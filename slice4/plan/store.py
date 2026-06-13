"""Season-input persistence (Slice 4, step 1). CRUD over season / goal_event /
unavailable_period. Athlete-scoped. The generator takes plain dicts, so it never touches
this — this is just where the entry UI/API reads and writes."""
import os
import sqlite3

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
EVENT_TYPES = ("road_race_hilly", "road_race_flat", "time_trial", "gran_fondo",
               "criterium", "climbing_gc", "mixed")


def init(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    return conn


def connect(db_path):
    return init(sqlite3.connect(db_path, check_same_thread=False))


# --- seasons ---
def create_season(conn, name, start_date, weekly_hours_budget, created_at, athlete_id=1):
    conn.execute("UPDATE season SET is_active=0 WHERE athlete_id=?", (athlete_id,))  # one active
    cur = conn.execute(
        "INSERT INTO season (athlete_id, name, start_date, weekly_hours_budget, is_active, "
        "created_at) VALUES (?,?,?,?,1,?)",
        (athlete_id, name, start_date, weekly_hours_budget, created_at))
    conn.commit()
    return cur.lastrowid


def active_season(conn, athlete_id=1):
    r = conn.execute("SELECT id, name, start_date, weekly_hours_budget FROM season "
                     "WHERE athlete_id=? AND is_active=1 ORDER BY id DESC LIMIT 1",
                     (athlete_id,)).fetchone()
    return dict(zip(("id", "name", "start_date", "weekly_hours_budget"), r)) if r else None


def update_season(conn, season_id, **fields):
    allowed = {"name", "start_date", "weekly_hours_budget"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if sets:
        conn.execute(f"UPDATE season SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                     (*sets.values(), season_id))
        conn.commit()


# --- events ---
def add_event(conn, season_id, name, event_date, priority, event_type, created_at,
              note=None, athlete_id=1):
    if priority not in ("A", "B", "C"):
        raise ValueError("priority must be A, B, or C")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {EVENT_TYPES}")
    cur = conn.execute(
        "INSERT INTO goal_event (season_id, athlete_id, name, event_date, priority, event_type, "
        "note, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (season_id, athlete_id, name, event_date, priority, event_type, note, created_at))
    conn.commit()
    return cur.lastrowid


def events_for(conn, season_id):
    rows = conn.execute(
        "SELECT id, name, event_date, priority, event_type, note FROM goal_event "
        "WHERE season_id=? ORDER BY event_date", (season_id,))
    return [dict(zip(("id", "name", "event_date", "priority", "event_type", "note"), r)) for r in rows]


def delete_event(conn, event_id):
    conn.execute("DELETE FROM goal_event WHERE id=?", (event_id,))
    conn.commit()


# --- unavailable periods ---
def add_unavailable(conn, season_id, start_date, end_date, created_at, reason=None,
                    note=None, athlete_id=1):
    cur = conn.execute(
        "INSERT INTO unavailable_period (season_id, athlete_id, start_date, end_date, reason, "
        "note, created_at) VALUES (?,?,?,?,?,?,?)",
        (season_id, athlete_id, start_date, end_date, reason, note))
    conn.commit()
    return cur.lastrowid


def unavailable_for(conn, season_id):
    rows = conn.execute(
        "SELECT id, start_date, end_date, reason, note FROM unavailable_period "
        "WHERE season_id=? ORDER BY start_date", (season_id,))
    return [dict(zip(("id", "start_date", "end_date", "reason", "note"), r)) for r in rows]


def delete_unavailable(conn, period_id):
    conn.execute("DELETE FROM unavailable_period WHERE id=?", (period_id,))
    conn.commit()
