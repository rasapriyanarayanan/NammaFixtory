# Implementation status

Every feature is labelled **Implemented** (works in this prototype and is tested), **Experimental** (works but is a
baseline or heuristic) or **Planned** (not built).

| Module | Status | Notes |
|---|---|---|
| Citizen report form (photo, text, GPS or landmark, consent for contact) | Implemented | Contact stored only with consent; public views round coordinates |
| Reference number + status tracking + "is it fixed?" feedback | Implemented | |
| Tamil + English text: language ID, category, safety cues | Experimental | Transparent keyword lexicon; Transformer upgrade planned |
| Voice input | Experimental | Browser speech recognition only where the browser supports it (typing is always available) |
| Photo detection (pothole, crack, garbage) | Experimental | OpenCV baseline; YOLO path is wired but needs trained weights |
| Duplicate suggestion (geo + text + image) | Implemented | Suggest-only; both reports kept; officer confirms/rejects |
| Infrastructure assets + history timeline | Implemented | Core innovation |
| Recurrence detection + inspection flag | Implemented | Rule-based, shows reasons |
| "Possible causes to check" | Experimental | Hypotheses for engineers, never findings |
| Hotspots (DBSCAN) + map | Implemented | Built-in offline SVG map; tiles when online |
| Explainable priority score | Implemented | Weighted, every factor explained |
| Risk score | Experimental | Rule-based; not a forecast |
| Repair evidence comparison (before/after) | Experimental | OpenCV; never certifies; officer decision required |
| Officer dashboard, filters, CSV report, audit log | Implemented | Demo-key login |
| Guided hackathon demo | Implemented | Synthetic photos |
| Learned predictive maintenance (Random Forest / GBM) | Planned | Needs real repair history |
| WhatsApp reporting (conversation, Tamil/English replies, status lookup, Meta webhook format, signature check) | Experimental | Runs fully in the built-in simulator. **Not live:** sending replies and downloading photos need WhatsApp Business API credentials |
| SMS / IVR reporting | Planned | |
| Mobile app | Planned | |
| Government integration (CPGRAMS, GCC, UMANG, Swachhata) | Planned | Needs permission; not claimed |
| PostgreSQL + PostGIS | Planned | Prototype uses SQLite; schema maps directly |
| Face / number-plate blurring | Experimental | Haar-cascade detector + manual officer blur. Needs `scripts/fetch_cascades.sh` (internet). **Fails closed:** an unchecked photo is held for officers only. Misses small/side-on faces and many plate styles |
| Held-photo review by officers | Implemented | Clear or blur by hand; audited |
