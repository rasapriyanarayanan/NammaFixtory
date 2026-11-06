"""WhatsApp channel (EXPERIMENTAL; runs fully offline through the simulator).

A citizen sends a photo, a description and a shared location in WhatsApp. NammaFixtory runs the same intake
pipeline as the web form and replies with a reference number in Tamil or English.

What is real and what is not
  * REAL: the webhook speaks Meta's WhatsApp Cloud API format (GET verification challenge, POST message
    payloads for text / image / location, optional X-Hub-Signature-256 check), and the conversation logic.
  * NOT live: sending replies and downloading photos need WhatsApp Business API credentials. Set
    WHATSAPP_TOKEN, WHATSAPP_PHONE_ID (and WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN) to enable them.
    Without credentials, replies are returned to the caller (the simulator page shows them).
  * Privacy: phone numbers are never stored. Half-finished reports are keyed by a salted hash and deleted as
    soon as the complaint is filed or after 30 minutes.
"""
import hashlib
import hmac
import json
import os
import re
import tempfile
import uuid
from datetime import timedelta

from flask import Blueprint, jsonify, request

import core
import db
from ai import nlp
from util import iso, now, parse

bp = Blueprint("whatsapp", __name__)

SESSION_MINUTES = 30
GRAPH = "https://graph.facebook.com/v20.0"
REF_RE = re.compile(r"NFX-\d{6}-[0-9A-F]{4}", re.I)
GREETINGS = {"hi", "hello", "hey", "help", "start", "menu", "வணக்கம்", "உதவி", "ஹலோ"}

T = {
    "help": {
        "en": "Welcome to NammaFixtory. Send a photo of the problem and a short description (Tamil or English), "
              "then share the location (attach > Location). To check a report, send: status NFX-xxxxxx-xxxx",
        "ta": "NammaFixtory-க்கு வரவேற்கிறோம். பிரச்சினையின் புகைப்படத்தையும் சிறு விளக்கத்தையும் (தமிழ் அல்லது "
              "ஆங்கிலம்) அனுப்புங்கள், பிறகு இருப்பிடத்தைப் பகிருங்கள் (இணை > Location). நிலையை அறிய: "
              "status NFX-xxxxxx-xxxx",
    },
    "need_loc": {
        "en": "Thanks, got it. Now please share the location (attach > Location) so we can find the spot.",
        "ta": "நன்றி. இடத்தைக் கண்டறிய இப்போது இருப்பிடத்தைப் பகிருங்கள் (இணை > Location).",
    },
    "need_desc": {
        "en": "Location received. Now send a photo or a short description of the problem.",
        "ta": "இருப்பிடம் கிடைத்தது. இப்போது புகைப்படம் அல்லது சிறு விளக்கத்தை அனுப்புங்கள்.",
    },
    "received": {
        "en": "Complaint received. Reference: {ref}\nType: {cat}\nDepartment: {dept}\nPriority: {level}\n"
              "An officer will review it. Check progress any time: status {ref}",
        "ta": "புகார் பெறப்பட்டது. குறிப்பு எண்: {ref}\nவகை: {cat}\nதுறை: {dept}\nமுன்னுரிமை: {level}\n"
              "அதிகாரி இதைப் பரிசீலிப்பார். நிலையை அறிய: status {ref}",
    },
    "dup": {
        "en": "A similar report may already exist at this spot. An officer will check, and both reports are kept.",
        "ta": "இதே இடத்தில் ஏற்கனவே இது போன்ற புகார் இருக்கக்கூடும். அதிகாரி சரிபார்ப்பார்; இரு புகார்களும் சேமிக்கப்படும்.",
    },
    "recur": {
        "en": "This spot was repaired before and has been damaged again. It is flagged for an engineer's inspection.",
        "ta": "இந்த இடம் முன்பு பழுது பார்க்கப்பட்டு மீண்டும் சேதமடைந்துள்ளது. பொறியாளர் ஆய்வுக்குக் குறிக்கப்பட்டுள்ளது.",
    },
    "status": {
        "en": "{ref}: {cat}, status: {status}.",
        "ta": "{ref}: {cat}, நிலை: {status}.",
    },
    "nf": {
        "en": "We could not find that reference number. Please check it and try again.",
        "ta": "அந்த குறிப்பு எண் கிடைக்கவில்லை. சரிபார்த்து மீண்டும் முயலுங்கள்.",
    },
    "bad_img": {
        "en": "We could not read that photo. Please describe the problem in words, or send the photo again.",
        "ta": "அந்தப் புகைப்படத்தைப் படிக்க முடியவில்லை. பிரச்சினையை எழுத்தில் விவரிக்கவும் அல்லது மீண்டும் அனுப்பவும்.",
    },
    "level": {  # keys are lower-case; the priority engine returns Low / Medium / High
        "en": {"low": "Low", "medium": "Medium", "high": "High"},
        "ta": {"low": "குறைவு", "medium": "நடுத்தரம்", "high": "அதிகம்"},
    },
    "st": {
        "en": {"open": "open", "under_review": "under review", "in_repair": "being repaired",
               "resolved": "resolved", "rejected": "closed"},
        "ta": {"open": "திறந்துள்ளது", "under_review": "பரிசீலனையில்", "in_repair": "பழுது நடைபெறுகிறது",
               "resolved": "தீர்க்கப்பட்டது", "rejected": "மூடப்பட்டது"},
    },
}


def _t(key, lang, **kw):
    s = T[key].get(lang) or T[key]["en"]
    return s.format(**kw) if kw else s


def sender_hash(sender: str) -> str:
    salt = os.environ.get("NAMMAFIXTORY_SALT", "dev-salt-change-me")
    return hashlib.sha256((salt + str(sender)).encode()).hexdigest()


def _load(conn, h):
    r = db.row(conn, "SELECT state, updated_at FROM channel_sessions WHERE sender_hash=?", (h,))
    if not r:
        return {}
    if parse(r["updated_at"]) < now() - timedelta(minutes=SESSION_MINUTES):
        conn.execute("DELETE FROM channel_sessions WHERE sender_hash=?", (h,))
        return {}
    return json.loads(r["state"])


def _save(conn, h, state):
    conn.execute("INSERT OR REPLACE INTO channel_sessions(sender_hash,channel,state,updated_at) VALUES (?,?,?,?)",
                 (h, "whatsapp", json.dumps(state), iso(now())))


def _clear(conn, h):
    conn.execute("DELETE FROM channel_sessions WHERE sender_hash=?", (h,))


def _status_reply(conn, ref, lang):
    c = db.row(conn, "SELECT ref,category,status FROM complaints WHERE ref=?", (ref.upper(),))
    if not c:
        return _t("nf", lang)
    from util import CATEGORY_LABEL
    return _t("status", lang, ref=c["ref"], cat=CATEGORY_LABEL.get(c["category"], c["category"]),
              status=T["st"][lang].get(c["status"], c["status"]))


def _file(conn, h, state, lang):
    out = core.submit_complaint(
        conn, description=state.get("text", ""), lat=state["lat"], lon=state["lon"],
        image_path=state.get("image"), channel="whatsapp", location_text="Shared via WhatsApp")
    _clear(conn, h)
    msgs = [_t("received", lang, ref=out["ref"], cat=out["category_label"], dept=out["department"],
               level=T["level"][lang].get(str(out["priority"]["level"]).lower(), out["priority"]["level"]))]
    if out.get("duplicate"):
        msgs.append(_t("dup", lang))
    if out.get("recurrence_detected"):
        msgs.append(_t("recur", lang))
    return msgs, out["ref"]


def handle_message(conn, sender, msg):
    """Process one normalised incoming message. Returns {"replies": [...], "ref": str|None}.

    msg: {"type": "text", "text": str} | {"type": "image", "path": str, "caption": str}
         | {"type": "location", "lat": float, "lon": float}
    """
    h = sender_hash(sender)
    state = _load(conn, h)
    lang = state.get("lang", "en")
    kind = msg.get("type")

    if kind == "text":
        text = (msg.get("text") or "").strip()
        if text:
            lang = nlp.detect_language(text) if nlp.detect_language(text) in ("ta", "en") else lang
        low = text.lower()
        m = REF_RE.search(text)
        if low.startswith("status") or (m and len(text) <= 40):
            conn.commit()
            return {"replies": [_status_reply(conn, m.group(0), lang)] if m else [_t("help", lang)], "ref": None}
        if low in GREETINGS or text in GREETINGS or not text:
            conn.commit()
            return {"replies": [_t("help", "en"), _t("help", "ta")] if not state else [_t("help", lang)], "ref": None}
        state["text"] = (state.get("text", "") + " " + text).strip()[:1000]
    elif kind == "image":
        path = msg.get("path")
        if not path or not os.path.exists(path):
            conn.commit()
            return {"replies": [_t("bad_img", lang)], "ref": None}
        state["image"] = path  # faces/plates are blurred (or the photo is held) inside core.submit_complaint
        cap = (msg.get("caption") or "").strip()
        if cap:
            state["text"] = (state.get("text", "") + " " + cap).strip()[:1000]
            lang = nlp.detect_language(cap) if nlp.detect_language(cap) in ("ta", "en") else lang
    elif kind == "location":
        try:
            lat, lon = float(msg["lat"]), float(msg["lon"])
        except (KeyError, TypeError, ValueError):
            return {"replies": [_t("need_loc", lang)], "ref": None}
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return {"replies": [_t("need_loc", lang)], "ref": None}
        state["lat"], state["lon"] = lat, lon
    else:
        return {"replies": [_t("help", lang)], "ref": None}

    state["lang"] = lang
    has_content = bool(state.get("text") or state.get("image"))
    has_loc = "lat" in state
    if has_content and has_loc:
        replies, ref = _file(conn, h, state, lang)
        conn.commit()
        return {"replies": replies, "ref": ref}
    _save(conn, h, state)
    conn.commit()
    return {"replies": [_t("need_loc" if has_content else "need_desc", lang)], "ref": None}


# --------------------------------------------------------------- Meta Cloud API
def _send(to, body):
    """Send a reply through the WhatsApp Cloud API when credentials are configured."""
    token, pid = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_ID")
    if not (token and pid):
        return False
    import requests
    r = requests.post(f"{GRAPH}/{pid}/messages", timeout=10,
                      headers={"Authorization": f"Bearer {token}"},
                      json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}})
    return r.ok


def _download_media(media_id):
    token = os.environ.get("WHATSAPP_TOKEN")
    if not token:
        return None
    import requests
    h = {"Authorization": f"Bearer {token}"}
    meta = requests.get(f"{GRAPH}/{media_id}", headers=h, timeout=10).json()
    data = requests.get(meta["url"], headers=h, timeout=20)
    if not data.ok or len(data.content) > 8 * 1024 * 1024:
        return None
    path = os.path.join(core.UPLOADS, f"w_{uuid.uuid4().hex[:12]}.jpg")
    with open(path, "wb") as f:
        f.write(data.content)
    return path


def _signature_ok(raw: bytes) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret:
        return True  # signature checking is off until a secret is configured
    sig = request.headers.get("X-Hub-Signature-256", "")
    good = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def normalise_cloud_message(m):
    t = m.get("type")
    if t == "text":
        return {"type": "text", "text": m["text"]["body"]}
    if t == "location":
        return {"type": "location", "lat": m["location"]["latitude"], "lon": m["location"]["longitude"]}
    if t == "image":
        return {"type": "image", "path": _download_media(m["image"]["id"]),
                "caption": m["image"].get("caption", "")}
    return {"type": "other"}


@bp.get("/webhook/whatsapp")
def verify():
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "nammafixtory-verify")
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == expected:
        return request.args.get("hub.challenge", ""), 200
    return "forbidden", 403


@bp.post("/webhook/whatsapp")
def webhook():
    raw = request.get_data()
    if not _signature_ok(raw):
        return "bad signature", 403
    payload = request.get_json(silent=True) or {}
    conn = db.connect()
    try:
        for entry in payload.get("entry", []):
            for ch in entry.get("changes", []):
                for m in ch.get("value", {}).get("messages", []):
                    out = handle_message(conn, m.get("from", ""), normalise_cloud_message(m))
                    for body in out["replies"]:
                        _send(m.get("from", ""), body)
        return jsonify({"ok": True}), 200
    finally:
        conn.close()


# ------------------------------------------------------------------- simulator
@bp.post("/api/channels/simulate")
def simulate():
    """Offline stand-in for WhatsApp: same conversation logic, replies returned in the response."""
    f = request.form
    sender = (f.get("sender") or "sim-user")[:40]
    kind = f.get("type", "text")
    msg = {"type": kind}
    if kind == "text":
        msg["text"] = (f.get("text") or "")[:1000]
    elif kind == "location":
        msg["lat"], msg["lon"] = f.get("lat"), f.get("lon")
    elif kind == "image":
        up = request.files.get("image")
        if not up or not up.filename:
            return jsonify({"error": "attach an image"}), 400
        ext = os.path.splitext(up.filename)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            return jsonify({"error": "Only JPG, PNG or WEBP images are accepted"}), 400
        path = os.path.join(core.UPLOADS, f"w_{uuid.uuid4().hex[:12]}{ext}")
        up.save(path)
        from PIL import Image
        try:
            with Image.open(path) as im:
                im.verify()
        except Exception:
            os.remove(path)
            return jsonify({"error": "That file is not a valid image"}), 400
        msg["path"], msg["caption"] = path, (f.get("text") or "")[:500]
    else:
        return jsonify({"error": "type must be text, image or location"}), 400
    conn = db.connect()
    try:
        out = handle_message(conn, sender, msg)
        return jsonify({**out, "live_sending": bool(os.environ.get("WHATSAPP_TOKEN"))})
    finally:
        conn.close()
