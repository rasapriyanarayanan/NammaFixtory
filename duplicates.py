"""Duplicate complaint detection.

score = 0.50 * geo + 0.30 * text + 0.20 * image   (weights are explainable & tunable)
A match is only SUGGESTED. Both citizen reports are always retained; an officer can
confirm or reject the link.
"""
import cv2
import numpy as np

from ai.nlp import text_similarity
from util import FAMILY, haversine_m, parse

RADIUS_M = 40.0
WINDOW_DAYS = 60
THRESHOLD = 0.55
WEIGHTS = {"geo": 0.50, "text": 0.30, "image": 0.20}


def image_similarity(path_a, path_b) -> float:
    if not path_a or not path_b:
        return 0.0
    a, b = cv2.imread(path_a), cv2.imread(path_b)
    if a is None or b is None:
        return 0.0
    sims = []
    for ch in range(3):
        ha = cv2.calcHist([a], [ch], None, [32], [0, 256])
        hb = cv2.calcHist([b], [ch], None, [32], [0, 256])
        cv2.normalize(ha, ha)
        cv2.normalize(hb, hb)
        sims.append(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
    return float(max(0.0, np.mean(sims)))


def score_pair(new, other, new_img, other_img):
    d = haversine_m(new["lat"], new["lon"], other["lat"], other["lon"])
    geo = max(0.0, 1.0 - d / RADIUS_M)
    txt = text_similarity(new.get("description", ""), other.get("description", ""))
    img = image_similarity(new_img, other_img)
    total = WEIGHTS["geo"] * geo + WEIGHTS["text"] * txt + WEIGHTS["image"] * img
    return {
        "score": round(total, 3),
        "geo": round(geo, 3),
        "text": round(txt, 3),
        "image": round(img, 3),
        "distance_m": round(d, 1),
    }


def find_duplicate(conn, new, new_img, created_at, exclude_id=None):
    """Return best suggested match (dict) or None. `new` needs lat/lon/category/description."""
    fam = FAMILY.get(new["category"], "public")
    cur = conn.execute(
        """SELECT c.*, (SELECT path FROM complaint_images i WHERE i.complaint_id=c.complaint_id
                        ORDER BY image_id LIMIT 1) AS img
           FROM complaints c
           WHERE c.status IN ('open','under_review','in_repair')
             AND c.duplicate_state IS NOT 'rejected'"""
    ).fetchall()
    best = None
    now_dt = parse(created_at)
    for r in cur:
        r = dict(r)
        if exclude_id is not None and r["complaint_id"] == exclude_id:
            continue
        if parse(r["created_at"]) > now_dt:
            continue
        if FAMILY.get(r["category"], "public") != fam:
            continue
        if (now_dt - parse(r["created_at"])).days > WINDOW_DAYS:
            continue
        if haversine_m(new["lat"], new["lon"], r["lat"], r["lon"]) > RADIUS_M:
            continue
        s = score_pair(new, r, new_img, r.get("img"))
        if s["score"] >= THRESHOLD and (best is None or s["score"] > best["score"]["score"]):
            canonical = r["duplicate_of"] or r["complaint_id"]
            best = {"match": r, "canonical_id": canonical, "score": s}
    return best
