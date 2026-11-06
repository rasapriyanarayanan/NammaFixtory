import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["NAMMAFIXTORY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import app as appmod  # noqa: E402
import synth  # noqa: E402
from ai import detect, nlp  # noqa: E402
from ai.evidence import compare  # noqa: E402

KEY = {"X-Officer-Key": "demo123"}


def photo(kind="pothole", **kw):
    p = os.path.join(tempfile.mkdtemp(), "x.jpg")
    getattr(synth, kind)(p, **kw)
    return p


class NLPTests(unittest.TestCase):
    def test_language(self):
        self.assertEqual(nlp.detect_language("சாலையில் பெரிய பள்ளம்"), "ta")
        self.assertEqual(nlp.detect_language("big pothole here"), "en")

    def test_classify(self):
        self.assertEqual(nlp.classify_text("சாலையில் பெரிய பள்ளம் உள்ளது")["category"], "pothole")
        self.assertEqual(nlp.classify_text("drain is blocked and overflowing")["category"], "blocked_drain")
        self.assertEqual(nlp.classify_text("garbage everywhere")["category"], "garbage")
        self.assertIsNone(nlp.classify_text("hello there")["category"])


class VisionTests(unittest.TestCase):
    def test_detector_runs(self):
        r = detect.analyse_image(photo("pothole", seed=1))
        self.assertIn(r["category"], {"pothole", "road_crack", "garbage", "other"})
        self.assertLessEqual(r["confidence"], 0.80)

    def test_evidence_identical_is_insufficient(self):
        p = photo("pothole", seed=7)
        self.assertEqual(compare(p, p)["result"], "insufficient")

    def test_evidence_repair_needs_confirmation(self):
        before, after = photo("pothole", seed=7), photo("pothole", seed=7, repaired=True)
        self.assertEqual(compare(before, after)["result"], "consistent_pending_confirmation")


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()
        cls.client.post("/api/demo/reset")

    def test_01_officer_endpoints_need_key(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/api/dashboard", headers=KEY).status_code, 200)

    def test_02_validation(self):
        r = self.client.post("/api/complaints", data={"description": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/complaints", data={"lat": "13", "lon": "80"})
        self.assertEqual(r.status_code, 400)
        bad = {"lat": "13", "lon": "80", "description": "pothole",
               "image": (io.BytesIO(b"not an image"), "x.jpg")}
        self.assertEqual(self.client.post("/api/complaints", data=bad,
                                          content_type="multipart/form-data").status_code, 400)

    def test_03_full_lifecycle(self):
        lat, lon = 13.2001, 80.3001  # away from sample data
        def report(desc, dlat=0.0, seed=1):
            with open(photo("pothole", seed=seed), "rb") as fh:
                return self.client.post("/api/complaints", data={
                    "lat": str(lat + dlat), "lon": str(lon), "description": desc,
                    "image": (io.BytesIO(fh.read()), "p.jpg")}, content_type="multipart/form-data")
        a = report("pothole near the bus stop")
        self.assertEqual(a.status_code, 201)
        ja = a.get_json()
        self.assertEqual(ja["category"], "pothole")
        self.assertTrue(ja["ref"].startswith("NFX-"))
        self.assertIsNone(ja["duplicate"])
        b = report("pothole on the road near bus stop", dlat=0.00003).get_json()
        self.assertIsNotNone(b["duplicate"], "second report of same pothole should be flagged")
        self.assertEqual(b["asset_id"], ja["asset_id"])
        # both reports retained
        self.assertEqual(self.client.get(f"/api/complaints/{ja['ref']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/complaints/{b['ref']}").status_code, 200)

        # repair (officer) with an after photo
        after = photo("pothole", seed=1, repaired=True)
        with open(after, "rb") as fh:
            r = self.client.post(f"/api/assets/{ja['asset_id']}/repair", headers=KEY, data={
                "officer": "T", "image": (io.BytesIO(fh.read()), "a.jpg")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.get_json()["evidence"])
        self.assertEqual(self.client.get(f"/api/complaints/{ja['ref']}").get_json()["status"], "resolved")

        # damage returns -> recurrence
        c = report("pothole again!", seed=5).get_json()
        self.assertEqual(c["asset_id"], ja["asset_id"])
        self.assertTrue(c["recurrence_detected"])
        self.assertIsNone(c["duplicate"], "post-repair report is a new episode, not a duplicate")
        asset = self.client.get(f"/api/assets/{ja['asset_id']}").get_json()
        self.assertEqual(asset["recurrences"], 1)
        self.assertEqual(asset["episodes"], 2)

    def test_04_public_privacy(self):
        with open(photo("pothole", seed=9), "rb") as fh:
            r = self.client.post("/api/complaints", data={
                "lat": "13.30011", "lon": "80.40011", "description": "pothole", "name": "Asha",
                "contact": "9999999999", "consent": "1", "image": (io.BytesIO(fh.read()), "p.jpg")},
                content_type="multipart/form-data").get_json()
        pub = self.client.get(f"/api/complaints/{r['ref']}").get_json()
        self.assertNotIn("contact", str(pub))
        self.assertNotIn("user_id", pub)
        self.assertEqual(pub["lat"], round(13.30011, 4))
        m = self.client.get("/api/map").get_json()
        self.assertNotIn("9999999999", str(m))

    def test_05_demo_scenario(self):
        self.client.post("/api/demo/reset")
        out = [self.client.post(f"/api/demo/step/{i}").get_json() for i in range(1, 6)]
        self.assertIsNotNone(out[1]["result"]["duplicate"])
        self.assertIn(out[2]["result"]["evidence"]["result"],
                      {"consistent_pending_confirmation", "needs_review", "insufficient"})
        self.assertTrue(out[4]["result"]["recurrence_detected"])
        self.assertEqual(out[4]["result"]["asset"]["recurrences"], 1)

    def test_06_dashboard_and_report(self):
        d = self.client.get("/api/dashboard", headers=KEY).get_json()
        self.assertGreater(d["total"], 0)
        self.assertEqual(self.client.get("/api/export/maintenance-report", headers=KEY).status_code, 200)
        self.assertEqual(self.client.get("/api/queue?category=pothole", headers=KEY).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
