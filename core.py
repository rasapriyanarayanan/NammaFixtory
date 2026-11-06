"""Business logic that connects the modules (used by the API and the demo)."""
import json
import os
import secrets
import shutil

import db
from ai import detect, nlp, privacy
from ai.duplicates import find_duplicate
from ai.evidence import compare, exif_info
from ai.priority import compute_priority
from ai.recurrence import asset_summary, build_history
from util import CATEGORY_LABEL, DEPARTMENT, FAMILY, haversine_m, iso, now, parse

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
ASSET_MATCH_M = 30.0
os.makedirs(UPLOADS, exist_ok=True)

CATEGORY_CHOICES = list(CATEGORY_LABEL.keys())

# A citizen photo may be shown to the public only in these privacy states. Anything else (including a photo whose
# privacy check could not run) is visible to authenticated officers only.
PUBLIC_PRIVACY = {"blurred", "none_found", "officer_cleared", "officer_blurred", "synthetic"}


def new_ref(conn):
    while True:
        ref = "NFX-" + now().strftime("%y%m%d") + "-" + secrets.token_hex(2).upper()
        if not conn.execute("SELECT 1 FROM complaints WHERE ref=?", (ref,)).fetchone():
            return ref


def nearest_ward(conn, lat, lon):
    best, bd = None, 1e12
    for w in conn.execute("SELECT * FROM wards").fetchall():
        d = haversine_m(lat, lon, w["lat"], w["lon"])
        if d < bd:
            best, bd = w["ward_id"], d
    return best


def match_or_create_asset(conn, family, category, lat, lon, ts):
    best, bd = None, 1e12
    for a in conn.execute("SELECT * FROM infrastructure_assets WHERE family=?", (family,)).fetchall():
        d = haversine_m(lat, lon, a["lat"], a["lon"])
        if d < bd:
            best, bd = a, d
    if best is not None and bd <= ASSET_MATCH_M:
        return best["asset_id"], False
    ward = nearest_ward(conn, lat, lon)
    n = conn.execute("SELECT COUNT(*) FROM infrastructure_assets").fetchone()[0] + 1
    code = f"AST-{family[:3].upper()}-{n:04d}"
    cur = conn.execute(
        "INSERT INTO infrastructure_assets(asset_code,family,label,lat,lon,ward_id,created_at) VALUES (?,?,?,?,?,?,?)",
        (code, family, f"{family.title()} section near ({lat:.4f}, {lon:.4f})", lat, lon, ward, ts))
    return cur.lastrowid, True


def _episode_number(conn, asset_id, now_dt, new_complaint_id):
    h = build_history(conn, asset_id, now_dt)
    return h["episodes"]


def submit_complaint(conn, *, description, lat, lon, category=None, image_path=None, name=None,
                     contact=None, consent=False, location_text="", channel="web",
                     created_at=None, is_sample=False, officer_ctx=None):
    """Full intake pipeline. Returns a dict describing everything the system inferred."""
    ts = created_at or iso(now())
    now_dt = parse(ts)

    # 1) language + NLP
    text_info = nlp.structure_complaint(description, location_text)

    # 2) image analysis
    img_info = detect.analyse_image(image_path) if image_path else None

    # 2b) photo privacy: sample photos are synthetic; real citizen photos get faces/plates blurred, and a photo
    #     the detector could not check is held for officers only (see app.py /uploads gate).
    photo_privacy = None
    if image_path:
        if is_sample:
            photo_privacy = "synthetic"
        else:
            try:
                photo_privacy = privacy.protect_image(image_path)["status"]
            except Exception:
                photo_privacy = "detector_unavailable"

    # 3) resolve category (citizen > confident image > text > other); keep every signal
    cat, src = None, None
    if category and category in CATEGORY_LABEL:
        cat, src = category, "citizen"
    elif img_info and img_info["confidence"] >= 0.55 and img_info["category"] != "other":
        cat, src = img_info["category"], "image"
    elif text_info["category"]:
        cat, src = text_info["category"], "nlp"
    elif img_info and img_info["category"] != "other":
        cat, src = img_info["category"], "image"
    else:
        cat, src = "other", "nlp"
    family = FAMILY.get(cat, "public")

    # 4) user (optional contact, only with consent)
    uid = None
    if name or (contact and consent):
        cur = conn.execute("INSERT INTO users(name,role,contact,consent,created_at) VALUES (?,?,?,?,?)",
                           (name, "citizen", contact if consent else None, 1 if consent else 0, ts))
        uid = cur.lastrowid

    # 5) asset (infrastructure history anchor)
    asset_id, created_asset = match_or_create_asset(conn, family, cat, lat, lon, ts)

    ref = new_ref(conn)
    cur = conn.execute(
        """INSERT INTO complaints(ref,user_id,asset_id,category,category_source,description,language,lat,lon,
           location_text,status,channel,is_sample,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ref, uid, asset_id, cat, src, description, text_info["language"], lat, lon, location_text,
         "open", channel, 1 if is_sample else 0, ts, ts))
    cid = cur.lastrowid
    if image_path:
        conn.execute("INSERT INTO complaint_images(complaint_id,path,kind,privacy,created_at) VALUES (?,?,?,?,?)",
                     (cid, image_path, "report", photo_privacy, ts))
    if img_info:
        conn.execute(
            "INSERT INTO ai_analysis(complaint_id,predicted_category,confidence,detector,detail,analysis_date) "
            "VALUES (?,?,?,?,?,?)",
            (cid, img_info["category"], img_info["confidence"], img_info["detector"],
             json.dumps({**img_info["detail"], "quality": img_info["quality"]}), ts))

    # 6) duplicates (suggested only)
    dup = find_duplicate(conn, {"lat": lat, "lon": lon, "category": cat, "description": description},
                         image_path, ts, exclude_id=cid)
    dup_out = None
    if dup:
        s = dup["score"]
        conn.execute("UPDATE complaints SET duplicate_of=?, duplicate_state='suggested' WHERE complaint_id=?",
                     (dup["canonical_id"], cid))
        conn.execute(
            "INSERT INTO duplicate_reports(complaint_id,matches_complaint_id,score,geo_score,text_score,image_score,state,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cid, dup["match"]["complaint_id"], s["score"], s["geo"], s["text"], s["image"], "suggested", ts))
        dup_out = {"matches_ref": dup["match"]["ref"], **s}

    # 7) history + priority
    hist = build_history(conn, asset_id, now_dt)
    n_reports = conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE status IN ('open','under_review','in_repair') AND asset_id=?",
        (asset_id,)).fetchone()[0]
    comp = {"category": cat, "description": description, "lat": lat, "lon": lon, "created_at": ts}
    pri = compute_priority(conn, comp, max(1, n_reports), hist["recurrences"], now_dt)
    conn.execute("INSERT INTO priority_records(complaint_id,score,level,factors,computed_at) VALUES (?,?,?,?,?)",
                 (cid, pri["score"], pri["level"], json.dumps(pri["factors"]), ts))
    conn.execute("UPDATE complaints SET episode=? WHERE complaint_id=?", (hist["episodes"], cid))

    conn.execute("INSERT INTO notifications(complaint_id,channel,message,created_at) VALUES (?,?,?,?)",
                 (cid, channel, f"Complaint {ref} received. Department: {DEPARTMENT[family]}.", ts))
    conn.commit()

    return {
        "ref": ref,
        "category": cat,
        "category_label": CATEGORY_LABEL[cat],
        "category_source": src,
        "department": DEPARTMENT[family],
        "asset_id": asset_id,
        "new_asset": created_asset,
        "language": text_info["language"],
        "nlp": text_info,
        "image_analysis": img_info,
        "photo_privacy": photo_privacy,
        "photo_public": photo_privacy in PUBLIC_PRIVACY if photo_privacy else None,
        "duplicate": dup_out,
        "priority": pri,
        "history": {k: v for k, v in hist.items() if not k.startswith("_") and k != "timeline"},
        "recurrence_detected": any(t["type"] == "recurrence" and t["ts"] == ts for t in hist["timeline"]),
        "human_review_note": "AI suggestions are not final; an officer reviews every complaint.",
    }


def complete_repair(conn, asset_id, *, officer, notes="", after_image=None, completed_at=None):
    ts = completed_at or iso(now())
    started = iso(parse(ts).replace(hour=max(0, parse(ts).hour - 1)))
    cur = conn.execute(
        "INSERT INTO repair_records(asset_id,officer,status,notes,started_at,completed_at) VALUES (?,?,?,?,?,?)",
        (asset_id, officer, "completed", notes, started, ts))
    rid = cur.lastrowid

    before = conn.execute(
        """SELECT i.path FROM complaint_images i JOIN complaints c ON c.complaint_id=i.complaint_id
           WHERE c.asset_id=? AND c.status IN ('open','under_review','in_repair')
           ORDER BY i.image_id LIMIT 1""", (asset_id,)).fetchone()
    evidence = None
    if after_image and before:
        res = compare(before["path"], after_image)
        res["exif_after"] = exif_info(after_image)
        conn.execute(
            "INSERT INTO repair_evidence(repair_id,before_image,after_image,ai_result,ai_detail,created_at) "
            "VALUES (?,?,?,?,?,?)", (rid, before["path"], after_image, res["result"], json.dumps(res), ts))
        evidence = res
    elif after_image:
        res = {"result": "needs_review", "reasons": ["no before photo is stored for this asset"], "metrics": {}}
        conn.execute(
            "INSERT INTO repair_evidence(repair_id,before_image,after_image,ai_result,ai_detail,created_at) "
            "VALUES (?,?,?,?,?,?)", (rid, None, after_image, res["result"], json.dumps(res), ts))
        evidence = res

    conn.execute(
        "UPDATE complaints SET status='resolved', updated_at=? WHERE asset_id=? AND status IN "
        "('open','under_review','in_repair')", (ts, asset_id))
    for c in conn.execute("SELECT complaint_id, ref FROM complaints WHERE asset_id=? AND updated_at=?",
                          (asset_id, ts)).fetchall():
        conn.execute("INSERT INTO notifications(complaint_id,channel,message,created_at) VALUES (?,?,?,?)",
                     (c["complaint_id"], "web",
                      f"Complaint {c['ref']}: repair recorded. Please confirm whether the problem is fixed.", ts))
    db.audit(conn, officer, "repair_completed", f"asset:{asset_id}", ts)
    conn.commit()
    return {"repair_id": rid, "evidence": evidence, "completed_at": ts}


def public_complaint(conn, ref, officer=False):
    c = db.row(conn, "SELECT * FROM complaints WHERE ref=?", (ref,))
    if not c:
        return None
    c["category_label"] = CATEGORY_LABEL.get(c["category"], c["category"])
    c["priority"] = db.row(conn, "SELECT score,level,factors FROM priority_records WHERE complaint_id=? "
                                 "ORDER BY priority_id DESC LIMIT 1", (c["complaint_id"],))
    if c["priority"]:
        c["priority"]["factors"] = json.loads(c["priority"]["factors"])
    c["ai"] = db.row(conn, "SELECT predicted_category,confidence,detector,detail,human_review FROM ai_analysis "
                           "WHERE complaint_id=? ORDER BY analysis_id DESC LIMIT 1", (c["complaint_id"],))
    if c["ai"]:
        c["ai"]["detail"] = json.loads(c["ai"]["detail"])
    imgs = db.rows(conn, "SELECT path,privacy FROM complaint_images WHERE complaint_id=?", (c["complaint_id"],))
    c["image_info"] = [{"name": os.path.basename(r["path"]), "privacy": r["privacy"] or "unchecked",
                        "public": r["privacy"] in PUBLIC_PRIVACY} for r in imgs]
    if officer:
        c["images"] = [i["name"] for i in c["image_info"]]
    else:  # the public sees only photos that passed the privacy gate; the rest are counted, not shown
        c["images"] = [i["name"] for i in c["image_info"] if i["public"]]
        c["images_held"] = sum(1 for i in c["image_info"] if not i["public"])
        c.pop("image_info")
    c["notifications"] = db.rows(conn, "SELECT channel,message,created_at FROM notifications WHERE complaint_id=?",
                                 (c["complaint_id"],))
    if c["duplicate_of"]:
        m = db.row(conn, "SELECT ref FROM complaints WHERE complaint_id=?", (c["duplicate_of"],))
        c["duplicate_of_ref"] = m["ref"] if m else None
    # privacy: never expose contact or user id publicly
    c.pop("user_id", None)
    if not officer:
        c["lat"], c["lon"] = round(c["lat"], 4), round(c["lon"], 4)
    return c
