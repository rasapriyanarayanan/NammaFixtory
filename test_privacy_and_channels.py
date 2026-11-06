"""Tests for photo privacy (face/plate blurring + fail-closed gate) and the WhatsApp channel."""
import hashlib
import hmac
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["NAMMAFIXTORY_DB"] = os.path.join(tempfile.mkdtemp(), "test_pc.db")

import app as appmod  # noqa: E402
import core  # noqa: E402
import db  # noqa: E402
import synth  # noqa: E402
from ai import privacy  # noqa: E402
from channels import whatsapp  # noqa: E402
from util import iso, now  # noqa: E402

KEY = {"X-Officer-Key": "demo123"}


def photo(**kw):
    p = os.path.join(tempfile.mkdtemp(), "x.jpg")
    synth.pothole(p, **kw)
    return p


def upload(client, path, **extra):
    data = {"lat": "13.05", "lon": "80.25", "description": "pothole near the school",
            "image": (open(path, "rb"), "x.jpg"), **extra}
    return client.post("/api/complaints", data=data, content_type="multipart/form-data")


class StubCascade:
    """Stands in for an OpenCV Haar cascade so the blurring path can be tested without the model files."""

    def __init__(self, boxes):
        self.boxes = boxes

    def detectMultiScale(self, *a, **k):
        return np.array(self.boxes, dtype=int).reshape(-1, 4) if self.boxes else []


class PrivacyModuleTests(unittest.TestCase):
    def test_blur_regions_changes_only_the_box(self):
        p = photo(seed=3)
        before = np.array(Image.open(p).convert("RGB")).astype(float)
        n = privacy.blur_regions(p, [(100, 100, 80, 60), (9999, 9999, 10, 10)])  # 2nd box is off-image
        after = np.array(Image.open(p).convert("RGB")).astype(float)
        self.assertEqual(n, 1)
        inside = (slice(100, 160), slice(100, 180))
        self.assertLess(after[inside].std(), before[inside].std())   # blurred area is smoother
        self.assertLess(np.abs(after[300:, :50] - before[300:, :50]).mean(), 6)  # elsewhere ~unchanged (JPEG noise only)

    def test_no_detector_fails_closed(self):
        old = privacy._find
        privacy._find = lambda names: None
        try:
            r = privacy.protect_image(photo(seed=4))
        finally:
            privacy._find = old
        self.assertEqual(r["status"], "detector_unavailable")  # never reported as "checked and clean"

    def test_stub_detector_blurs_and_reports(self):
        p = photo(seed=5)
        old = privacy._load
        privacy._load = lambda names: StubCascade([(120, 120, 90, 90)] if "face" in names[0] else [])
        try:
            r = privacy.protect_image(p)
        finally:
            privacy._load = old
        self.assertEqual((r["status"], r["faces"], r["plates"]), ("blurred", 1, 0))

    def test_stub_detector_nothing_found(self):
        old = privacy._load
        privacy._load = lambda names: StubCascade([])
        try:
            r = privacy.protect_image(photo(seed=6))
        finally:
            privacy._load = old
        self.assertEqual(r["status"], "none_found")

    def test_unreadable_file_fails_closed(self):
        old = privacy._load
        privacy._load = lambda names: StubCascade([])
        try:
            r = privacy.protect_image("/nonexistent/photo.jpg")
        finally:
            privacy._load = old
        self.assertEqual(r["status"], "detector_unavailable")

    def test_migration_adds_column_and_marks_samples(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""CREATE TABLE complaints(complaint_id INTEGER PRIMARY KEY, is_sample INTEGER);
            CREATE TABLE complaint_images(image_id INTEGER PRIMARY KEY, complaint_id INTEGER, path TEXT);
            INSERT INTO complaints VALUES (1,1),(2,0);
            INSERT INTO complaint_images VALUES (1,1,'a.jpg'),(2,2,'b.jpg');""")
        db._migrate(con)
        got = {r["path"]: r["privacy"] for r in con.execute("SELECT path,privacy FROM complaint_images")}
        self.assertEqual(got, {"a.jpg": "synthetic", "b.jpg": None})  # real photo stays unchecked -> held


class PrivacyGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()
        cls.client.post("/api/demo/reset")

    def test_real_photo_without_detector_is_held_from_public(self):
        old = privacy._find
        privacy._find = lambda names: None
        try:
            r = upload(self.client, photo(seed=11))
        finally:
            privacy._find = old
        out = r.get_json()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(out["photo_privacy"], "detector_unavailable")
        self.assertFalse(out["photo_public"])
        pub = self.client.get("/api/complaints/" + out["ref"]).get_json()
        self.assertEqual(pub["images"], [])
        self.assertEqual(pub["images_held"], 1)
        off = self.client.get("/api/complaints/" + out["ref"], headers=KEY).get_json()
        name = off["images"][0]
        self.assertFalse(off["image_info"][0]["public"])
        self.assertEqual(self.client.get("/uploads/" + name).status_code, 403)
        self.assertEqual(self.client.get("/uploads/" + name, headers=KEY).status_code, 200)

        # officer review: needs the key, is audited, and releases the photo
        self.assertEqual(self.client.post(f"/api/images/{name}/privacy", json={"action": "clear"}).status_code, 401)
        self.assertEqual(self.client.post(f"/api/images/{name}/privacy", json={"action": "x"},
                                          headers=KEY).status_code, 400)
        ok = self.client.post(f"/api/images/{name}/privacy", json={"action": "clear"}, headers=KEY)
        self.assertEqual(ok.get_json()["privacy"], "officer_cleared")
        self.assertEqual(self.client.get("/uploads/" + name).status_code, 200)
        actions = [a["action"] for a in self.client.get("/api/audit", headers=KEY).get_json()]
        self.assertIn("photo_officer_cleared", actions)

    def test_officer_manual_blur_releases_photo(self):
        old = privacy._find
        privacy._find = lambda names: None
        try:
            out = upload(self.client, photo(seed=12)).get_json()
        finally:
            privacy._find = old
        name = self.client.get("/api/complaints/" + out["ref"], headers=KEY).get_json()["images"][0]
        self.assertEqual(self.client.post(f"/api/images/{name}/privacy", json={"action": "blur", "boxes": []},
                                          headers=KEY).status_code, 400)
        r = self.client.post(f"/api/images/{name}/privacy",
                             json={"action": "blur", "boxes": [[50, 50, 100, 100]]}, headers=KEY).get_json()
        self.assertEqual((r["privacy"], r["boxes_blurred"]), ("officer_blurred", 1))
        self.assertEqual(self.client.get("/uploads/" + name).status_code, 200)

    def test_detector_clean_photo_is_public_immediately(self):
        old = privacy._load
        privacy._load = lambda names: StubCascade([])
        try:
            out = upload(self.client, photo(seed=13)).get_json()
        finally:
            privacy._load = old
        self.assertEqual(out["photo_privacy"], "none_found")
        pub = self.client.get("/api/complaints/" + out["ref"]).get_json()
        self.assertEqual(len(pub["images"]), 1)
        self.assertEqual(self.client.get("/uploads/" + pub["images"][0]).status_code, 200)

    def test_sample_photos_stay_public_and_unknown_files_404(self):
        self.client.post("/api/demo/step/1")
        self.assertEqual(self.client.get("/uploads/demo_a.jpg").status_code, 200)
        self.assertEqual(self.client.get("/uploads/does_not_exist.jpg").status_code, 404)
        self.assertEqual(self.client.get("/uploads/../app.py").status_code, 404)

    def test_meta_reports_detectors_and_whatsapp(self):
        m = self.client.get("/api/meta").get_json()
        self.assertEqual(set(m["privacy_detectors"]), {"face", "plate"})
        self.assertTrue(m["whatsapp"]["simulator"])


class WhatsAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()

    def setUp(self):
        self.client.post("/api/demo/reset")
        os.environ.pop("WHATSAPP_APP_SECRET", None)

    def sim(self, sender="919876500001", **f):
        return self.client.post("/api/channels/simulate", data={"sender": sender, **f}).get_json()

    def test_text_then_location_files_a_complaint(self):
        r1 = self.sim(type="text", text="Big pothole near the bus stop")
        self.assertIsNone(r1["ref"])
        self.assertIn("location", r1["replies"][0].lower())
        r2 = self.sim(type="location", lat="13.0501", lon="80.2501")
        self.assertRegex(r2["ref"], r"^NFX-\d{6}-[0-9A-F]{4}$")
        self.assertIn("Pothole", r2["replies"][0])
        c = self.client.get("/api/complaints/" + r2["ref"], headers=KEY).get_json()
        self.assertEqual(c["channel"], "whatsapp")

    def test_location_first_then_text_and_tamil_reply(self):
        self.sim(sender="919876500002", type="location", lat="13.06", lon="80.26")
        r = self.sim(sender="919876500002", type="text", text="சாலையில் பெரிய பள்ளம் உள்ளது")
        self.assertIsNotNone(r["ref"])
        self.assertIn("புகார் பெறப்பட்டது", r["replies"][0])

    def test_image_flow_and_privacy_gate(self):
        old = privacy._find
        privacy._find = lambda names: None
        try:
            self.sim(sender="919876500003", type="location", lat="13.07", lon="80.27")
            r = self.client.post("/api/channels/simulate", data={
                "sender": "919876500003", "type": "image", "text": "pothole near school",
                "image": (open(photo(seed=21), "rb"), "p.jpg")}, content_type="multipart/form-data").get_json()
        finally:
            privacy._find = old
        self.assertIsNotNone(r["ref"])
        pub = self.client.get("/api/complaints/" + r["ref"]).get_json()
        self.assertEqual((pub["images"], pub["images_held"]), ([], 1))  # WhatsApp photos obey the same gate

    def test_status_lookup_and_unknown_reference(self):
        ref = self.sim(type="text", text="drain blocked and overflowing")["ref"] or \
            self.sim(type="location", lat="13.08", lon="80.28")["ref"]
        r = self.sim(type="text", text="status " + ref)
        self.assertIn(ref, r["replies"][0])
        self.assertIn("could not find", self.sim(type="text", text="status NFX-000000-0000")["replies"][0])

    def test_greeting_help_and_bad_input(self):
        self.assertEqual(len(self.sim(type="text", text="hi")["replies"]), 2)  # English + Tamil
        self.assertEqual(self.client.post("/api/channels/simulate", data={"type": "video"}).status_code, 400)
        self.assertEqual(self.client.post("/api/channels/simulate", data={"type": "image"}).status_code, 400)
        r = self.sim(type="location", lat="999", lon="80")
        self.assertIsNone(r["ref"])
        r = self.sim(type="location", lat="abc", lon="80")
        self.assertIsNone(r["ref"])

    def test_phone_number_is_never_stored(self):
        sender = "919812345678"
        self.sim(sender=sender, type="text", text="pothole here")  # leaves a half-finished session
        con = db.connect()
        try:
            dump = " ".join(str(tuple(r)) for t in ("channel_sessions", "complaints", "users", "audit_log")
                            for r in con.execute(f"SELECT * FROM {t}"))
            self.assertNotIn(sender, dump)
            self.assertEqual(con.execute("SELECT sender_hash FROM channel_sessions").fetchone()[0],
                             whatsapp.sender_hash(sender))
        finally:
            con.close()

    def test_session_expires_after_30_minutes(self):
        sender = "919800000009"
        self.sim(sender=sender, type="text", text="pothole near the temple")
        con = db.connect()
        con.execute("UPDATE channel_sessions SET updated_at=?", (iso(now() - timedelta(minutes=45)),))
        con.commit()
        con.close()
        r = self.sim(sender=sender, type="location", lat="13.09", lon="80.29")
        self.assertIsNone(r["ref"])  # the old description was discarded, so only a location is not enough

    def test_session_cleared_after_filing(self):
        self.sim(sender="919800000010", type="text", text="pothole")
        self.sim(sender="919800000010", type="location", lat="13.1", lon="80.3")
        con = db.connect()
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM channel_sessions").fetchone()[0], 0)
        finally:
            con.close()

    # ---- Meta Cloud API webhook
    def test_webhook_verification(self):
        ok = self.client.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=nammafixtory-verify&hub.challenge=42")
        self.assertEqual((ok.status_code, ok.data), (200, b"42"))
        bad = self.client.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42")
        self.assertEqual(bad.status_code, 403)

    @staticmethod
    def payload(*msgs):
        return {"entry": [{"changes": [{"value": {"messages": list(msgs)}}]}]}

    def test_webhook_accepts_text_and_location_messages(self):
        wa = "919855500000"
        r1 = self.client.post("/webhook/whatsapp", json=self.payload(
            {"from": wa, "type": "text", "text": {"body": "pothole near the school gate"}}))
        r2 = self.client.post("/webhook/whatsapp", json=self.payload(
            {"from": wa, "type": "location", "location": {"latitude": 13.11, "longitude": 80.31}}))
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        con = db.connect()
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM complaints WHERE channel='whatsapp'").fetchone()[0], 1)
        finally:
            con.close()

    def test_webhook_signature_enforced_when_secret_set(self):
        os.environ["WHATSAPP_APP_SECRET"] = "s3cret"
        try:
            body = json.dumps(self.payload({"from": "1", "type": "text", "text": {"body": "hi"}})).encode()
            hdr = {"Content-Type": "application/json"}
            self.assertEqual(self.client.post("/webhook/whatsapp", data=body, headers=hdr).status_code, 403)
            sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
            self.assertEqual(self.client.post("/webhook/whatsapp", data=body,
                                              headers={**hdr, "X-Hub-Signature-256": sig}).status_code, 200)
        finally:
            os.environ.pop("WHATSAPP_APP_SECRET", None)

    def test_webhook_image_without_credentials_is_handled(self):
        r = self.client.post("/webhook/whatsapp", json=self.payload(
            {"from": "919800000077", "type": "image", "image": {"id": "MEDIA1", "caption": "pothole"}}))
        self.assertEqual(r.status_code, 200)  # no token -> media cannot be fetched; must not crash


if __name__ == "__main__":
    unittest.main()
