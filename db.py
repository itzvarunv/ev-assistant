#Database
import re
import sqlite3
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    contact_id TEXT,
    role TEXT,
    text TEXT,
    at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id INTEGER PRIMARY KEY,
    path TEXT,
    filename TEXT,
    sha256 TEXT UNIQUE,
    kind TEXT,
    title TEXT,
    description TEXT,
    content TEXT,
    added TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(title, description, content);
CREATE TABLE IF NOT EXISTS doc_permissions (
    doc_id INTEGER,
    contact_id TEXT,              -- '*' means anyone
    PRIMARY KEY (doc_id, contact_id)
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    contact_id TEXT,
    text TEXT,
    topic TEXT,
    at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    source TEXT,
    chunk TEXT,
    added TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(topic, chunk);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    contact_id TEXT,
    contact_name TEXT,
    title TEXT,
    details TEXT,
    due TEXT,
    status TEXT DEFAULT 'open',   -- open / done
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS owner_outbox (   -- notices WhatsApp wouldn't deliver yet (24h window)
    id INTEGER PRIMARY KEY,
    text TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pending_messages (  -- held back REPLY_DELAY_SECONDS so the owner can answer first
    id INTEGER PRIMARY KEY,
    contact_id TEXT,
    name TEXT,
    text TEXT,
    due_at REAL,
    image_path TEXT                           -- photo they sent, read by the vision model when answering
);
CREATE TABLE IF NOT EXISTS takeovers (         -- owner replied from the phone: EV stays quiet until then
    contact_id TEXT PRIMARY KEY,
    until_at REAL
);
CREATE TABLE IF NOT EXISTS skip_contacts (     -- people EV never answers (family, close friends)
    contact_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS events (            -- the owner's own schedule, for reminders
    id INTEGER PRIMARY KEY,
    title TEXT,
    start_at TEXT,                            -- local time, "YYYY-MM-DD HH:MM"
    remind_before_min INTEGER DEFAULT 30,
    repeat TEXT,                              -- NULL, 'daily' or 'weekly'
    before_sent INTEGER DEFAULT 0,
    status TEXT DEFAULT 'upcoming',           -- upcoming / done / missed / cancelled
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seen_messages (  -- WhatsApp retries webhooks; handle each message once
    msg_id TEXT PRIMARY KEY
);
"""


def get_connection():
    config.DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    try:   # databases created before photo support
        db.execute("ALTER TABLE pending_messages ADD COLUMN image_path TEXT")
    except sqlite3.OperationalError:
        pass
    return db


def fts_query(text):
    # Turn free text into a safe FTS5 query: "word1" OR "word2" ...
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(w) > 2]
    return " OR ".join(f'"{w}"' for w in words[:12])


def allowed_docs(db, contact_id):
    return db.execute("""
        SELECT DISTINCT d.* FROM documents d
        JOIN doc_permissions p ON p.doc_id = d.doc_id
        WHERE p.contact_id IN (?, '*')
    """, (contact_id,)).fetchall()


def can_send(db, doc_id, contact_id):
    row = db.execute(
        "SELECT 1 FROM doc_permissions WHERE doc_id = ? AND contact_id IN (?, '*')",
        (doc_id, contact_id)).fetchone()
    return row is not None


def search_knowledge(db, text, limit=3):
    q = fts_query(text)
    if not q:
        return []
    return db.execute(
        "SELECT topic, chunk FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
        (q, limit)).fetchall()


def ev_is_on(db):
    row = db.execute("SELECT value FROM settings WHERE key = 'ev_on'").fetchone()
    return row is None or row["value"] == "1"


def should_stay_quiet(db, contact_id, now):
    """True if EV must not answer this person right now."""
    if not ev_is_on(db):
        return True
    if db.execute("SELECT 1 FROM skip_contacts WHERE contact_id = ?", (contact_id,)).fetchone():
        return True
    return db.execute("SELECT 1 FROM takeovers WHERE contact_id = ? AND until_at > ?",
                      (contact_id, now)).fetchone() is not None
