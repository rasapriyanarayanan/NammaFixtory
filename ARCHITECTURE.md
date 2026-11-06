# Architecture

## Layers (as built)

| Layer | Implementation | Planned upgrade |
|---|---|---|
| 1 User access | Responsive web app (citizen pages + officer dashboard) in `static/` | SMS/IVR, mobile app (WhatsApp runs in the simulator and speaks Meta's webhook format; live sending needs Business API credentials) |
| 2 Data collection | Photo upload (JPG/PNG/WEBP, validated), text, browser GPS or landmark, optional voice | Video |
| 3 Processing | `ai/nlp.py` language ID + normalisation; `ai/detect.py` image quality checks | Speech-to-text service, EXIF GPS cross-check |
| 4 AI engine | detector, text classifier, duplicates, hotspots, priority, recurrence, evidence | YOLO weights, Sentence-Transformers, learned risk model |
| 5 Database | SQLite, 14 tables (see DATABASE.md) | PostgreSQL + PostGIS |
| 6 Output | Dashboard, map, CSV report, citizen tracking | Scheduled maintenance reports |

## Intake pipeline (`core.submit_complaint`)

1. **Language + NLP**: Tamil/English/Tanglish detection; category from a keyword lexicon; safety cues; location hint.
2. **Image analysis**: quality checks (blur, brightness, resolution) and a detector. If `models/civic_yolo.pt` exists and `ultralytics` is installed, YOLO is used; otherwise the OpenCV baseline.
3. **Category resolution** (strongest signal first): citizen's choice, then a confident image result (>= 0.55), then text, then "other". The source is stored so officers can see where the label came from.
4. **Asset matching**: the report attaches to the nearest asset of the same family within 30 m, otherwise a new asset is created. **The asset is the unit of history.**
5. **Duplicate suggestion**: among open reports of the same family within 40 m and 60 days, score = 0.50 geo + 0.30 text + 0.20 image; a score of 0.55 or more suggests a link. Suggest-only; both reports stay.
6. **History + priority**: rebuild the asset's episodes, recompute recurrence, compute the explainable priority.

## Recurrence logic (`ai/recurrence.py`)

An asset's reports and repairs are put on one timeline. A **damage episode** is a group of reports; a report arriving
after a *completed repair* starts a **new episode**. `recurrences = episodes - 1`.

An asset is **flagged for inspection** when it has 2 or more recurrences, or when damage returned within 90 days of a repair.
Every flag lists its reasons. "Possible causes" (sub-surface/structural cause, drainage, repair quality, monsoon
exposure) are *hypotheses* attached to evidence, for engineers to test.

## Risk score (rule-based, 0-100)

Repeated failures (20 each, max 3), fast recurrence (15 if within 60 days, 8 if within 120), open reports, monsoon
months for roads/drains, and a recent repair that has not yet proved itself. Not a forecast; replace with a trained
Random Forest / Gradient Boosting model only when enough real repair history exists.

## Priority score (0-100, `ai/priority.py`)

severity 30 + linked reports 20 + age 15 + recurrence 20 + nearby school/hospital 10 + safety cues 5. Levels:
High >= 60, Medium >= 35, otherwise Low. Each factor carries a plain-language reason shown on the dashboard.
A recommendation only; official emergency procedures take precedence.

## Repair evidence (`ai/evidence.py`)

Compares the original photo with the after-repair photo (pixel change in the damaged region, ORB keypoint scene match,
layout correlation, EXIF presence). Outcomes: *consistent, pending officer confirmation*, *needs review*, *insufficient*.
There is deliberately no "repair verified" outcome. An officer's confirmation is recorded in the audit log.

## Privacy and safety controls in the code

* Contact details are stored only if the citizen ticks consent, and are never returned by public endpoints.
* Public views round coordinates; exact coordinates are officer-only.
* Officer endpoints require `X-Officer-Key`; officer actions are written to an audit log.
* Uploads: extension allow-list, image verification on save, 10 MB limit, random file names.
* AI never auto-rejects a report: duplicates and categories are suggestions.
* Photo privacy (`ai/privacy.py`): faces and number plates are blurred with OpenCV Haar cascades when the model files are present (`scripts/fetch_cascades.sh`). If a photo cannot be checked it is **held**: `/uploads` returns 403 to the public and only officers can see it until they clear it or blur it by hand. Detection is a risk reducer, not a guarantee: Haar cascades miss small, side-on and many Indian-style plates.
* WhatsApp (`channels/whatsapp.py`): phone numbers are never stored; reports run through the same intake pipeline as the web form.

## Production gaps (not in the prototype)

Real accounts and roles, HTTPS, rate limiting and CAPTCHA, a stronger face/plate detector, retention and deletion
policy, a data-protection review under Indian law, backups, monitoring, PostgreSQL/PostGIS.
