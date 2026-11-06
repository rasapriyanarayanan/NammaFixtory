"""NammaFixtory web server (Flask + SQLite).

Run:  python3 app.py        then open http://localhost:5000
Officer actions need the header X-Officer-Key (env NAMMAFIXTORY_OFFICER_KEY, default 'demo123').
"""
import json
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory
from PIL import Image

import core
import db
import seed
import synth
from ai import privacy
from ai.hotspots import hotspots
from ai.recurrence import asset_summary, build_history
from channels.whatsapp import bp as whatsapp_bp
from util import CATEGORY_LABEL, FAMILY, iso, now, parse

BASE = os.path.dirname(os.path.abspath(__file__))
OFFICER_KEY = os.environ.get("NAMMAFIXTORY_OFFICER_KEY", "demo123")
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}

app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.register_blueprint(whatsapp_bp)
db.init_db()
_c = db.connect()
if _c.execute("SELECT COUNT(*) FROM wards").fetchone()[0] == 0:
    seed.seed_sample(_c)
_c.close()


def officer_only():
    return request.headers.get("X-Officer-Key") == OFFICER_KEY


def deny():
    return jsonify({"error": "officer access required (X-Officer-Key)"}), 401


def save_upload(file_storage, prefix="u"):
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Only JPG, PNG or WEBP images are accepted")
    path = os.path.join(core.UPLOADS, f"{prefix}_{uuid.uuid4().hex[:12]}{ext}")
    file_storage.save(path)
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        os.remove(path)
        raise ValueError("That file is not a valid image")
    return path


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/uploads/<path:name>")
def uploads(name):
    """Serve a stored image. Citizen photos are public only after the privacy check (faces and number plates
    blurred, or an officer cleared them). Anything unchecked is officer-only: fail closed."""
    if not officer_only():
        conn = db.connect()
        try:
            r = db.row(conn, "SELECT privacy FROM complaint_images WHERE path=?",
                       (os.path.join(core.UPLOADS, os.path.basename(name)),))
        finally:
            conn.close()
        if r is not None and r["privacy"] not in core.PUBLIC_PRIVACY:
            return jsonify({"error": "This photo is held for officer review (privacy check pending)."}), 403
    return send_from_directory(core.UPLOADS, name)


@app.post("/api/images/<name>/privacy")
def image_privacy(name):
    """Officer resolves a held photo: mark it clear, or blur boxes [[x,y,w,h], ...] by hand."""
    if not officer_only():
        return deny()
    data = request.get_json(silent=True) or {}
    path = os.path.join(core.UPLOADS, os.path.basename(name))
    conn = db.connect()
    try:
        if not db.row(conn, "SELECT 1 FROM complaint_images WHERE path=?", (path,)):
            return jsonify({"error": "not found"}), 404
        if data.get("action") == "blur":
            try:
                boxes = [[int(v) for v in b[:4]] for b in (data.get("boxes") or [])][:50]
            except (TypeError, ValueError):
                return jsonify({"error": "boxes must be [[x,y,w,h], ...]"}), 400
            if not boxes:
                return jsonify({"error": "provide at least one box to blur"}), 400
            n = privacy.blur_regions(path, boxes)
            state = "officer_blurred"
        elif data.get("action") == "clear":
            n, state = 0, "officer_cleared"
        else:
            return jsonify({"error": "action must be 'clear' or 'blur'"}), 400
        conn.execute("UPDATE complaint_images SET privacy=? WHERE path=?", (state, path))
        db.audit(conn, data.get("officer", "Officer"), f"photo_{state}", f"image:{os.path.basename(path)}", iso(now()))
        conn.commit()
        return jsonify({"ok": True, "privacy": state, "boxes_blurred": n})
    finally:
        conn.close()


@app.get("/api/meta")
def meta():
    return jsonify({
        "categories": [{"key": k, "label": v, "family": FAMILY[k]} for k, v in CATEGORY_LABEL.items()],
        "name": "NammaFixtory", "tagline": "Fix Today. Prevent Tomorrow.",
        "detector": "yolo" if os.path.exists(os.path.join(BASE, "models", "civic_yolo.pt")) else
                    "opencv-heuristic-baseline",
        "sample_data": True,
        "privacy_detectors": privacy.detectors_available(),
        "whatsapp": {"simulator": True, "live": bool(os.environ.get("WHATSAPP_TOKEN"))},
    })


# ------------------------------------------------------------------ citizen
@app.post("/api/complaints")
def create_complaint():
    f = request.form
    try:
        lat, lon = float(f.get("lat", "")), float(f.get("lon", ""))
    except ValueError:
        return jsonify({"error": "A valid location (lat/lon) is required"}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Location is out of range"}), 400
    desc = (f.get("description") or "").strip()[:1000]
    path = None
    if "image" in request.files and request.files["image"].filename:
        try:
            path = save_upload(request.files["image"], "r")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    if not desc and not path:
        return jsonify({"error": "Add a photo or a description"}), 400
    conn = db.connect()
    try:
        out = core.submit_complaint(
            conn, description=desc, lat=lat, lon=lon, category=f.get("category") or None, image_path=path,
            name=(f.get("name") or None), contact=(f.get("contact") or None),
            consent=f.get("consent") in ("1", "true", "on"), location_text=(f.get("location_text") or ""),
            channel=f.get("channel", "web"))
        return jsonify(out), 201
    finally:
        conn.close()


@app.get("/api/complaints/<ref>")
def get_complaint(ref):
    conn = db.connect()
    try:
        c = core.public_complaint(conn, ref, officer=officer_only())
        if not c:
            return jsonify({"error": "No complaint with that reference"}), 404
        if c["asset_id"]:
            c["asset"] = asset_summary(conn, c["asset_id"], now())
        return jsonify(c)
    finally:
        conn.close()


@app.post("/api/complaints/<ref>/feedback")
def feedback(ref):
    data = request.get_json(silent=True) or {}
    conn = db.connect()
    try:
        c = db.row(conn, "SELECT complaint_id FROM complaints WHERE ref=?", (ref,))
        if not c:
            return jsonify({"error": "not found"}), 404
        conn.execute("INSERT INTO citizen_feedback(complaint_id,resolved,comment,created_at) VALUES (?,?,?,?)",
                     (c["complaint_id"], 1 if data.get("resolved") else 0, (data.get("comment") or "")[:500],
                      iso(now())))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.get("/api/map")
def map_points():
    """Public map data: no contact info, no citizen identity, coordinates rounded."""
    conn = db.connect()
    try:
        cs = db.rows(conn, "SELECT ref,category,status,lat,lon,created_at,asset_id,duplicate_of FROM complaints")
        for c in cs:
            c["lat"], c["lon"] = round(c["lat"], 4), round(c["lon"], 4)
            c["label"] = CATEGORY_LABEL.get(c["category"], c["category"])
        assets = []
        for a in db.rows(conn, "SELECT asset_id FROM infrastructure_assets"):
            s = asset_summary(conn, a["asset_id"], now())
            assets.append({k: s[k] for k in ("asset_id", "asset_code", "family", "lat", "lon", "ward",
                                             "recurrences", "inspection_flag")} | {"risk_level": s["risk"]["level"]})
        pts = [{"lat": c["lat"], "lon": c["lon"]} for c in cs if c["status"] != "resolved"]
        return jsonify({"complaints": cs, "assets": assets, "hotspots": hotspots(pts)})
    finally:
        conn.close()


@app.get("/api/sensitive-places")
def places():
    conn = db.connect()
    try:
        return jsonify(db.rows(conn, "SELECT name,kind,lat,lon FROM sensitive_places"))
    finally:
        conn.close()


# ------------------------------------------------------------------ officer
@app.get("/api/dashboard")
def dashboard():
    if not officer_only():
        return deny()
    conn = db.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        by_status = {r["status"]: r["n"] for r in db.rows(conn, "SELECT status, COUNT(*) n FROM complaints GROUP BY status")}
        by_cat = db.rows(conn, "SELECT category, COUNT(*) n FROM complaints GROUP BY category ORDER BY n DESC")
        for r in by_cat:
            r["label"] = CATEGORY_LABEL.get(r["category"], r["category"])
        by_ward = db.rows(conn, """SELECT COALESCE(w.name,'Unassigned') ward, COUNT(*) n FROM complaints c
                                   LEFT JOIN infrastructure_assets a ON a.asset_id=c.asset_id
                                   LEFT JOIN wards w ON w.ward_id=a.ward_id GROUP BY ward ORDER BY n DESC""")
        monthly = db.rows(conn, "SELECT substr(created_at,1,7) month, COUNT(*) n FROM complaints GROUP BY month ORDER BY month")
        dups = conn.execute("SELECT COUNT(*) FROM complaints WHERE duplicate_of IS NOT NULL").fetchone()[0]
        assets = [asset_summary(conn, a["asset_id"], now()) for a in db.rows(conn, "SELECT asset_id FROM infrastructure_assets")]
        recurring = sorted([a for a in assets if a["recurrences"] > 0], key=lambda a: (-a["recurrences"], -a["risk"]["score"]))
        evidence_pending = conn.execute("SELECT COUNT(*) FROM repair_evidence WHERE review_status='awaiting_officer'").fetchone()[0]
        ev_flag = conn.execute("SELECT COUNT(*) FROM repair_evidence WHERE ai_result!='consistent_pending_confirmation'").fetchone()[0]
        ev_total = conn.execute("SELECT COUNT(*) FROM repair_evidence").fetchone()[0]
        return jsonify({
            "total": total, "by_status": by_status, "by_category": by_cat, "by_ward": by_ward, "monthly": monthly,
            "duplicates": dups, "recurring_assets": recurring, "evidence_pending": evidence_pending,
            "evidence_needing_review_pct": round(100 * ev_flag / ev_total, 1) if ev_total else None,
            "high_risk_assets": sum(1 for a in assets if a["risk"]["level"] == "High"),
            "inspection_flags": sum(1 for a in assets if a["inspection_flag"]),
        })
    finally:
        conn.close()


@app.get("/api/queue")
def queue():
    if not officer_only():
        return deny()
    cat, ward, status = request.args.get("category"), request.args.get("ward"), request.args.get("status")
    q = request.args.get("q", "").strip().lower()
    conn = db.connect()
    try:
        sql = """SELECT c.ref,c.category,c.status,c.created_at,c.description,c.duplicate_of,c.duplicate_state,
                        c.asset_id,c.episode,c.lat,c.lon,w.name AS ward,
                        (SELECT score FROM priority_records p WHERE p.complaint_id=c.complaint_id
                         ORDER BY priority_id DESC LIMIT 1) AS priority_score,
                        (SELECT level FROM priority_records p WHERE p.complaint_id=c.complaint_id
                         ORDER BY priority_id DESC LIMIT 1) AS priority_level
                 FROM complaints c LEFT JOIN infrastructure_assets a ON a.asset_id=c.asset_id
                 LEFT JOIN wards w ON w.ward_id=a.ward_id WHERE 1=1"""
        args = []
        if cat:
            sql += " AND c.category=?"
            args.append(cat)
        if ward:
            sql += " AND w.name=?"
            args.append(ward)
        if status:
            sql += " AND c.status=?"
            args.append(status)
        sql += " ORDER BY priority_score DESC, c.created_at DESC"
        out = db.rows(conn, sql, args)
        if q:
            out = [r for r in out if q in (r["description"] or "").lower() or q in r["ref"].lower()]
        for r in out:
            r["label"] = CATEGORY_LABEL.get(r["category"], r["category"])
        return jsonify(out)
    finally:
        conn.close()


@app.get("/api/assets/<int:aid>")
def asset(aid):
    conn = db.connect()
    try:
        if not db.row(conn, "SELECT 1 FROM infrastructure_assets WHERE asset_id=?", (aid,)):
            return jsonify({"error": "not found"}), 404
        s = asset_summary(conn, aid, now(), full=True)
        s["evidence"] = []
        for e in db.rows(conn, """SELECT e.* FROM repair_evidence e JOIN repair_records r ON r.repair_id=e.repair_id
                                  WHERE r.asset_id=? ORDER BY e.evidence_id""", (aid,)):
            e["ai_detail"] = json.loads(e["ai_detail"] or "{}")
            e["before_image"] = os.path.basename(e["before_image"]) if e["before_image"] else None
            e["after_image"] = os.path.basename(e["after_image"]) if e["after_image"] else None
            s["evidence"].append(e)
        return jsonify(s)
    finally:
        conn.close()


@app.post("/api/assets/<int:aid>/repair")
def repair(aid):
    if not officer_only():
        return deny()
    path = None
    if "image" in request.files and request.files["image"].filename:
        try:
            path = save_upload(request.files["image"], "a")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        try:  # best effort: after-repair photos can also catch bystanders and vehicles
            privacy.protect_image(path)
        except Exception:
            pass
    conn = db.connect()
    try:
        if not db.row(conn, "SELECT 1 FROM infrastructure_assets WHERE asset_id=?", (aid,)):
            return jsonify({"error": "not found"}), 404
        out = core.complete_repair(conn, aid, officer=request.form.get("officer", "Officer"),
                                   notes=(request.form.get("notes") or "")[:300], after_image=path)
        return jsonify(out)
    finally:
        conn.close()


@app.post("/api/evidence/<int:eid>/review")
def review_evidence(eid):
    if not officer_only():
        return deny()
    data = request.get_json(silent=True) or {}
    state = "officer_confirmed" if data.get("confirm") else "officer_rejected"
    conn = db.connect()
    try:
        conn.execute("UPDATE repair_evidence SET review_status=?, review_notes=? WHERE evidence_id=?",
                     (state, (data.get("notes") or "")[:300], eid))
        db.audit(conn, data.get("officer", "Officer"), f"evidence_{state}", f"evidence:{eid}", iso(now()))
        conn.commit()
        return jsonify({"ok": True, "review_status": state})
    finally:
        conn.close()


@app.post("/api/complaints/<ref>/status")
def set_status(ref):
    if not officer_only():
        return deny()
    data = request.get_json(silent=True) or {}
    new = data.get("status")
    if new not in ("open", "under_review", "in_repair", "rejected"):
        return jsonify({"error": "invalid status"}), 400
    conn = db.connect()
    try:
        conn.execute("UPDATE complaints SET status=?, updated_at=? WHERE ref=?", (new, iso(now()), ref))
        db.audit(conn, data.get("officer", "Officer"), f"status:{new}", ref, iso(now()))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.post("/api/complaints/<ref>/duplicate")
def duplicate_decision(ref):
    if not officer_only():
        return deny()
    data = request.get_json(silent=True) or {}
    state = "confirmed" if data.get("confirm") else "rejected"
    conn = db.connect()
    try:
        if state == "rejected":
            conn.execute("UPDATE complaints SET duplicate_state='rejected', duplicate_of=NULL WHERE ref=?", (ref,))
        else:
            conn.execute("UPDATE complaints SET duplicate_state='confirmed' WHERE ref=?", (ref,))
        conn.execute("UPDATE duplicate_reports SET state=? WHERE complaint_id=(SELECT complaint_id FROM complaints WHERE ref=?)",
                     (state, ref))
        db.audit(conn, data.get("officer", "Officer"), f"duplicate_{state}", ref, iso(now()))
        conn.commit()
        return jsonify({"ok": True, "duplicate_state": state})
    finally:
        conn.close()


@app.post("/api/complaints/<ref>/ai-review")
def ai_review(ref):
    """Officer corrects or confirms the AI category (human-in-the-loop)."""
    if not officer_only():
        return deny()
    data = request.get_json(silent=True) or {}
    conn = db.connect()
    try:
        c = db.row(conn, "SELECT complaint_id FROM complaints WHERE ref=?", (ref,))
        if not c:
            return jsonify({"error": "not found"}), 404
        if data.get("category") in CATEGORY_LABEL:
            conn.execute("UPDATE complaints SET category=?, category_source='officer' WHERE ref=?", (data["category"], ref))
            conn.execute("UPDATE ai_analysis SET human_review='corrected' WHERE complaint_id=?", (c["complaint_id"],))
        else:
            conn.execute("UPDATE ai_analysis SET human_review='confirmed' WHERE complaint_id=?", (c["complaint_id"],))
        db.audit(conn, data.get("officer", "Officer"), "ai_review", ref, iso(now()))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.get("/api/audit")
def audit_log():
    if not officer_only():
        return deny()
    conn = db.connect()
    try:
        return jsonify(db.rows(conn, "SELECT * FROM audit_log ORDER BY log_id DESC LIMIT 100"))
    finally:
        conn.close()


@app.get("/api/export/maintenance-report")
def maintenance_report():
    if not officer_only():
        return deny()
    conn = db.connect()
    try:
        assets = [asset_summary(conn, a["asset_id"], now()) for a in db.rows(conn, "SELECT asset_id FROM infrastructure_assets")]
        assets = [a for a in assets if a["recurrences"] > 0 or a["risk"]["level"] != "Low"]
        assets.sort(key=lambda a: -a["risk"]["score"])
        lines = ["asset_code,family,ward,reports,episodes,recurrences,repairs,min_days_to_recurrence,"
                 "inspection_flag,risk_score,risk_level,possible_causes"]
        for a in assets:
            causes = " | ".join(c["hypothesis"] for c in a["possible_causes"]).replace(",", ";")
            lines.append(f"{a['asset_code']},{a['family']},{a['ward']},{a['reports_total']},{a['episodes']},"
                         f"{a['recurrences']},{a['repairs_completed']},{a['min_days_to_recurrence']},"
                         f"{a['inspection_flag']},{a['risk']['score']},{a['risk']['level']},{causes}")
        return app.response_class("\n".join(lines), mimetype="text/csv",
                                  headers={"Content-Disposition": "attachment; filename=maintenance_report.csv"})
    finally:
        conn.close()


# ------------------------------------------------------------------ demo
DEMO_LAT, DEMO_LON = 13.0827, 80.2707


@app.post("/api/demo/reset")
def demo_reset():
    seed.full_reset(True)
    return jsonify({"ok": True})


@app.post("/api/demo/step/<int:n>")
def demo_step(n):
    """Guided hackathon scenario with SYNTHETIC photos and a simulated timeline."""
    conn = db.connect()
    d = os.path.join(core.UPLOADS)
    try:
        if n == 1:
            p = os.path.join(d, "demo_a.jpg"); synth.pothole(p, seed=101)
            out = core.submit_complaint(conn, description="Big pothole near the bus stop, very dangerous",
                                        lat=DEMO_LAT, lon=DEMO_LON, image_path=p, created_at=iso(now(-100)),
                                        name="Citizen A", is_sample=True)
            return jsonify({"step": 1, "title": "Citizen A reports a pothole", "result": out})
        if n == 2:
            p = os.path.join(d, "demo_b.jpg"); synth.pothole(p, seed=101, shift=8)
            out = core.submit_complaint(conn, description="pothole on the road near bus stop",
                                        lat=DEMO_LAT + 0.00004, lon=DEMO_LON + 0.00003, image_path=p,
                                        created_at=iso(now(-100) ), name="Citizen B", is_sample=True)
            return jsonify({"step": 2, "title": "Citizen B reports the same pothole", "result": out})
        a = db.row(conn, "SELECT asset_id FROM infrastructure_assets WHERE family='road' ORDER BY "
                         "((lat-?)*(lat-?)+(lon-?)*(lon-?)) LIMIT 1", (DEMO_LAT, DEMO_LAT, DEMO_LON, DEMO_LON))
        if not a:
            return jsonify({"error": "Run steps 1-2 first"}), 400
        if n == 3:
            p = os.path.join(d, "demo_after.jpg"); synth.pothole(p, seed=101, repaired=True)
            out = core.complete_repair(conn, a["asset_id"], officer="Sample Officer", notes="cold-mix patch",
                                       after_image=p, completed_at=iso(now(-90)))
            return jsonify({"step": 3, "title": "Officer records a repair with an after-photo", "result": out})
        if n == 4:
            ev = db.row(conn, "SELECT e.evidence_id FROM repair_evidence e JOIN repair_records r ON r.repair_id=e.repair_id "
                              "WHERE r.asset_id=? ORDER BY e.evidence_id DESC LIMIT 1", (a["asset_id"],))
            if ev:
                conn.execute("UPDATE repair_evidence SET review_status='officer_confirmed', review_notes='Verified on site' "
                             "WHERE evidence_id=?", (ev["evidence_id"],))
                conn.commit()
            return jsonify({"step": 4, "title": "Officer reviews the AI evidence check and confirms",
                            "result": {"asset": asset_summary(conn, a["asset_id"], now(), full=True)}})
        if n == 5:
            p = os.path.join(d, "demo_back.jpg"); synth.pothole(p, seed=103)
            out = core.submit_complaint(conn, description="The pothole has come back at the same spot!",
                                        lat=DEMO_LAT, lon=DEMO_LON + 0.00002, image_path=p,
                                        created_at=iso(now(-30)), name="Citizen C", is_sample=True)
            out["asset"] = asset_summary(conn, a["asset_id"], now(), full=True)
            return jsonify({"step": 5, "title": "Damage returns: recurrence detected", "result": out})
        return jsonify({"error": "steps are 1-5"}), 400
    finally:
        conn.close()


@app.get("/api/demo/location")
def demo_location():
    return jsonify({"lat": DEMO_LAT, "lon": DEMO_LON})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
