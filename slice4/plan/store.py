"""Season-input persistence (Slice 4, step 1). CRUD over season / goal_event /
unavailable_period. Athlete-scoped. The generator takes plain dicts, so it never touches
this — this is just where the entry UI/API reads and writes.

Slice 4.5 adds transient plan_modifier rows (diary-driven availability / intensity-cap windows)
and a plan_adjustment audit trail with undo."""
import json
import os
import sqlite3

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
EVENT_TYPES = ("road_race_hilly", "road_race_flat", "time_trial", "gran_fondo",
               "criterium", "climbing_gc", "mixed")
# No-event fallback direction (intake): the generator's existing emphasis classes. Validated in
# app, not by a column CHECK (avoids the SQLite ALTER+CHECK edge case).
GENERAL_GOALS = ("durability", "sustained_threshold", "anaerobic", "balanced")


def _validate_general_goal(g):
    if g is not None and g not in GENERAL_GOALS:
        raise ValueError(f"general_goal must be one of {GENERAL_GOALS} or None")


def init(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    _migrate(conn)
    return conn


def _migrate(conn):
    """Idempotent column adds for DBs created before a column existed (CREATE IF NOT EXISTS
    won't alter an existing table). JSON-free, additive, safe to run every startup."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(season)")]
    if "general_goal" not in cols:
        conn.execute("ALTER TABLE season ADD COLUMN general_goal TEXT")
    conn.commit()


def connect(db_path):
    return init(sqlite3.connect(db_path, check_same_thread=False))


# --- seasons ---
def create_season(conn, name, start_date, weekly_hours_budget, created_at, athlete_id=1,
                  general_goal=None):
    _validate_general_goal(general_goal)
    conn.execute("UPDATE season SET is_active=0 WHERE athlete_id=?", (athlete_id,))  # one active
    cur = conn.execute(
        "INSERT INTO season (athlete_id, name, start_date, weekly_hours_budget, is_active, "
        "created_at, general_goal) VALUES (?,?,?,?,1,?,?)",
        (athlete_id, name, start_date, weekly_hours_budget, created_at, general_goal))
    conn.commit()
    return cur.lastrowid


def active_season(conn, athlete_id=1):
    r = conn.execute("SELECT id, name, start_date, weekly_hours_budget, general_goal FROM season "
                     "WHERE athlete_id=? AND is_active=1 ORDER BY id DESC LIMIT 1",
                     (athlete_id,)).fetchone()
    return dict(zip(("id", "name", "start_date", "weekly_hours_budget", "general_goal"), r)) if r else None


def update_season(conn, season_id, **fields):
    allowed = {"name", "start_date", "weekly_hours_budget", "general_goal"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "general_goal" in sets:
        _validate_general_goal(sets["general_goal"])
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
        (season_id, athlete_id, start_date, end_date, reason, note, created_at))
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


# --- transient plan modifiers (Slice 4.5) ---
#   'readiness' stores its 0..1 ease FACTOR in the `hours` column (tighten-only; <=1 always).
def add_modifier(conn, season_id, kind, start_date, end_date, created_at,
                 hours=None, reason=None, athlete_id=1):
    if kind not in ("availability", "intensity_cap", "readiness", "block_hold"):
        raise ValueError("kind must be availability/intensity_cap/readiness/block_hold")
    cur = conn.execute(
        "INSERT INTO plan_modifier (season_id, athlete_id, kind, start_date, end_date, hours, "
        "reason, active, created_at) VALUES (?,?,?,?,?,?,?,1,?)",
        (season_id, athlete_id, kind, start_date, end_date, hours, reason, created_at))
    conn.commit()
    return cur.lastrowid


def deactivate_modifier(conn, modifier_id):
    conn.execute("UPDATE plan_modifier SET active=0 WHERE id=?", (modifier_id,))
    conn.commit()


def active_modifiers(conn, season_id):
    """The generator's transient-input lists, ACTIVE only. Shape matches generate_plan()."""
    rows = conn.execute(
        "SELECT kind, start_date, end_date, hours, reason FROM plan_modifier "
        "WHERE season_id=? AND active=1 ORDER BY start_date", (season_id,))
    availability, intensity_caps = [], []
    for kind, s, e, hours, reason in rows:
        if kind == "availability":
            availability.append({"start_date": s, "end_date": e, "hours": hours, "reason": reason})
        elif kind == "intensity_cap":
            intensity_caps.append({"start_date": s, "end_date": e, "reason": reason})
    return availability, intensity_caps


def active_readiness(conn, season_id):
    """ACTIVE subjective-readiness ease windows for the generator: {start,end,factor,reason}."""
    rows = conn.execute(
        "SELECT start_date, end_date, hours, reason FROM plan_modifier "
        "WHERE season_id=? AND active=1 AND kind='readiness' ORDER BY start_date", (season_id,))
    return [{"start_date": s, "end_date": e, "factor": h, "reason": r} for s, e, h, r in rows]


def active_block_holds(conn, season_id):
    """ACTIVE phase-progression holds for the generator: {block_name: total_extra_weeks}.
    Stored as kind='block_hold' (block in `reason`, weeks in `hours`)."""
    rows = conn.execute(
        "SELECT reason, hours FROM plan_modifier "
        "WHERE season_id=? AND active=1 AND kind='block_hold'", (season_id,))
    out = {}
    for block, weeks in rows:
        out[block] = out.get(block, 0) + int(weeks or 0)
    return out


# --- adjustment audit trail + undo (Slice 4.5) ---
def log_adjustment(conn, season_id, kind, summary, applied, undo_ref, created_at, athlete_id=1):
    cur = conn.execute(
        "INSERT INTO plan_adjustment (season_id, athlete_id, kind, summary, applied, undo_ref, "
        "active, created_at) VALUES (?,?,?,?,?,?,1,?)",
        (season_id, athlete_id, kind, summary, json.dumps(applied), json.dumps(undo_ref), created_at))
    conn.commit()
    return cur.lastrowid


def adjustments_for(conn, season_id, active_only=False):
    q = ("SELECT id, kind, summary, applied, undo_ref, active, created_at FROM plan_adjustment "
         "WHERE season_id=?" + (" AND active=1" if active_only else "") + " ORDER BY id DESC")
    rows = conn.execute(q, (season_id,))
    return [{"id": i, "kind": k, "summary": s, "applied": json.loads(a), "undo_ref": json.loads(u),
             "active": bool(ac), "created_at": c} for i, k, s, a, u, ac, c in rows]


def undo_adjustment(conn, adjustment_id):
    """Reverse an applied adjustment: deactivate it and remove/deactivate the row it created.
    Returns the adjustment dict, or None if not found / already undone."""
    row = conn.execute("SELECT undo_ref, active FROM plan_adjustment WHERE id=?",
                       (adjustment_id,)).fetchone()
    if row is None or not row[1]:
        return None
    ref = json.loads(row[0])
    if ref.get("table") == "unavailable_period":
        conn.execute("DELETE FROM unavailable_period WHERE id=?", (ref["id"],))
    elif ref.get("table") == "plan_modifier":
        conn.execute("UPDATE plan_modifier SET active=0 WHERE id=?", (ref["id"],))
    conn.execute("UPDATE plan_adjustment SET active=0 WHERE id=?", (adjustment_id,))
    conn.commit()
    return adjustment_id

# NOTE: the life_event TABLE is created here via schema.sql (plan_store.init), but its CRUD lives
# in slice2/watchman/life_events.py next to load/apply_life_events for cohesion (handoff 2).
