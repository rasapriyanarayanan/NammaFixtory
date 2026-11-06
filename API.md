# API

Base URL `http://localhost:5000`. Officer routes need the header `X-Officer-Key: demo123` (set `NAMMAFIXTORY_OFFICER_KEY`).

## Public
| Method | Path | Notes |
|---|---|---|
| GET | `/api/meta` | Categories, detector in use, tagline |
| POST | `/api/complaints` | multipart: `image` (optional), `description`, `category` (optional), `lat`, `lon`, `location_text`, `consent`, `name`, `contact`. Returns reference, category and source, department, AI photo result, duplicate suggestion, priority with reasons, history and `recurrence_detected` |
| GET | `/api/complaints/<ref>` | Status, updates, linked asset. Rounded coordinates, no contact details |
| POST | `/api/complaints/<ref>/feedback` | `{"resolved": true/false}` |
| GET | `/api/map` | Assets, complaints, hotspots (DBSCAN) |
| GET | `/api/sensitive-places` | Sample schools/hospitals |
| GET | `/uploads/<file>` | Images. Citizen photos are public only after the privacy check; held photos return 403 unless the officer key is sent (see *Photo privacy* below) |

## WhatsApp channel
| Method | Path | Notes |
|---|---|---|
| GET | `/webhook/whatsapp` | Meta Cloud API verification (`hub.mode=subscribe`, `hub.verify_token` = `WHATSAPP_VERIFY_TOKEN`, default `nammafixtory-verify`) |
| POST | `/webhook/whatsapp` | Incoming text / image / location messages in Meta's payload format. If `WHATSAPP_APP_SECRET` is set, `X-Hub-Signature-256` is checked. Replies are sent only when `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_ID` are set |
| POST | `/api/channels/simulate` | Offline simulator used by the WhatsApp page. Form fields: `sender`, `type` (`text` / `image` / `location`), `text`, `image`, `lat`, `lon`. Returns `{"replies": [...], "ref": ...}` |

Conversation: description and/or photo, plus a shared location, in any order; a reference number comes back in Tamil
or English. `status NFX-xxxxxx-xxxx` returns the current status. Half-finished reports expire after 30 minutes; phone
numbers are never stored, only a salted hash (`NAMMAFIXTORY_SALT`) while a report is incomplete.

## Photo privacy
Every real citizen photo (web or WhatsApp) goes through `ai/privacy.py` at intake. Result stored per photo:
`blurred`, `none_found`, `officer_cleared`, `officer_blurred`, `synthetic` (sample photos, no people) are **public**;
`detector_unavailable` or a missing value is **held**: visible to officers only. The submit response includes
`photo_privacy` and `photo_public`; public complaint views list only public photos plus an `images_held` count.

## Officer
| Method | Path | Notes |
|---|---|---|
| GET | `/api/dashboard` | Totals, by status/category/ward/month, recurring assets, flags |
| GET | `/api/queue?q=&category=&ward=&status=` | Prioritised complaint queue |
| GET | `/api/assets/<id>` | History timeline, risk, possible causes, repair evidence |
| POST | `/api/assets/<id>/repair` | multipart `officer`, `notes`, optional after `image` |
| POST | `/api/evidence/<id>/review` | `{"confirm": true/false}` |
| POST | `/api/complaints/<ref>/status` | `{"status": "under_review" \| "in_repair" \| "rejected" ...}` |
| POST | `/api/complaints/<ref>/duplicate` | `{"confirm": true/false}` |
| POST | `/api/complaints/<ref>/ai-review` | `{}` confirms, `{"category": "..."}` corrects |
| POST | `/api/images/<file>/privacy` | `{"action": "clear"}` after checking a held photo, or `{"action": "blur", "boxes": [[x,y,w,h], ...]}` to blur areas by hand. Audited |
| GET | `/api/audit` | Audit log |
| GET | `/api/export/maintenance-report` | CSV for engineers |

## Demo (sample data only)
`POST /api/demo/reset`, `POST /api/demo/step/1..5`, `GET /api/demo/location`.
