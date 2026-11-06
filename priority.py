"""Explainable maintenance priority (weighted score, 0-100).

This is a RECOMMENDATION for officers. It never overrides official emergency or
public-safety procedures.
"""
from ai.nlp import safety_cues
from util import haversine_m, parse

WEIGHTS = {
    "severity": 30,
    "reports": 20,
    "age": 15,
    "recurrence": 20,
    "sensitive_place": 10,
    "safety": 5,
}

BASE_SEVERITY = {
    "pothole": 0.70, "road_crack": 0.40, "road_damage": 0.60, "blocked_drain": 0.60,
    "waterlogging": 0.70, "water_leakage": 0.55, "garbage": 0.40, "streetlight": 0.45, "other": 0.30,
}


def compute_priority(conn, complaint, n_reports, recurrences, now_dt, ai_conf=None):
    factors = []

    sev = BASE_SEVERITY.get(complaint["category"], 0.3)
    factors.append(("severity", sev, f"{complaint['category'].replace('_', ' ')} base severity {sev:.0%}"))

    rep = min(1.0, (n_reports - 1) / 4) if n_reports > 1 else 0.0
    factors.append(("reports", rep, f"{n_reports} report(s) linked to this issue"))

    age_days = max(0, (now_dt - parse(complaint["created_at"])).days)
    age = min(1.0, age_days / 30)
    factors.append(("age", age, f"open for {age_days} day(s)"))

    rec = min(1.0, recurrences / 3)
    factors.append(("recurrence", rec,
                    f"{recurrences} earlier failure(s) at this location after repair" if recurrences
                    else "no repeated failure recorded"))

    near, near_d = None, 1e9
    for p in conn.execute("SELECT * FROM sensitive_places").fetchall():
        d = haversine_m(complaint["lat"], complaint["lon"], p["lat"], p["lon"])
        if d < near_d:
            near, near_d = p, d
    sens = 0.0
    sens_note = "no sensitive public place within 200 m"
    if near is not None and near_d <= 200:
        sens = 1.0 if near_d <= 100 else 0.5
        sens_note = f"{near['kind']} '{near['name']}' about {int(near_d)} m away"
    factors.append(("sensitive_place", sens, sens_note))

    cues = safety_cues(complaint.get("description", ""))
    saf = min(1.0, len(cues) / 2)
    factors.append(("safety", saf, ("safety cues in text: " + ", ".join(cues)) if cues else "no safety cues in text"))

    total = 0.0
    detail = []
    for name, val, why in factors:
        pts = WEIGHTS[name] * val
        total += pts
        detail.append({"factor": name, "value": round(val, 2), "weight": WEIGHTS[name],
                       "points": round(pts, 1), "why": why})
    level = "High" if total >= 60 else "Medium" if total >= 35 else "Low"
    return {"score": round(total, 1), "level": level, "factors": detail,
            "disclaimer": "Recommendation only; official emergency procedures take precedence."}
