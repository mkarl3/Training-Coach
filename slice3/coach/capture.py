"""Subjective-capture store (Slice 3, step 2).

Takes what the athlete says in a check-in and stores it as DATED, STRUCTURED notes.

THE CAPTURE BOUNDARY (non-negotiable, enforced structurally):
  - The model records WHAT THE ATHLETE SAID — it never turns a statement into a metric,
    never overrides a computed value, never infers a number the athlete didn't give.
  - Structural enforcement, in order of strength:
      1. The note schema has NO numeric fields. There is nowhere to put an invented
         TSS/TSB/CTL adjustment. Category is a closed enum; everything else is text.
      2. Every note must carry a `quote` that is a VERBATIM substring of the athlete's
         message (whitespace/case-normalized). A note whose quote isn't in the input is
         fabricated and is rejected by the validator, not stored.
      3. Note dates must fall inside [checkin_date - lookback, checkin_date]. The model
         resolves "Saturday" against a calendar we hand it; the validator rejects any
         date outside the window. No future notes, no drift.
  - The system prompt restates the rule, but the prompt is the SECOND line of defense.
"""
import datetime
import re
import sqlite3
from enum import Enum

from pydantic import BaseModel, Field

from .config import DEFAULT

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkin (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,            -- the check-in's anchor date (ISO)
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subjective_note (
    id          INTEGER PRIMARY KEY,
    checkin_id  INTEGER NOT NULL REFERENCES checkin(id),
    date        TEXT NOT NULL,            -- the day the note is ABOUT (keys onto daily timeline)
    category    TEXT NOT NULL,            -- closed enum, see NoteCategory
    note        TEXT NOT NULL,            -- short gist, the athlete's meaning
    quote       TEXT NOT NULL,            -- verbatim words from the athlete (validated)
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_date ON subjective_note(date);
"""


class NoteCategory(str, Enum):
    sleep = "sleep"
    stress = "stress"
    fatigue = "fatigue"
    soreness_pain = "soreness_pain"
    illness = "illness"
    motivation = "motivation"
    time_constraint = "time_constraint"
    feel = "feel"                       # how the legs/body felt on the bike
    life_event = "life_event"
    other = "other"


class SubjectiveNote(BaseModel):
    """One dated note. NO numeric fields — there is nowhere to put an invented metric."""
    date: str = Field(description="ISO date (YYYY-MM-DD) the statement is ABOUT, resolved "
                                  "from the provided calendar. Use the check-in date if the "
                                  "athlete gave no day.")
    category: NoteCategory
    note: str = Field(description="One short sentence capturing what the athlete reported. "
                                  "Their meaning, not your interpretation. Never a number "
                                  "they didn't say, never training advice.")
    quote: str = Field(description="The athlete's own words supporting this note, copied "
                                   "VERBATIM from the message (a contiguous excerpt).")


class CaptureResult(BaseModel):
    notes: list[SubjectiveNote]


# --------------------------------------------------------------------------- #
# Validation — the structural gate. Runs on EVERY extraction before storage.
# --------------------------------------------------------------------------- #
def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def validate_notes(notes, message, checkin_date, lookback_days=None):
    """Return (accepted, rejected) — rejected carries the reason. Pure function."""
    lookback = lookback_days or DEFAULT.capture_lookback_days
    anchor = datetime.date.fromisoformat(checkin_date)
    msg_norm = _norm(message)
    accepted, rejected = [], []
    for n in notes:
        # 2. quote must be verbatim (fabrication gate)
        if not n.quote or _norm(n.quote) not in msg_norm:
            rejected.append((n, "quote_not_verbatim"))
            continue
        # 3. date inside the window (no future, no drift)
        try:
            d = datetime.date.fromisoformat(n.date)
        except ValueError:
            rejected.append((n, "bad_date"))
            continue
        if d > anchor or (anchor - d).days > lookback:
            rejected.append((n, "date_out_of_window"))
            continue
        accepted.append(n)
    return accepted, rejected


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _calendar_block(checkin_date, lookback_days):
    """The calendar we hand the model so day-names resolve deterministically."""
    anchor = datetime.date.fromisoformat(checkin_date)
    lines = []
    for i in range(lookback_days, -1, -1):
        d = anchor - datetime.timedelta(days=i)
        tag = " (check-in day / today)" if i == 0 else ""
        lines.append(f"  {d.strftime('%A')} = {d.isoformat()}{tag}")
    return "\n".join(lines)


EXTRACT_SYSTEM = """You record an athlete's subjective check-in statements as dated notes.

Rules (absolute):
- Record only what the athlete actually said. Do not interpret, diagnose, or advise.
- NEVER produce a number the athlete did not say. If they said "slept badly", the note is
  "reported sleeping badly" — not hours, not a score, not a metric adjustment.
- Each note's `quote` must be copied verbatim, character-for-character, from the message.
- Resolve day references ("Saturday", "yesterday") to ISO dates USING ONLY the calendar
  provided. If no day is given, use the check-in date.
- One note per distinct statement; skip pleasantries and questions."""


def extract_notes(message, checkin_date, client=None, cfg=DEFAULT):
    """Run the LLM extraction, then the structural validation gate.
    Returns (accepted, rejected). The model's output NEVER reaches storage unvalidated."""
    import anthropic
    client = client or anthropic.Anthropic()
    cal = _calendar_block(checkin_date, cfg.capture_lookback_days)
    response = client.messages.parse(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=EXTRACT_SYSTEM,
        messages=[{
            "role": "user",
            "content": (f"Check-in date: {checkin_date}\nCalendar:\n{cal}\n\n"
                        f"Athlete's check-in message:\n\"\"\"\n{message}\n\"\"\""),
        }],
        output_format=CaptureResult,
    )
    result = response.parsed_output
    notes = result.notes if result else []
    return validate_notes(notes, message, checkin_date, cfg.capture_lookback_days)


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def ensure_schema(conn):
    conn.executescript(SCHEMA)


def store_checkin(conn, checkin_date, notes, created_at):
    """Persist a check-in + its validated notes. Returns checkin_id."""
    ensure_schema(conn)
    cur = conn.execute("INSERT INTO checkin (date, created_at) VALUES (?, ?)",
                       (checkin_date, created_at))
    cid = cur.lastrowid
    conn.executemany(
        "INSERT INTO subjective_note (checkin_id, date, category, note, quote, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(cid, n.date, n.category.value, n.note, n.quote, created_at) for n in notes])
    conn.commit()
    return cid


def notes_for_window(conn, start, end):
    """Dated notes inside [start, end] — how the engine corroborates findings later."""
    ensure_schema(conn)
    return list(conn.execute(
        "SELECT date, category, note, quote FROM subjective_note "
        "WHERE date BETWEEN ? AND ? ORDER BY date", (start, end)))
