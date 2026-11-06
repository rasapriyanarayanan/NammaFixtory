# Evaluation results (synthetic data only)

> These results use generated images and hand-written complaints. They test that the pipeline behaves as designed. They are **not** accuracy claims for real roads. Collect and label local Tamil Nadu photographs before reporting real performance.

Detector in use: `opencv-heuristic-baseline`

## 1. Image detector (OpenCV heuristic baseline), 30 synthetic images per class, plus 30 clean-road images that should be 'other'

| Class | Precision | Recall | F1 |
|---|---|---|---|
| pothole | 1.0 | 1.0 | 1.0 |
| garbage | 1.0 | 1.0 | 1.0 |
| road_crack | 1.0 | 1.0 | 1.0 |
Caution: the baseline's thresholds were tuned on these same synthetic images, so a perfect score here only shows the pipeline works. It says nothing about real photographs, where a trained model (YOLO on RDD2020 plus local images, see `scripts/train_yolo.py`) is needed.

Overall accuracy: **1.0**. Confusion counts (rows = true, columns = predicted): `{'pothole': {'pothole': 30, 'garbage': 0, 'road_crack': 0, 'other': 0}, 'garbage': {'pothole': 0, 'garbage': 30, 'road_crack': 0, 'other': 0}, 'road_crack': {'pothole': 0, 'garbage': 0, 'road_crack': 30, 'other': 0}, 'other': {'pothole': 0, 'garbage': 0, 'road_crack': 0, 'other': 30}}`

## 2. Complaint text classifier (keyword/lexicon, Tamil + English)

Accuracy on 13 hand-written cases: **1.0**

| Complaint | Expected | Got | OK |
|---|---|---|---|
| There is a big pothole on the road near the bus stop | pothole | pothole | yes |
| kuzhi on the road, bikes are falling | pothole | pothole | yes |
| பேருந்து நிலையம் அருகே சாலையில் பெரிய பள்ளம் உள்ளது | pothole | pothole | yes |
| The drain is blocked and sewage is overflowing | blocked_drain | blocked_drain | yes |
| வடிகால் அடைப்பு, கழிவுநீர் தெருவில் ஓடுகிறது | blocked_drain | blocked_drain | yes |
| Water is stagnant on the street after rain, waterlogging | waterlogging | waterlogging | yes |
| மழை நீர் தேங்கி நிற்கிறது | waterlogging | waterlogging | yes |
| Garbage has piled up near the market for a week | garbage | garbage | yes |
| குப்பை குவிந்து கிடக்கிறது, துர்நாற்றம் | garbage | garbage | yes |
| Pipe leaking, drinking water is wasted on the road | water_leakage | water_leakage | yes |
| Streetlight not working, the lane is dark | streetlight | streetlight | yes |
| Long cracks have appeared on the road surface | road_crack | road_crack | yes |
| Nice weather today | None | None | yes |

## 3. Duplicate detection (geo + text + image score)

25 same-pothole pairs vs 25 different-pothole pairs. TP=25, FP=10, FN=0, TN=15. Precision 0.714, recall 1.0, F1 0.833.

Reading this honestly: the false positives are *different* potholes that sit 16-38 m apart with similar wording. In these synthetic photos every pothole looks alike, so the image signal cannot help; real photos should separate them better, but two damage spots on one stretch of road are genuinely ambiguous. That is why duplicates are only *suggested*: an officer confirms or rejects the link, and both citizen reports are always kept.

## 4. Repair-evidence comparison

15 genuinely repaired pairs: `{'consistent_pending_confirmation': 15, 'needs_review': 0, 'insufficient': 0}`

15 control pairs (damage still present): `{'consistent_pending_confirmation': 0, 'needs_review': 0, 'insufficient': 15}`

The system never certifies a repair. The best result is *consistent, pending officer confirmation*.

