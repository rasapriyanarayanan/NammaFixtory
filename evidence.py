"""Repair-evidence review: compares the before photo with the after photo.

The module only produces a RECOMMENDATION for an officer. It never certifies a repair.
Outcomes:
  consistent_pending_confirmation - the scene matches and the damaged region changed
  needs_review                    - inconclusive (different viewpoint, poor quality, etc.)
  insufficient                    - photos look identical / same photo reused / unusable
"""
import cv2
import numpy as np
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS


def exif_info(path):
    try:
        with Image.open(path) as im:
            raw = im._getexif() or {}
    except Exception:
        return {"has_exif": False}
    info = {"has_exif": bool(raw)}
    for k, v in raw.items():
        tag = TAGS.get(k, k)
        if tag == "DateTimeOriginal":
            info["taken_at"] = str(v)
        if tag == "GPSInfo":
            gps = {GPSTAGS.get(t, t): v[t] for t in v}
            info["has_gps"] = bool(gps)
    return info


def _load(path, w=320):
    img = cv2.imread(path)
    if img is None:
        return None
    return cv2.resize(img, (w, int(w * img.shape[0] / img.shape[1])))


def compare(before_path, after_path):
    b, a = _load(before_path), _load(after_path)
    if b is None or a is None:
        return {"result": "insufficient", "reasons": ["one of the photos could not be read"], "metrics": {}}
    a = cv2.resize(a, (b.shape[1], b.shape[0]))
    gb, ga = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)

    diff = cv2.absdiff(gb, ga)
    changed_frac = float((diff > 35).mean())
    mean_diff = float(diff.mean())

    orb = cv2.ORB_create(500)
    kb, db_ = orb.detectAndCompute(gb, None)
    ka, da = orb.detectAndCompute(ga, None)
    good = 0
    if db_ is not None and da is not None and len(db_) > 10 and len(da) > 10:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(bf.match(db_, da), key=lambda m: m.distance)
        good = sum(1 for m in matches if m.distance < 40)
    match_ratio = good / max(1, min(len(kb or []), len(ka or [])))

    # second scene signal: correlation of heavily blurred low-resolution layouts
    def layout(g):
        return cv2.resize(cv2.GaussianBlur(g, (21, 21), 0), (32, 24)).astype(np.float32).ravel()
    lb, la = layout(gb), layout(ga)
    struct_corr = float(np.corrcoef(lb, la)[0, 1]) if lb.std() > 0 and la.std() > 0 else 0.0
    scene_ok = good >= 15 or match_ratio >= 0.04 or struct_corr >= 0.85

    # darkness of the darkest blob before vs after (a filled pothole is less dark)
    def dark_frac(g):
        return float((cv2.GaussianBlur(g, (7, 7), 0) <= min(int(np.percentile(g, 18)), 90)).mean())

    reasons, result = [], "needs_review"
    if mean_diff < 2.0 and changed_frac < 0.003:
        result = "insufficient"
        reasons.append("after photo is virtually identical to the before photo (unchanged damage or reused photo)")
    elif not scene_ok:
        result = "needs_review"
        reasons.append("scene could not be matched: different viewpoint or location; officer should verify")
    elif changed_frac >= 0.02:
        result = "consistent_pending_confirmation"
        reasons.append("same scene, with a visible change in the damaged region")
    else:
        result = "needs_review"
        reasons.append("only a small change was detected")

    qa = cv2.Laplacian(ga, cv2.CV_64F).var()
    if qa < 40:
        reasons.append("after photo is blurry")
        if result == "consistent_pending_confirmation":
            result = "needs_review"
    return {
        "result": result,
        "reasons": reasons,
        "metrics": {
            "scene_match_keypoints": int(good),
            "scene_match_ratio": round(match_ratio, 3),
            "layout_correlation": round(struct_corr, 3),
            "changed_pixel_fraction": round(changed_frac, 3),
            "mean_abs_difference": round(mean_diff, 2),
            "dark_region_before": round(dark_frac(gb), 3),
            "dark_region_after": round(dark_frac(ga), 3),
        },
        "note": "Recommendation only. An officer must confirm; photos alone never certify a repair.",
    }
