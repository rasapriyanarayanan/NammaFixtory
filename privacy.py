"""Photo privacy: blur faces and vehicle number plates in citizen photos. (EXPERIMENTAL)

Why: citizens photograph roads, and people and vehicles end up in the frame. The project document requires
that faces and registration plates are masked before a photo is shown to anyone but authorised officers.

How it works
  * Detection uses OpenCV Haar cascades *if the cascade files are present* (looked for in ./models and in
    OpenCV's own data folder). Fetch them once with `scripts/fetch_cascades.sh` (needs internet).
  * If no cascade is available the photo is NOT silently treated as safe. The result says
    `detector_unavailable`, and the photo is flagged so only officers should see it.
  * `blur_regions()` can also blur boxes an officer marks by hand, for the cases the detector misses.

Known limits (be honest about these in any demo): Haar cascades miss side-on and small faces and many
Indian plate styles. This reduces risk, it does not guarantee anonymity. A production system should use a
stronger detector and keep originals access-controlled.
"""
import os

import cv2
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIRS = [os.path.join(BASE, "models"), getattr(getattr(cv2, "data", None), "haarcascades", "") or ""]
FACE_FILES = ["haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"]
PLATE_FILES = ["haarcascade_russian_plate_number.xml", "haarcascade_license_plate_rus_16stages.xml"]


def _find(names):
    for d in MODEL_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if d and os.path.isfile(p):
                return p
    return None


def _load(names):
    p = _find(names)
    if not p:
        return None
    c = cv2.CascadeClassifier(p)
    return None if c.empty() else c


def detectors_available() -> dict:
    return {"face": _find(FACE_FILES) is not None, "plate": _find(PLATE_FILES) is not None}


def _blur_box(arr, x, y, w, h):
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return False
    roi = arr[y0:y1, x0:x1]
    k = max(15, (max(x1 - x0, y1 - y0) // 2) | 1)  # odd, strong kernel
    arr[y0:y1, x0:x1] = cv2.GaussianBlur(roi, (k, k), 0)
    return True


def blur_regions(path: str, boxes, out_path: str = None) -> int:
    """Blur (x, y, w, h) boxes in an image file. Keeps EXIF. Returns how many boxes were blurred."""
    with Image.open(path) as im:
        exif = im.info.get("exif")
        rgb = np.array(im.convert("RGB"))
    n = sum(1 for b in boxes if _blur_box(rgb, *[int(v) for v in b]))
    save_kw = {"quality": 90}
    if exif:
        save_kw["exif"] = exif
    out = out_path or path
    fmt = "PNG" if out.lower().endswith(".png") else ("WEBP" if out.lower().endswith(".webp") else "JPEG")
    if fmt != "JPEG":
        save_kw = {}
    Image.fromarray(rgb).save(out, fmt, **save_kw)
    return n


def protect_image(path: str) -> dict:
    """Detect faces/plates and blur them in place.

    Returns {"status": "blurred"|"none_found"|"detector_unavailable", "faces": n, "plates": n}.
    """
    face_c, plate_c = _load(FACE_FILES), _load(PLATE_FILES)
    if face_c is None and plate_c is None:
        return {"status": "detector_unavailable", "faces": 0, "plates": 0}
    img = cv2.imread(path)
    if img is None:
        return {"status": "detector_unavailable", "faces": 0, "plates": 0}
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    min_side = max(24, min(img.shape[:2]) // 20)
    faces = face_c.detectMultiScale(gray, 1.1, 5, minSize=(min_side, min_side)) if face_c is not None else []
    plates = plate_c.detectMultiScale(gray, 1.1, 4, minSize=(min_side * 2, min_side)) if plate_c is not None else []
    boxes = [tuple(b) for b in faces] + [tuple(b) for b in plates]
    if not boxes:
        return {"status": "none_found", "faces": 0, "plates": 0}
    blur_regions(path, boxes)
    return {"status": "blurred", "faces": len(faces), "plates": len(plates)}
