"""Infrastructure history, recurrence detection and rule-based risk score.

Concept: complaints are grouped by infrastructure ASSET. A *damage episode* is a
cluster of reports; a NEW episode starts when a report arrives after a repair was
completed on that asset. Recurrences = episodes - 1.

Risk is a transparent rule-based estimate (not a trained forecast). Possible causes
are hypotheses to investigate, never conclusions.
"""
from db import rows
from util import haversine_m, parse

MONSOON_MONTHS = {6, 7, 8, 9, 10, 11, 12}  # SW monsoon + NE monsoon relevance for Tamil Nadu


def asset_events(conn, asset_id):
    comps = rows(conn, "SELECT * FROM complaints WHERE asset_id=? ORDER BY created_at", (asset_id,))
    reps = rows(conn, "SELECT * FROM repair_records WHERE asset_id=? ORDER BY COALESCE(completed_at, started_at)",
                (asset_id,))
    return comps, reps


def build_history(conn, asset_id, now_dt):
    comps, reps = asset_events(conn, asset_id)
    done = [r for r in reps if r["status"] == "completed" and r["completed_at"]]
    episodes = []  # each: {start, reports:[], repair_after:None}
    for c in comps:
        if c["duplicate_of"] and c["duplicate_state"] != "rejected":
            if episodes:
                episodes[-1]["reports"].append(c)
            continue
        cdt = parse(c["created_at"])
        if not episodes:
            episodes.append({"start": cdt, "reports": [c]})
            continue
        last_start = episodes[-1]["start"]
        # a repair always follows the report it fixes, so a tie (same second) counts as after it
        repair_between = [r for r in done if last_start <= parse(r["completed_at"]) <= cdt]
        if repair_between:
            episodes.append({"start": cdt, "reports": [c], "after_repair": repair_between[-1]})
        else:
            episodes[-1]["reports"].append(c)

    intervals = []
    for e in episodes[1:]:
        intervals.append((e["start"] - parse(e["after_repair"]["completed_at"])).days)

    recurrences = max(0, len(episodes) - 1)
    min_gap = min(intervals) if intervals else None

    flag = False
    reasons = []
    if recurrences >= 2:
        flag = True
        reasons.append(f"{recurrences} repeated failures after repair")
    if recurrences >= 1 and min_gap is not None and min_gap <= 90:
        flag = True
        reasons.append(f"damage returned within {min_gap} days of a repair")

    # timeline
    timeline = []
    for c in comps:
        dup = bool(c["duplicate_of"])
        timeline.append({"ts": c["created_at"], "type": "duplicate_report" if dup else "report",
                         "text": f"{c['ref']} - {c['category'].replace('_', ' ')} reported"
                                 + (" (linked duplicate)" if dup else ""),
                         "ref": c["ref"]})
    for r in reps:
        if r["started_at"]:
            timeline.append({"ts": r["started_at"], "type": "repair_started", "text": "Repair started"})
        if r["completed_at"]:
            timeline.append({"ts": r["completed_at"], "type": "repair_completed",
                             "text": "Repair marked complete" + (f" ({r['notes']})" if r["notes"] else "")})
    timeline.sort(key=lambda x: x["ts"])
    # mark recurrence points
    for e in episodes[1:]:
        for t in timeline:
            if t["type"] == "report" and t["ts"] == e["reports"][0]["created_at"]:
                t["type"] = "recurrence"
                t["text"] = t["text"] + " - RECURRENCE after repair"

    return {
        "reports_total": len(comps),
        "episodes": len(episodes),
        "recurrences": recurrences,
        "repairs_completed": len(done),
        "min_days_to_recurrence": min_gap,
        "mean_days_to_recurrence": round(sum(intervals) / len(intervals), 1) if intervals else None,
        "inspection_flag": flag,
        "flag_reasons": reasons,
        "timeline": timeline,
        "_episodes": episodes,
        "_done_repairs": done,
    }


def possible_causes(conn, asset, history):
    """Hypotheses only. Each carries the evidence that triggered it."""
    out = []
    if history["recurrences"] == 0:
        return out
    near = rows(conn, "SELECT * FROM complaints WHERE category IN ('blocked_drain','waterlogging','water_leakage')")
    near = [c for c in near if haversine_m(asset["lat"], asset["lon"], c["lat"], c["lon"]) <= 100]
    if near:
        out.append({"hypothesis": "Drainage or water leakage nearby may be weakening the surface",
                    "evidence": f"{len(near)} drainage/water report(s) within 100 m"})
    gap = history["min_days_to_recurrence"]
    if gap is not None and gap <= 60:
        out.append({"hypothesis": "Repair quality or material may need inspection",
                    "evidence": f"damage returned {gap} days after repair"})
    if history["recurrences"] >= 2:
        out.append({"hypothesis": "Sub-surface or structural cause may exist; engineering inspection advised",
                    "evidence": f"{history['recurrences']} repeated failures at the same section"})
    return out


def risk_score(conn, asset, history, now_dt):
    pts, why = 0, []
    rec = history["recurrences"]
    if rec:
        p = min(rec, 3) * 20
        pts += p
        why.append((p, f"{rec} repeated failure(s)"))
    gap = history["min_days_to_recurrence"]
    if gap is not None:
        p = 15 if gap <= 60 else 8 if gap <= 120 else 0
        if p:
            pts += p
            why.append((p, f"fastest recurrence {gap} days after repair"))
    open_reports = sum(1 for c in conn.execute(
        "SELECT status FROM complaints WHERE asset_id=? AND status IN ('open','under_review','in_repair')",
        (asset["asset_id"],)).fetchall())
    if open_reports:
        p = min(open_reports, 5) * 3
        pts += p
        why.append((p, f"{open_reports} open report(s)"))
    if now_dt.month in MONSOON_MONTHS and asset["family"] in ("road", "drainage"):
        pts += 10
        why.append((10, "monsoon-season exposure"))
    done = history["_done_repairs"]
    if done:
        days = (now_dt - parse(done[-1]["completed_at"])).days
        if days <= 45 and history["recurrences"] == 0:
            pts += 0  # recently repaired, no recurrence: no extra risk
    pts = min(100, pts)
    level = "High" if pts >= 60 else "Medium" if pts >= 35 else "Low"
    return {"score": pts, "level": level,
            "factors": [{"points": p, "why": w} for p, w in why],
            "disclaimer": "Rule-based risk estimate, not a guaranteed forecast. Train an ML model only after "
                          "enough reliable pilot data exists."}


def asset_summary(conn, asset_id, now_dt, full=False):
    asset = rows(conn, "SELECT a.*, w.name AS ward FROM infrastructure_assets a "
                       "LEFT JOIN wards w ON w.ward_id=a.ward_id WHERE asset_id=?", (asset_id,))[0]
    h = build_history(conn, asset_id, now_dt)
    risk = risk_score(conn, asset, h, now_dt)
    causes = possible_causes(conn, asset, h)
    out = {**asset,
           "reports_total": h["reports_total"], "episodes": h["episodes"], "recurrences": h["recurrences"],
           "repairs_completed": h["repairs_completed"], "inspection_flag": h["inspection_flag"],
           "flag_reasons": h["flag_reasons"], "min_days_to_recurrence": h["min_days_to_recurrence"],
           "mean_days_to_recurrence": h["mean_days_to_recurrence"],
           "risk": risk, "possible_causes": causes}
    if full:
        out["timeline"] = h["timeline"]
    return out
