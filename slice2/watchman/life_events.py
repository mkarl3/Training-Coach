"""Life-event findings modifier (intake data layer).

A pure pre-pass applied ONCE, right after detectors.run_all(m), returning a NEW findings list.
It explains and quiets findings that overlap the historical life events an athlete tagged at
intake (injury/illness/travel/...). It adds NO metric and NO detector; select.py is untouched.

Why confirmed -> watch is enough: select.py rule 3 already collapses watch-tier into the rollup
instead of a red alert, so an explained gap still shows — it just stops alarming.
"""
import sqlite3

# Categories + their findings effect. detector_effect is decided at write time from category,
# then stored explicitly so the consumer (apply_life_events) stays dumb. Athlete override wins.
LIFE_EVENT_CATEGORIES = ("injury", "illness", "life", "travel", "equipment", "other")
LIFE_EVENT_EFFECTS = ("annotate_only", "downgrade_severity")
_DEFAULT_EFFECT = {"injury": "downgrade_severity", "illness": "downgrade_severity"}


def default_effect_for(category):
    return _DEFAULT_EFFECT.get(category, "annotate_only")


# --------------------------------------------------------------------------- #
# CRUD — write/read path for intake. Operates on the season-layer DB connection (the same one
# load_life_events reads); the life_event table is created by plan_store.init at startup.
# --------------------------------------------------------------------------- #
def add_life_event(conn, start_date, category, created_at, end_date=None, note=None,
                   detector_effect=None, athlete_id=1):
    """Persist a tagged life event. detector_effect defaults from category, stored explicitly;
    an explicit override wins. Raises ValueError on a bad category/effect."""
    if category not in LIFE_EVENT_CATEGORIES:
        raise ValueError(f"category must be one of {LIFE_EVENT_CATEGORIES}")
    effect = detector_effect or default_effect_for(category)
    if effect not in LIFE_EVENT_EFFECTS:
        raise ValueError(f"detector_effect must be one of {LIFE_EVENT_EFFECTS}")
    cur = conn.execute(
        "INSERT INTO life_event (athlete_id, start_date, end_date, category, note, "
        "detector_effect, created_at) VALUES (?,?,?,?,?,?,?)",
        (athlete_id, start_date, end_date, category, note, effect, created_at))
    conn.commit()
    return cur.lastrowid


def list_life_events(conn, athlete_id=1):
    """Full rows for the CRUD/API surface. Graceful [] if the table doesn't exist yet."""
    try:
        rows = conn.execute(
            "SELECT id, start_date, end_date, category, note, detector_effect FROM life_event "
            "WHERE athlete_id=? ORDER BY start_date", (athlete_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(zip(("id", "start_date", "end_date", "category", "note", "detector_effect"), r))
            for r in rows]


def delete_life_event(conn, event_id, athlete_id=1):
    conn.execute("DELETE FROM life_event WHERE id=? AND athlete_id=?", (event_id, athlete_id))
    conn.commit()


def load_life_events(conn, athlete_id=1):
    """Minimal rows for the findings pre-pass. Graceful: [] if the table doesn't exist yet."""
    try:
        rows = conn.execute(
            "SELECT start_date, end_date, category, detector_effect FROM life_event "
            "WHERE athlete_id=? ORDER BY start_date", (athlete_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"start_date": s, "end_date": e, "category": c, "detector_effect": d}
            for (s, e, c, d) in rows]


def _finding_span(f):
    """Date span of a finding: window_start/window_end (tripwires) or zone_start/zone_end
    (trend annotations); single-date if only a start exists."""
    start = f.get("window_start") or f.get("zone_start")
    end = f.get("window_end") or f.get("zone_end") or start
    return start, end


def _overlaps(f_start, f_end, e_start, e_end):
    """Inclusive overlap; ISO strings compare lexically; a NULL event end means ongoing."""
    if f_start is None:
        return False
    if e_end is None:                          # event is open-ended / ongoing from e_start
        return f_end >= e_start
    return f_start <= e_end and e_start <= f_end


def apply_life_events(findings, life_events):
    """Return a NEW findings list, modified per the frozen semantics:
      - On any overlap: append data_flag 'explained:<category>' (deduped).
      - On an overlap whose event is 'downgrade_severity' AND the finding is 'confirmed':
        set severity = 'watch'. Trend-family findings are flagged but never downgraded.
      - Effects compose (any one downgrade overlap is enough; every overlap adds its flag).
      - Never deletes, never invents, never touches watch/trend severities beyond the flag.
    With no life events, returns the input unchanged (byte-identical, no copy)."""
    if not life_events:
        return findings
    out = []
    for f in findings:
        f_start, f_end = _finding_span(f)
        flags = list(f["data_flags"])
        severity = f["severity"]
        for ev in life_events:
            if not _overlaps(f_start, f_end, ev["start_date"], ev["end_date"]):
                continue
            flag = f"explained:{ev['category']}"
            if flag not in flags:
                flags.append(flag)
            if (ev["detector_effect"] == "downgrade_severity"
                    and severity == "confirmed"
                    and f.get("detector_family") != "trend"):
                severity = "watch"
        nf = dict(f)
        nf["data_flags"] = flags
        nf["severity"] = severity
        out.append(nf)
    return out
