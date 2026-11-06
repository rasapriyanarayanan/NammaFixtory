"""Civic issue detection from a photograph.

Two detectors, chosen automatically:

1. YOLO (ultralytics) -- used ONLY if the `ultralytics` package is installed and a
   trained weights file exists at models/civic_yolo.pt (train it on RDD2020 plus
   local Tamil Nadu photos; see docs/MODEL_EVALUATION.md).
2. OpenCV heuristic baseline -- always available. It looks at dark-region area,
   edge density and colour variance. It is NOT a trained model: confidences are
   deliberately capped and every result is sent for human confirmation.
"""
import os

import cv2
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEIGHTS = os.path.join(BASE, "models", "civic_yolo.pt")
_yolo = None
_yolo_tried = False

CLASS_MAP = {  # labels a trained YOLO model is expected to emit -> our categories
    "pothole": "pothole",
    "D40": "pothole",
    "crack": "road_crack",
    "D00": "road_crack",
    "D10": "road_crack",
    "D20": "road_crack",
    "garbage": "garbage",
    "waste": "garbage",
}


def _load_yolo():
    global _yolo, _yolo_tried
    if _yolo_tried:
        return _yolo
    _yolo_tried = True
    try:
        from ultralytics import YOLO  # type: ignore

        if os.path.exists(WEIGHTS):
            _yolo = YOLO(WEIGHTS)
    except Exception:
        _yolo = None
    return _yolo


def image_quality(img) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    bright = float(gray.mean())
    issues = []
    if blur < 40:
        issues.append("image looks blurry")
    if bright < 40:
        issues.append("image is very dark")
    if bright > 225:
        issues.append("image is overexposed")
    h, w = gray.shape
    if min(h, w) < 200:
        issues.append("image resolution is low")
    return {"sharpness": round(blur, 1), "brightness": round(bright, 1), "issues": issues}


def _heuristic(img) -> dict:
    img = cv2.resize(img, (320, int(320 * img.shape[0] / img.shape[1])))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    smooth = cv2.GaussianBlur(gray, (7, 7), 0)

    # dark compact region (pothole-like): Otsu on the lower tail
    thr = min(int(np.percentile(smooth, 18)), 90)
    dark = (smooth <= thr).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_total = dark.shape[0] * dark.shape[1]
    best_area, best_circ = 0.0, 0.0
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 0.01 * area_total:
            continue
        p = cv2.arcLength(c, True) or 1
        circ = 4 * np.pi * a / (p * p)
        if a > best_area:
            best_area, best_circ = a, circ
    dark_frac = best_area / area_total

    edges = cv2.Canny(smooth, 60, 140)
    edge_density = float(edges.mean() / 255)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 40, minLineLength=60, maxLineGap=8)
    n_lines = 0 if lines is None else len(lines)

    sat_frac = float((hsv[..., 1] > 60).mean())          # share of strongly coloured pixels
    # thin dark line-like structures (cracks): black-hat transform, then keep elongated blobs
    bh = cv2.morphologyEx(smooth, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    thin = (bh > 18).astype(np.uint8)
    thin_frac = float(thin.mean())
    n_lab, _, stats, _ = cv2.connectedComponentsWithStats(thin)
    n_elong = sum(1 for i in range(1, n_lab)
                  if stats[i, 4] >= 25 and max(stats[i, 2], stats[i, 3]) >= 25
                  and stats[i, 4] / float(stats[i, 2] * stats[i, 3]) < 0.5)

    scores = {
        "pothole": 0.0,
        "road_crack": 0.0,
        "garbage": 0.0,
        "other": 0.15,
    }
    if 0.015 < dark_frac < 0.55:
        scores["pothole"] = 0.35 + 0.35 * min(1.0, best_circ / 0.6) + 0.15 * min(1.0, dark_frac * 4)
    if 0.006 <= thin_frac <= 0.05 and n_elong >= 1 and dark_frac < 0.02 and sat_frac < 0.06:
        scores["road_crack"] = 0.35 + min(0.30, thin_frac * 12 + 0.05 * n_elong)
    elif n_lines >= 3 and dark_frac < 0.02 and sat_frac < 0.06:
        scores["road_crack"] = 0.30 + min(0.30, n_lines / 40)
    if sat_frac >= 0.08 and edge_density > 0.02:
        scores["garbage"] = 0.35 + min(0.40, sat_frac * 1.2 + edge_density * 2)

    cat = max(scores, key=scores.get)
    conf = min(scores[cat], 0.80)  # cap: untrained baseline
    return {
        "category": cat,
        "confidence": round(conf, 2),
        "detector": "opencv-heuristic-baseline",
        "detail": {
            "dark_region_fraction": round(dark_frac, 3),
            "edge_density": round(edge_density, 3),
            "line_segments": int(n_lines),
            "thin_dark_fraction": round(thin_frac, 4),
            "elongated_blobs": int(n_elong),
            "coloured_pixel_fraction": round(sat_frac, 3),
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "note": "Untrained heuristic baseline calibrated on synthetic images only. Human confirmation required.",
        },
    }


def analyse_image(path: str) -> dict:
    img = cv2.imread(path)
    if img is None:
        return {"category": "other", "confidence": 0.0, "detector": "none",
                "detail": {"error": "unreadable image"}, "quality": {"issues": ["image unreadable"]}}
    quality = image_quality(img)
    model = _load_yolo()
    if model is not None:
        try:
            res = model.predict(path, verbose=False)[0]
            best = None
            for b in res.boxes:
                name = res.names[int(b.cls)]
                cat = CLASS_MAP.get(name)
                if cat and (best is None or float(b.conf) > best[1]):
                    best = (cat, float(b.conf), name)
            if best:
                return {"category": best[0], "confidence": round(best[1], 2), "detector": "yolo",
                        "detail": {"raw_class": best[2]}, "quality": quality}
        except Exception as exc:  # fall through to baseline
            pass
    out = _heuristic(img)
    out["quality"] = quality
    return out
