"""Dated load-FTP history — the athlete's THRESHOLD/set FTP (WKO5 'bikeFTP') over time, the number
used for TSS / IF / power-zone time. An entry's value applies from its effective_date FORWARD until
the next entry; rides before the earliest entry use that earliest value (back-fill).

This is the LOAD side of the two-FTP model and is DISTINCT from the modeled CP/mFTP that drives the
progression gates (that one is computed from the power-duration curve, never stored here).

Persisted in the app DB (coach.db) so it survives the wko.db rebuilds. Read at DB-build time and
handed to the Strava metrics engine as a plain sorted list of {date, ftp} — the engine has no DB
dependency. Entries are either 'manual' (athlete-entered, dated as they choose) or 'strava'
(captured from the athlete's current Strava FTP on a pull, dated the day we first saw it).
"""
from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ftp_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id     INTEGER NOT NULL DEFAULT 1,
    effective_date TEXT NOT NULL,                    -- ISO date the FTP took effect
    ftp_w          REAL NOT NULL,
    source         TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'strava' | 'seed'
    created_at     TEXT,
    UNIQUE(athlete_id, effective_date)               -- one set-FTP per day
);
CREATE TABLE IF NOT EXISTS ftp_pending (
    athlete_id INTEGER PRIMARY KEY,                  -- one open proposal per athlete
    ftp_w      REAL NOT NULL,
    seen_date  TEXT NOT NULL,                        -- date Strava first reported it (= the pull date)
    status     TEXT NOT NULL DEFAULT 'pending'       -- 'pending' (awaiting decision) | 'dismissed'
);
"""


def ensure(conn):
    conn.executescript(_SCHEMA)


def list_entries(conn, athlete_id: int = 1) -> list[dict]:
    """All entries, oldest first, shaped for the API + UI."""
    ensure(conn)
    rows = conn.execute(
        "SELECT id, effective_date, ftp_w, source FROM ftp_history WHERE athlete_id=? "
        "ORDER BY effective_date", (athlete_id,)).fetchall()
    return [{"id": r[0], "effective_date": r[1], "ftp": r[2], "source": r[3]} for r in rows]


def history(conn, athlete_id: int = 1) -> list[dict]:
    """Sorted [{date, ftp}] for the metrics engine (sources.metrics._ftp_resolver)."""
    return [{"date": e["effective_date"], "ftp": e["ftp"]} for e in list_entries(conn, athlete_id)]


def latest_ftp(conn, athlete_id: int = 1) -> float | None:
    """The current (most-recent-effective) set FTP, or None when there's no history yet."""
    rows = list_entries(conn, athlete_id)
    return rows[-1]["ftp"] if rows else None


def add_entry(conn, effective_date: str, ftp_w: float, source: str = "manual",
              created_at: str | None = None, athlete_id: int = 1) -> None:
    """Insert (or replace the same-day entry). Idempotent per (athlete, date)."""
    ensure(conn)
    conn.execute(
        "INSERT OR REPLACE INTO ftp_history (athlete_id, effective_date, ftp_w, source, created_at) "
        "VALUES (?,?,?,?,?)", (athlete_id, effective_date, float(ftp_w), source, created_at))
    conn.commit()


def delete_entry(conn, entry_id: int, athlete_id: int = 1) -> int:
    ensure(conn)
    cur = conn.execute("DELETE FROM ftp_history WHERE id=? AND athlete_id=?", (entry_id, athlete_id))
    conn.commit()
    return cur.rowcount


# --- Strava current-FTP PROPOSAL (propose -> athlete accepts/edits/dismisses; never auto-applied) -- #
def get_pending(conn, athlete_id: int = 1) -> dict | None:
    """The open Strava-FTP proposal awaiting the athlete's decision, or None (also None once
    dismissed — dismissal hides the notice but the value is remembered to avoid re-nagging)."""
    ensure(conn)
    r = conn.execute("SELECT ftp_w, seen_date, status FROM ftp_pending WHERE athlete_id=?",
                     (athlete_id,)).fetchone()
    if not r or r[2] != "pending":
        return None
    return {"ftp": r[0], "seen_date": r[1], "status": r[2]}


def _pending_value(conn, athlete_id: int = 1):
    r = conn.execute("SELECT ftp_w FROM ftp_pending WHERE athlete_id=?", (athlete_id,)).fetchone()
    return r[0] if r else None


def clear_pending(conn, athlete_id: int = 1) -> None:
    ensure(conn)
    conn.execute("DELETE FROM ftp_pending WHERE athlete_id=?", (athlete_id,))
    conn.commit()


def dismiss_pending(conn, athlete_id: int = 1) -> None:
    """Hide the notice but remember the value, so the same Strava FTP won't prompt again."""
    ensure(conn)
    conn.execute("UPDATE ftp_pending SET status='dismissed' WHERE athlete_id=?", (athlete_id,))
    conn.commit()


def clear_pending_if_value(conn, ftp_w, athlete_id: int = 1) -> None:
    """Drop the pending proposal once an entry of that value lands by other means (e.g. the athlete
    added it by hand via Edit)."""
    prev = _pending_value(conn, athlete_id)
    if prev is not None and abs(prev - float(ftp_w)) < 0.5:
        clear_pending(conn, athlete_id)


def propose_strava_ftp(conn, current_ftp, seen_date: str, athlete_id: int = 1) -> dict | None:
    """Compare Strava's current FTP to the latest entry on file. If it differs and we haven't
    already surfaced this exact value (pending OR dismissed), record it as a PENDING proposal — but
    apply nothing. Returns the proposal to surface, or None. Strava gives no change-date, so the
    proposal is stamped with `seen_date` (the pull date)."""
    if not current_ftp:
        return None
    current = float(current_ftp)
    latest = latest_ftp(conn, athlete_id)
    if latest is not None and abs(latest - current) < 0.5:
        clear_pending(conn, athlete_id)                  # already on file → nothing to decide
        return None
    prev = _pending_value(conn, athlete_id)
    if prev is not None and abs(prev - current) < 0.5:
        return get_pending(conn, athlete_id)             # same value already surfaced — don't re-nag
    ensure(conn)
    conn.execute("INSERT OR REPLACE INTO ftp_pending (athlete_id, ftp_w, seen_date, status) "
                 "VALUES (?,?,?, 'pending')", (athlete_id, current, seen_date))
    conn.commit()
    return {"ftp": current, "seen_date": seen_date, "status": "pending"}


def accept_pending(conn, athlete_id: int = 1) -> dict | None:
    """Move the pending Strava FTP into history, effective the date Strava first showed it. Returns
    the accepted entry, or None if nothing is pending."""
    p = get_pending(conn, athlete_id)
    if not p:
        return None
    add_entry(conn, p["seen_date"], p["ftp"], source="strava", created_at=p["seen_date"],
              athlete_id=athlete_id)
    clear_pending(conn, athlete_id)
    return {"effective_date": p["seen_date"], "ftp": p["ftp"], "source": "strava"}
