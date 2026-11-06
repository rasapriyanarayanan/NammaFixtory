#!/usr/bin/env python3
"""Reproducible evaluation of the prototype's components.

IMPORTANT: every number this script prints comes from SYNTHETIC images and hand-written
sample complaints. They show that the pipeline behaves as designed. They are NOT accuracy
claims for real Tamil Nadu roads. Real figures need a labelled local dataset (see
docs/MODEL_EVALUATION.md).

Run:  python3 scripts/evaluate.py            (writes docs/EVALUATION_RESULTS.md)
"""
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import synth  # noqa: E402
from ai import detect, nlp  # noqa: E402
from ai.duplicates import image_similarity  # noqa: E402
from ai.evidence import compare  # noqa: E402
from util import haversine_m  # noqa: E402


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 3), round(r, 3), round(f, 3)


# ---------------------------------------------------------------- 1. image detector
def eval_detector(tmp, n=30):
    makers = {"pothole": synth.pothole, "garbage": synth.garbage, "road_crack": synth.crack}
    classes = list(makers) + ["other"]
    conf = {a: {b: 0 for b in classes} for a in classes}
    for cls, fn in makers.items():
        for i in range(n):
            p = os.path.join(tmp, f"{cls}_{i}.jpg")
            fn(p, seed=1000 + i)
            pred = detect.analyse_image(p)["category"]
            conf[cls][pred if pred in classes else "other"] += 1
    for i in range(n):  # clean road photos: the detector should say "other"
        p = os.path.join(tmp, f"clean_{i}.jpg")
        synth._asphalt(640, 480, 50 + i).save(p, quality=88)
        pred = detect.analyse_image(p)["category"]
        conf["other"][pred if pred in classes else "other"] += 1
    rows = []
    for c in makers:
        tp = conf[c][c]
        fp = sum(conf[o][c] for o in makers if o != c)
        fn_ = sum(conf[c][o] for o in classes if o != c)
        rows.append((c, *prf(tp, fp, fn_)))
    acc = sum(conf[c][c] for c in classes) / (n * len(classes))
    return rows, round(acc, 3), conf


# ---------------------------------------------------------------- 2. text classifier
TEXT_CASES = [
    ("There is a big pothole on the road near the bus stop", "pothole"),
    ("kuzhi on the road, bikes are falling", "pothole"),
    ("பேருந்து நிலையம் அருகே சாலையில் பெரிய பள்ளம் உள்ளது", "pothole"),
    ("The drain is blocked and sewage is overflowing", "blocked_drain"),
    ("வடிகால் அடைப்பு, கழிவுநீர் தெருவில் ஓடுகிறது", "blocked_drain"),
    ("Water is stagnant on the street after rain, waterlogging", "waterlogging"),
    ("மழை நீர் தேங்கி நிற்கிறது", "waterlogging"),
    ("Garbage has piled up near the market for a week", "garbage"),
    ("குப்பை குவிந்து கிடக்கிறது, துர்நாற்றம்", "garbage"),
    ("Pipe leaking, drinking water is wasted on the road", "water_leakage"),
    ("Streetlight not working, the lane is dark", "streetlight"),
    ("Long cracks have appeared on the road surface", "road_crack"),
    ("Nice weather today", None),
]


def eval_text():
    ok, rows = 0, []
    for text, want in TEXT_CASES:
        got = nlp.classify_text(text)["category"]
        hit = got == want
        ok += hit
        rows.append((text[:58], want, got, hit))
    return round(ok / len(TEXT_CASES), 3), rows


# ---------------------------------------------------------------- 3. duplicate scoring
def eval_duplicates(tmp):
    """Pairs of the same pothole (shifted photo, few metres apart) vs different potholes."""
    from ai.duplicates import RADIUS_M, THRESHOLD, WEIGHTS, text_similarity

    rnd = random.Random(7)
    base = (13.0827, 80.2707)
    tp = fp = fn = tn = 0
    for i in range(25):
        a, b, c = (os.path.join(tmp, f"d{i}{x}.jpg") for x in "abc")
        synth.pothole(a, seed=200 + i)
        synth.pothole(b, seed=200 + i, shift=rnd.randint(4, 12))     # same pothole, another phone
        synth.pothole(c, seed=900 + i)                                # a different pothole
        dm = rnd.uniform(2, 15)
        lat2 = base[0] + dm / 111320
        same_txt = ("pothole near the bus stop", "big pothole on road near bus stop")
        diff_txt = ("pothole near the temple", "pothole near the bus stop")
        dist_same = haversine_m(base[0], base[1], lat2, base[1])
        dist_diff = rnd.uniform(RADIUS_M * 0.4, RADIUS_M * 0.95)   # a different pothole, still close by
        def score(d, txts, i1, i2):
            geo = max(0.0, 1 - d / RADIUS_M)
            return (WEIGHTS["geo"] * geo + WEIGHTS["text"] * text_similarity(*txts)
                    + WEIGHTS["image"] * image_similarity(i1, i2))
        s_same = score(dist_same, same_txt, a, b)
        s_diff = score(dist_diff, diff_txt, a, c)
        tp += s_same >= THRESHOLD
        fn += s_same < THRESHOLD
        fp += s_diff >= THRESHOLD
        tn += s_diff < THRESHOLD
    return prf(tp, fp, fn), (tp, fp, fn, tn)


# ---------------------------------------------------------------- 4. repair evidence
def eval_evidence(tmp, n=15):
    counts = {"consistent_pending_confirmation": 0, "needs_review": 0, "insufficient": 0}
    ctrl = dict(counts)
    for i in range(n):
        b, a, u, other = (os.path.join(tmp, f"e{i}{x}.jpg") for x in "bauo")
        synth.pothole(b, seed=300 + i)
        synth.pothole(a, seed=300 + i, repaired=True)      # genuinely repaired
        synth.pothole(u, seed=300 + i, shift=1)             # NOT repaired (same damage)
        counts[compare(b, a)["result"]] += 1
        ctrl[compare(b, u)["result"]] += 1
    return counts, ctrl, n


def main():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        rows, acc, conf = eval_detector(tmp)
        t_acc, t_rows = eval_text()
        (p, r, f), dcounts = eval_duplicates(tmp)
        ev, ctrl, n = eval_evidence(tmp)

    out.append("# Evaluation results (synthetic data only)\n")
    out.append("> These results use generated images and hand-written complaints. They test that the pipeline "
               "behaves as designed. They are **not** accuracy claims for real roads. Collect and label local "
               "Tamil Nadu photographs before reporting real performance.\n")
    out.append(f"Detector in use: `{detect.analyse_image(os.path.join(ROOT,'uploads','demo_a.jpg'))['detector']}`\n")
    out.append("## 1. Image detector (OpenCV heuristic baseline), 30 synthetic images per class, plus 30 clean-road images that should be 'other'\n")
    out.append("| Class | Precision | Recall | F1 |\n|---|---|---|---|")
    for c, p_, r_, f_ in rows:
        out.append(f"| {c} | {p_} | {r_} | {f_} |")
    out.append("Caution: the baseline's thresholds were tuned on these same synthetic images, so a perfect score "
               "here only shows the pipeline works. It says nothing about real photographs, where a trained model "
               "(YOLO on RDD2020 plus local images, see `scripts/train_yolo.py`) is needed.")
    out.append(f"\nOverall accuracy: **{acc}**. Confusion counts (rows = true, columns = predicted): `{conf}`\n")
    out.append("## 2. Complaint text classifier (keyword/lexicon, Tamil + English)\n")
    out.append(f"Accuracy on {len(TEXT_CASES)} hand-written cases: **{t_acc}**\n")
    out.append("| Complaint | Expected | Got | OK |\n|---|---|---|---|")
    for t, w, g, h in t_rows:
        out.append(f"| {t} | {w} | {g} | {'yes' if h else 'NO'} |")
    out.append("\n## 3. Duplicate detection (geo + text + image score)\n")
    tp, fp, fn, tn = dcounts
    out.append(f"25 same-pothole pairs vs 25 different-pothole pairs. TP={tp}, FP={fp}, FN={fn}, TN={tn}. "
               f"Precision {p}, recall {r}, F1 {f}.\n")
    out.append("Reading this honestly: the false positives are *different* potholes that sit 16-38 m apart with similar "
               "wording. In these synthetic photos every pothole looks alike, so the image signal cannot help; real "
               "photos should separate them better, but two damage spots on one stretch of road are genuinely "
               "ambiguous. That is why duplicates are only *suggested*: an officer confirms or rejects the link, "
               "and both citizen reports are always kept.\n")
    out.append("## 4. Repair-evidence comparison\n")
    out.append(f"{n} genuinely repaired pairs: `{ev}`\n")
    out.append(f"{n} control pairs (damage still present): `{ctrl}`\n")
    out.append("The system never certifies a repair. The best result is *consistent, pending officer confirmation*.\n")
    text = "\n".join(out)
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "EVALUATION_RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
