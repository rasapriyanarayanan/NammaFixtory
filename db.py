"""SQLite persistence (the production plan uses PostgreSQL + PostGIS; the logical
schema here mirrors the project document so it can be migrated)."""
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NAMMAFIXTORY_DB", os.path.join(BASE, "nammafixtory.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    role TEXT DEFAULT 'citizen',
    contact TEXT,                -- optional, officer-only
    consent INTEGER DEFAULT 0,   -- consent to store contact + location
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS wards (
    ward_id INTEGER PRIMARY KEY,
    name TEXT, lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS sensitive_places (
    place_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, kind TEXT, lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS infrastructure_assets (
    asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_code TEXT UNIQUE,
    family TEXT,                 -- road | drainage | sanitation | public
    label TEXT,
    lat REAL, lon REAL,
    ward_id INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT UNIQUE,
    user_id INTEGER,
    asset_id INTEGER,
    category TEXT,
    category_source TEXT,        -- citizen | nlp | image | merged
    description TEXT,
    language TEXT,
    lat REAL, lon REAL,
    location_text TEXT,
    status TEXT DEFAULT 'open',  -- open | under_review | in_repair | resolved | rejected
    duplicate_of INTEGER,        -- complaint_id of canonical report (suggested)
    duplicate_state TEXT,        -- suggested | confirmed | rejected
    episode INTEGER,             -- damage episode number on the asset
    channel TEXT DEFAULT 'web',
    is_sample INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS complaint_images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    path TEXT,
    kind TEXT DEFAULT 'report',
    privacy TEXT,                -- blurred | none_found | officer_cleared | officer_blurred | synthetic | detector_unavailable
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_analysis (
    analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    predicted_category TEXT,
    confidence REAL,
    detector TEXT,
    detail TEXT,                 -- JSON
    human_review TEXT DEFAULT 'pending',   -- pending | confirmed | corrected
    analysis_date TEXT
);
CREATE TABLE IF NOT EXISTS duplicate_reports (
    dup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    matches_complaint_id INTEGER,
    score REAL,
    geo_score REAL, text_score REAL, image_score REAL,
    state TEXT DEFAULT 'suggested',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS priority_records (
    priority_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    score REAL,
    level TEXT,
    factors TEXT,                -- JSON explanation
    computed_at TEXT
);
CREATE TABLE IF NOT EXISTS repair_records (
    repair_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    officer TEXT,
    status TEXT,                 -- in_progress | completed
    notes TEXT,
    started_at TEXT,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS repair_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    repair_id INTEGER,
    before_image TEXT,
    after_image TEXT,
    ai_result TEXT,              -- consistent_pending_confirmation | needs_review | insufficient
    ai_detail TEXT,              -- JSON
    review_status TEXT DEFAULT 'awaiting_officer',  -- awaiting_officer | officer_confirmed | officer_rejected
    review_notes TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS citizen_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    resolved INTEGER,
    comment TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER,
    channel TEXT,
    message TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT, action TEXT, target TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS channel_sessions (
    sender_hash TEXT PRIMARY KEY,   -- salted hash of the phone number; the number itself is never stored
    channel TEXT,
    state TEXT,                     -- JSON: the half-finished report (text, photo path, language)
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_c_asset ON complaints(asset_id);
CREATE INDEX IF NOT EXISTS idx_c_created ON complaints(created_at);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Upgrade databases created before photo-privacy tracking existed.

    Sample (synthetic) photos contain no people, so they are marked 'synthetic'. Any other photo without a
    recorded privacy check stays NULL, which the app treats as held for officers (fail closed).
    """
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(complaint_images)").fetchall()]
    if "privacy" not in cols:
        conn.execute("ALTER TABLE complaint_images ADD COLUMN privacy TEXT")
    conn.execute("""UPDATE complaint_images SET privacy='synthetic' WHERE privacy IS NULL AND complaint_id IN
                    (SELECT complaint_id FROM complaints WHERE is_sample=1)""")


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


def reset_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def audit(conn, actor, action, target, ts):
    conn.execute(
        "INSERT INTO audit_log(actor,action,target,created_at) VALUES (?,?,?,?)",
        (actor, action, target, ts),
    )
