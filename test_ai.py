"""Unit tests for the AI modules (run: python3 -m pytest tests)."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["NAMMAFIXTORY_DB"] = os.path.join(tempfile.mkdtemp(), "ai.db")

import core  # noqa: E402
import db  # noqa: E402
import synth  # noqa: E402
from ai import detect, nlp  # noqa: E402
from ai.duplicates import RADIUS_M, THRESHOLD, WEIGHTS, score_pair  # noqa: E402
from ai.evidence import compare  # noqa: E402
from ai.hotspots import hotspots  # noqa: E402
from ai.recurrence import asset_summary  # noqa: E402
from util import haversine_m, iso, now  # noqa: E402


def photo(kind="pothole", **kw):
    p = os.path.join(tempfile.mkdtemp(), "x.jpg")
    getattr(synth, kind)(p, **kw)
    return p


_ORIG_DB = db.DB_PATH
_AI_DB = os.path.join(tempfile.mkdtemp(), "ai_unit.db")


def tearDownModule():
    db.DB_PATH = _ORIG_DB


def fresh():
    db.DB_PATH = _AI_DB      # never touch the database the API tests use
    db.reset_db()
    db.init_db()
    c = db.connect()
    c.execute("INSERT INTO wards VALUES (1,'Ward A',13.0827,80.2707)")
    c.commit()
    return c


class DetectorTests(unittest.TestCase):
    def test_each_synthetic_class(self):
        self.assertEqual(detect.analyse_image(photo("pothole", seed=1))["category"], "pothole")
        self.assertEqual(detect.analyse_image(photo("garbage", seed=2))["category"], "garbage")
        self.assertEqual(detect.analyse_image(photo("crack", seed=3))["category"], "road_crack")

    def test_clean_road_is_other(self):
        p = os.path.join(tempfile.mkdtemp(), "c.jpg")
        synth._asphalt(640, 480, 9).save(p, quality=88)
        self.assertEqual(detect.analyse_image(p)["category"], "other")

    def test_confidence_capped_and_never_certain(self):
        r = detect.analyse_image(photo("pothole", seed=1))
        self.assertLessEqual(r["confidence"], 0.80)

    def test_unreadable_file(self):
        p = os.path.join(tempfile.mkdtemp(), "bad.jpg")
        open(p, "wb").write(b"not an image")
        r = detect.analyse_image(p)
        self.assertEqual(r["category"], "other")
        self.assertEqual(r["confidence"], 0.0)


class NLPTests(unittest.TestCase):
    def test_whole_word_matching(self):
        self.assertEqual(nlp.classify_text("pipe leaking, water wasted on the road")["category"], "water_leakage")
        self.assertEqual(nlp.classify_text("garbage everywhere")["category"], "garbage")

    def test_tamil_stagnant_water(self):
        self.assertEqual(nlp.classify_text("மழை நீர் தேங்கி நிற்கிறது")["category"], "waterlogging")

    def test_safety_cues_and_location(self):
        s = nlp.structure_complaint("Deep pothole near the school, a child fell at night")
        self.assertIn("school", s["safety_cues"])
        self.assertTrue(s["location_hint"])

    def test_text_similarity_orders(self):
        near = nlp.text_similarity("pothole near bus stop", "big pothole near the bus stop")
        far = nlp.text_similarity("pothole near bus stop", "garbage piled at market")
        self.assertGreater(near, far)


class DuplicateTests(unittest.TestCase):
    def test_same_spot_scores_above_threshold(self):
        a, b = photo("pothole", seed=1), photo("pothole", seed=1, shift=6)
        s = score_pair({"lat": 13.0, "lon": 80.0, "description": "pothole near bus stop"},
                       {"lat": 13.00003, "lon": 80.0, "description": "big pothole near the bus stop"}, a, b)
        self.assertGreaterEqual(s["score"], THRESHOLD)

    def test_far_apart_never_duplicate(self):
        a = photo("pothole", seed=1)
        s = score_pair({"lat": 13.0, "lon": 80.0, "description": "pothole"},
                       {"lat": 13.002, "lon": 80.0, "description": "pothole"}, a, a)
        self.assertLess(s["score"], THRESHOLD)
        self.assertGreater(haversine_m(13.0, 80.0, 13.002, 80.0), RADIUS_M)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0)


class HotspotTests(unittest.TestCase):
    def test_cluster_found_and_outlier_ignored(self):
        pts = [{"lat": 13.0 + i * 0.0001, "lon": 80.0} for i in range(4)] + [{"lat": 13.5, "lon": 80.5}]
        h = hotspots(pts, eps_m=80, min_samples=3)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["size"], 4)

    def test_too_few_points(self):
        self.assertEqual(hotspots([{"lat": 1, "lon": 1}], min_samples=3), [])


class EvidenceTests(unittest.TestCase):
    def test_repaired_vs_unrepaired(self):
        before = photo("pothole", seed=1)
        self.assertEqual(compare(before, photo("pothole", seed=1, repaired=True))["result"],
                         "consistent_pending_confirmation")
        self.assertNotEqual(compare(before, photo("pothole", seed=1, shift=1))["result"],
                            "consistent_pending_confirmation")

    def test_never_auto_certifies(self):
        r = compare(photo("pothole", seed=1), photo("pothole", seed=1, repaired=True))
        self.assertNotIn(r["result"], ("repaired", "complete", "certified"))

    def test_unreadable_photo_is_insufficient(self):
        bad = os.path.join(tempfile.mkdtemp(), "bad.jpg")
        open(bad, "wb").write(b"nope")
        self.assertEqual(compare(photo("pothole"), bad)["result"], "insufficient")


class PipelineTests(unittest.TestCase):
    LAT, LON = 13.0827, 80.2707

    def test_recurrence_lifecycle(self):
        c = fresh()
        r1 = core.submit_complaint(c, description="pothole on road", lat=self.LAT, lon=self.LON,
                                   image_path=photo("pothole", seed=1), created_at=iso(now(-120)))
        core.complete_repair(c, r1["asset_id"], officer="T", notes="patch",
                             after_image=photo("pothole", seed=1, repaired=True), completed_at=iso(now(-100)))
        r2 = core.submit_complaint(c, description="the pothole is back", lat=self.LAT, lon=self.LON + 0.00002,
                                   image_path=photo("pothole", seed=2), created_at=iso(now(-40)))
        self.assertEqual(r1["asset_id"], r2["asset_id"])           # same infrastructure asset
        self.assertTrue(r2["recurrence_detected"])
        a = asset_summary(c, r1["asset_id"], now(), full=True)
        self.assertEqual(a["recurrences"], 1)
        self.assertTrue(a["inspection_flag"])
        self.assertTrue(a["flag_reasons"])

    def test_recurrence_when_everything_happens_in_the_same_second(self):
        c = fresh()
        t = iso(now())
        r1 = core.submit_complaint(c, description="pothole", lat=self.LAT, lon=self.LON, created_at=t)
        core.complete_repair(c, r1["asset_id"], officer="T", completed_at=t)
        r2 = core.submit_complaint(c, description="pothole again", lat=self.LAT, lon=self.LON, created_at=t)
        self.assertTrue(r2["recurrence_detected"])

    def test_old_resolved_complaints_do_not_become_duplicates(self):
        c = fresh()
        core.submit_complaint(c, description="pothole", lat=self.LAT, lon=self.LON, created_at=iso(now(-200)))
        r = core.submit_complaint(c, description="pothole", lat=self.LAT, lon=self.LON, created_at=iso(now(-1)))
        self.assertIsNone(r["duplicate"])

    def test_duplicate_keeps_both_reports(self):
        c = fresh()
        a = core.submit_complaint(c, description="pothole near bus stop", lat=self.LAT, lon=self.LON,
                                  image_path=photo("pothole", seed=1), created_at=iso(now(-3)))
        b = core.submit_complaint(c, description="big pothole near the bus stop", lat=self.LAT + 0.00003,
                                  lon=self.LON, image_path=photo("pothole", seed=1, shift=5), created_at=iso(now(-2)))
        self.assertIsNotNone(b["duplicate"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0], 2)

    def test_contact_only_stored_with_consent(self):
        c = fresh()
        core.submit_complaint(c, description="pothole", lat=self.LAT, lon=self.LON, name="Asha",
                              contact="9999999999", consent=False)
        self.assertIsNone(c.execute("SELECT contact FROM users").fetchone()["contact"])

    def test_priority_rises_near_school_and_with_recurrence(self):
        c = fresh()
        c.execute("INSERT INTO sensitive_places(name,kind,lat,lon) VALUES ('School','school',?,?)",
                  (self.LAT + 0.0003, self.LON))
        c.commit()
        near = core.submit_complaint(c, description="pothole", lat=self.LAT, lon=self.LON)
        far = core.submit_complaint(c, description="pothole", lat=self.LAT + 0.05, lon=self.LON + 0.05)
        self.assertGreater(near["priority"]["score"], far["priority"]["score"])
        self.assertTrue(all("why" in f for f in near["priority"]["factors"]))     # explainable


if __name__ == "__main__":
    unittest.main()
