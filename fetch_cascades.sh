#!/usr/bin/env bash
# Download OpenCV Haar cascades used by ai/privacy.py (face + number-plate blurring).
# Needs internet. Files go to ./models/ . Run once: ./scripts/fetch_cascades.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p models
BASE=https://raw.githubusercontent.com/opencv/opencv/4.x/data/haarcascades
for f in haarcascade_frontalface_default.xml haarcascade_profileface.xml haarcascade_russian_plate_number.xml; do
  echo "fetching $f"; curl -fsSL "$BASE/$f" -o "models/$f"
done
echo "done. Restart the server; /api/meta will report privacy detectors as available."
