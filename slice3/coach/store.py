"""Conversation persistence — check-ins survive across sessions (SQLite).

Lives in the same coach.db as the subjective notes so a check-in, its messages, and the
notes it produced are one consistent store, stitched to the training timeline by date.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    as_of       TEXT NOT NULL             -- the training-data date this conversation anchors to
);
CREATE TABLE IF NOT EXISTS message (
    id          INTEGER PRIMARY KEY,
    conv_id     INTEGER NOT NULL REFERENCES conversation(id),
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_conv ON message(conv_id);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def start_conversation(conn, as_of, started_at):
    cur = conn.execute("INSERT INTO conversation (started_at, as_of) VALUES (?, ?)",
                       (started_at, as_of))
    conn.commit()
    return cur.lastrowid


def latest_conversation(conn):
    row = conn.execute("SELECT id, as_of FROM conversation ORDER BY id DESC LIMIT 1").fetchone()
    return row  # (id, as_of) or None


def add_message(conn, conv_id, role, content, created_at):
    conn.execute("INSERT INTO message (conv_id, role, content, created_at) VALUES (?,?,?,?)",
                 (conv_id, role, content, created_at))
    conn.commit()


def history(conn, conv_id, limit=None):
    q = "SELECT role, content, created_at FROM message WHERE conv_id=? ORDER BY id"
    rows = list(conn.execute(q, (conv_id,)))
    return rows[-limit:] if limit else rows


def prior_checkin_dates(conn, before_conv_id, limit=6):
    """Dates of earlier conversations — lets the coach reference past check-ins."""
    return [r[0] for r in conn.execute(
        "SELECT as_of FROM conversation WHERE id < ? ORDER BY id DESC LIMIT ?",
        (before_conv_id, limit))]
