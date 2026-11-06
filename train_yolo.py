#!/usr/bin/env python3
"""Train the civic damage detector (YOLO) on a road-damage dataset.

Needs packages that are NOT bundled with the prototype:  pip install ultralytics
Dataset: RDD2020 (https://github.com/sekilab/RoadDamageDetector) converted to YOLO format, ideally plus
a few hundred consented local photographs from Tamil Nadu for validation.

Usage:
    python3 scripts/train_yolo.py --data path/to/rdd.yaml --epochs 50 --imgsz 640
Result: models/civic_yolo.pt. Restart the server and ai/detect.py uses it automatically
(the detector name shown in the dashboard changes from 'opencv-heuristic-baseline' to 'yolo').

rdd.yaml example:
    path: /data/rdd2020_yolo
    train: images/train
    val: images/val
    names: {0: D00, 1: D10, 2: D20, 3: D40}      # D40 = pothole, D00/D10/D20 = cracks
Report precision, recall, F1 and mAP50 on a held-out LOCAL validation set before claiming accuracy.
"""
import argparse
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="YOLO dataset yaml")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--base", default="yolov8n.pt", help="pretrained starting weights")
    a = ap.parse_args()
    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("ultralytics is not installed. Run: pip install ultralytics")
    model = YOLO(a.base)
    model.train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, project=os.path.join(ROOT, "models", "runs"), name="civic")
    metrics = model.val()
    print("mAP50:", metrics.box.map50, "precision:", metrics.box.mp, "recall:", metrics.box.mr)
    best = os.path.join(ROOT, "models", "runs", "civic", "weights", "best.pt")
    if os.path.exists(best):
        shutil.copy(best, os.path.join(ROOT, "models", "civic_yolo.pt"))
        print("Saved models/civic_yolo.pt")


if __name__ == "__main__":
    main()
