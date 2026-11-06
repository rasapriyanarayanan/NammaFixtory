# NammaFixtory — Fix Today. Prevent Tomorrow.

AI-assisted civic infrastructure monitoring for Tamil Nadu. Citizens report potholes, drains, waterlogging and
garbage. The system doesn't just file complaints: it keeps a **history for each piece of road or drain**, so it can
show not only *what broke* but *what keeps breaking*.

**Why the name?** *Fixtory* = fix + history. *Namma* is Tamil for "ours". Every road and drain gets its own story, so a repair is never the end of the record.

> **Prototype status.** Everything here runs on **sample data** (synthetic photos, invented complaints in Chennai
> coordinates). There is no government integration, no live municipal data and no real-world accuracy claim.
> AI output is always a suggestion for an officer to review. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## Run it (2 minutes)

```bash
pip install -r requirements.txt     # flask, numpy, pillow, opencv, scikit-learn
./scripts/fetch_cascades.sh         # optional, needs internet: face + number-plate blur models
python3 app.py                      # or ./run.sh   ->  http://localhost:5000
```

| Page | What it does |
|---|---|
| **Report a problem** | Photo + description (Tamil or English, optional voice input) + location. Returns a reference number, the AI's reading of the photo, a priority score with reasons, and whether this looks like a duplicate or a repeat failure. |
| **Track a report** | Status, updates, "is it fixed?" feedback, and the history of that exact spot. |
| **WhatsApp** | A chat simulator for reporting by photo, text and shared location (Tamil or English replies, `status NFX-…` lookup). Same logic as the Meta Cloud API webhook at `/webhook/whatsapp`; live sending needs Business API credentials. |
| **Map** | Every report, hotspots (DBSCAN clusters) and red rings for places that failed again after repair. Works offline (built-in SVG map); shows street tiles when internet is available. |
| **Officer dashboard** | Key: `demo123` (set `NAMMAFIXTORY_OFFICER_KEY` to change). Complaint queue with filters, priority explanations, duplicate confirm/reject, type correction, repair recording with before/after evidence, risk scores, "possible causes to check", audit log, CSV maintenance report. |
| **Guided demo** | Runs the full hackathon story in five clicks (see [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)). |

Verify it: `python3 -m pytest tests` (56 tests) and `python3 scripts/evaluate.py` (writes `docs/EVALUATION_RESULTS.md`).

## What makes it different

Complaint registration, photo classification, mapping and duplicate detection already exist in civic apps. The
proposed difference here is **infrastructure-level history**:

1. Reports attach to an *asset* (a road section or drain), not just a ticket.
2. A new report after a completed repair starts a new *damage episode* and is flagged as a **recurrence**.
3. Locations with repeated failures are flagged for engineering inspection, with *hypotheses* (drainage, repair quality, heavy traffic) for engineers to test, never conclusions.
4. Priority and risk scores are **explainable**: every point has a stated reason.
5. Repair evidence is compared by software but **only an officer confirms**; the AI can never certify a repair.

(This is a product emphasis, not a novelty or patent claim. That would need a proper prior-art review.)

## How it works

```
Citizen (web) ──► intake pipeline ──► SQLite (assets, complaints, history)
 photo+text+GPS     1 language + NLP (Tamil/English)         │
                    2 image analysis (OpenCV baseline / YOLO)│
                    3 asset match (<=30 m, same family)      ▼
                    4 duplicate suggestion (geo+text+image)  Officer dashboard
                    5 history + recurrence + priority        map · queue · evidence · reports
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/API.md](docs/API.md) · [docs/DATABASE.md](docs/DATABASE.md)

## Project layout

```
app.py            Flask server and API          core.py       intake + repair pipeline
db.py             SQLite schema                 seed.py       sample data
synth.py          synthetic demo photos         util.py       categories, departments, geo helpers
ai/detect.py      photo detector (YOLO if weights exist, else OpenCV baseline)
ai/nlp.py         language ID, Tamil/English classification, safety cues, text similarity
ai/duplicates.py  geo + text + image duplicate scoring     ai/hotspots.py  DBSCAN hotspots
ai/recurrence.py  history, recurrence, risk score, possible causes
ai/priority.py    explainable priority      ai/evidence.py  before/after comparison
ai/privacy.py     face/plate blurring, fail-closed photo gate     channels/whatsapp.py  WhatsApp webhook + simulator
static/           the web app (index.html, minimap.js)     scripts/  evaluate.py, train_yolo.py, fetch_vendor.sh
tests/            56 tests                  docs/         architecture, API, evaluation, pilot proposal
```

## Honest limitations

* The photo detector is an **untrained OpenCV baseline** calibrated on synthetic images. Real accuracy needs YOLO trained on RDD2020 plus local photos (`scripts/train_yolo.py`, needs `ultralytics`).
* Text classification is a transparent Tamil/English keyword lexicon, not a Transformer model yet.
* Duplicate suggestions can fire for *different* potholes less than 40 m apart; that is why an officer confirms every link.
* Risk scores are **rule-based estimates**, not forecasts. A learned model needs real repair history.
* Officer sign-in is a demo key. A real deployment needs proper accounts, roles, HTTPS and a data-protection review.
* **Photo privacy fails closed.** Faces and number plates are blurred only when the Haar-cascade files are installed (`scripts/fetch_cascades.sh`). Without them, every real citizen photo is held: only officers can see it until they clear it or blur it by hand. Even with the detector, small, side-on faces and many Indian plate styles are missed.
* **WhatsApp is simulator-only until you add credentials.** The webhook, signature check and conversation logic are tested, but nothing has been sent through WhatsApp itself.
* Not yet built: SMS/IVR channels, mobile app, live government platform integration (CPGRAMS, GCC, UMANG). These need permission and are listed under *planned*.
