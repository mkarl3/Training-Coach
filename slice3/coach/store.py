"""Conversation persistence — check-ins survive across sessions (SQLite).

Lives in the same coach.db as the subjective notes so a check-in, its messages, and the
notes it produced are one consistent store, stitched to the training timeline by date.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL DEFAULT 1,   -- scopes the conversation to an athlete
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


def ensure_column(conn, table, col, decl):
    """Idempotent migration — add a column to an existing table if it's missing
    (backfills the DEFAULT for rows created before the column existed)."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def connect(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    ensure_column(conn, "conversation", "athlete_id", "INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    return conn


def start_conversation(conn, as_of, started_at, athlete_id=1):
    cur = conn.execute("INSERT INTO conversation (athlete_id, started_at, as_of) VALUES (?,?,?)",
                       (athlete_id, started_at, as_of))
    conn.commit()
    return cur.lastrowid


def latest_conversation(conn, athlete_id=1):
    row = conn.execute("SELECT id, as_of FROM conversation WHERE athlete_id=? "
                       "ORDER BY id DESC LIMIT 1", (athlete_id,)).fetchone()
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
