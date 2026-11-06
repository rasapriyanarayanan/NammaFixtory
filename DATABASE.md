# Database (SQLite prototype; maps directly to PostgreSQL + PostGIS)

| Table | Purpose |
|---|---|
| users | Optional citizen identity. `contact` kept only when `consent = 1`. |
| wards | Sample ward centres (replace with real ward polygons). |
| sensitive_places | Schools/hospitals used by the priority score. |
| **infrastructure_assets** | A road section or drain with its own history (`asset_code`, `family`, location, ward). |
| complaints | Citizen reports. Links to `asset_id`, stores category + `category_source`, `duplicate_of` + `duplicate_state`, damage `episode`, `is_sample`. |
| complaint_images | Photos per complaint, with `privacy` (blurred / none_found / officer_cleared / officer_blurred / synthetic / detector_unavailable). Anything not in the public set is officer-only. |
| ai_analysis | Detector output: category, confidence, detector name, JSON detail, `human_review` (pending/confirmed/corrected). |
| duplicate_reports | Suggested links with geo/text/image sub-scores. |
| priority_records | Score, level and the JSON explanation. |
| repair_records | Repairs per asset with officer, notes, start/complete times. |
| repair_evidence | Before/after photos, AI result, `review_status` (awaiting_officer / officer_confirmed / officer_rejected). |
| channel_sessions | Half-finished WhatsApp reports keyed by a salted hash of the phone number (never the number), deleted on filing or after 30 minutes. |
| citizen_feedback | "Is it fixed?" answers. |
| notifications | Messages shown to the citizen. |
| audit_log | Who did what, when. |

Key relationships: one user to many complaints; one complaint to many photos; **one asset to many complaints and many
repairs**; one repair to many evidence records; many reports to one recurring problem through the asset.

PostGIS move: replace `lat, lon` with a `geography(Point)` column, use `ST_DWithin(…, 30)` for asset matching and
`ST_ClusterDBSCAN` for hotspots.
