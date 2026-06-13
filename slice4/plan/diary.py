"""Diary-driven adjustment — the classifier (Slice 4.5, step 1).

The athlete talks to the coach in a normal check-in. This module reads each message and
decides whether anything in it should bend the PLAN — and if so, what INPUT it changes.

THE BOUNDARY (same as everywhere): the model classifies and extracts INPUTS — dates, hours,
durations, flags. It NEVER emits load numbers (TSS/CTL/ramp). There is nowhere in the schema
to put one. Code recomputes the plan from those inputs (step 2); this module only reads.

Taxonomy (closed enum), in order of consequence:
  hard_time_loss      illness / injury / work / travel that COSTS training time
                      -> an unavailable period (start..end)
  hard_capacity_change an ongoing limiter ("knee needs easy weeks")
                      -> hold intensity down / extend recovery for a duration
  hard_capacity_up    a temporary OPPORTUNITY ("family away, 12h free this week")
                      -> a transient per-week availability bump (the GUARDRAILS still bind how
                         much of it is usable — this only relaxes the time budget, nothing else)
  soft                how they feel (tired/flat/sore/great) — informs the coach, never moves a
                      number. Readiness/enthusiasm is SOFT: "I feel great, full gas" cannot
                      unlock load after a layoff.
  ambiguous           plan-relevant but underspecified / low-confidence -> ASK, never act.
                      Carries a clarifying_question.
  none                not plan-relevant (pleasantries, questions) -> ignored.

RE-ENTRY after illness/injury is NOT a formula (a flu, a stomach bug, a hamstring, a
concussion all return differently). It is elicited HERE in conversation and expressed as
inputs: the out-period dates, plus optional re-entry flags (intensity_capped, reduced_hours
for duration_weeks). The deterministic engine recomputes within that envelope; conversation
can only TIGHTEN the standing guardrails, never loosen them.
"""
import datetime
import re
from enum import Enum

from pydantic import BaseModel, Field


class AdjustmentKind(str, Enum):
    hard_time_loss = "hard_time_loss"
    hard_capacity_change = "hard_capacity_change"
    hard_capacity_up = "hard_capacity_up"
    soft = "soft"
    ambiguous = "ambiguous"
    none = "none"


HARD_KINDS = (AdjustmentKind.hard_time_loss, AdjustmentKind.hard_capacity_change,
              AdjustmentKind.hard_capacity_up)


class DiaryItem(BaseModel):
    """One plan-relevant reading of the athlete's message. INPUTS only — no load numbers."""
    kind: AdjustmentKind
    summary: str = Field(description="One short sentence: what the athlete reported and the "
                                     "input it implies. Their meaning, not training advice, "
                                     "never a number they did not say.")
    quote: str = Field(description="The athlete's own words supporting this reading, copied "
                                   "VERBATIM (a contiguous excerpt of the message).")
    confidence: float = Field(description="0..1 confidence in this classification.")
    # --- extracted INPUTS (only those relevant to the kind; null otherwise) ---
    start_date: str | None = Field(default=None, description="ISO date. Out-period start "
                                    "(time-loss) or the affected week's start (capacity-up).")
    end_date: str | None = Field(default=None, description="ISO date. Out-period / window end.")
    available_hours: float | None = Field(default=None, description="capacity-up: hours the "
                                          "athlete says they have that window (an input, not a plan).")
    duration_weeks: float | None = Field(default=None, description="capacity-change / re-entry: "
                                         "how many weeks the constraint or re-entry applies.")
    intensity_capped: bool | None = Field(default=None, description="capacity-change / re-entry: "
                                          "hold intensity down (easy/aerobic only) for the window.")
    reduced_hours: float | None = Field(default=None, description="re-entry: reduced weekly hours "
                                        "during the return window, if the athlete indicated easing back.")
    severity: str | None = Field(default=None, description="illness/injury severity if stated or "
                                 "clearly implied: 'mild' | 'moderate' | 'severe'. Informs how "
                                 "conservative re-entry is; never invent it.")
    reason: str | None = Field(default=None, description="Short free text: 'flu', 'work travel', "
                               "'family away', 'knee'.")
    clarifying_question: str | None = Field(default=None, description="REQUIRED when kind is "
                                            "'ambiguous': the one question to ask the athlete.")


class DiaryReading(BaseModel):
    items: list[DiaryItem]


# --------------------------------------------------------------------------- #
# Validation — the structural gate (pure). A proposal that fails here is dropped
# to 'ambiguous' or rejected; nothing the model emits is trusted blind.
# --------------------------------------------------------------------------- #
def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def _valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def validate_items(items, message):
    """Return (accepted, rejected) with reasons. Pure.

    Gates: verbatim-quote fabrication check; well-formed + ordered dates; confidence in range;
    ambiguous must carry a question; hard kinds must carry the minimum input they map to.
    'soft'/'none' need no inputs. Nothing is applied here — these are PROPOSALS."""
    msg_norm = _norm(message)
    accepted, rejected = [], []
    for n in items:
        if n.kind == AdjustmentKind.none:
            continue                                       # not plan-relevant; ignore silently
        # 1. fabrication gate — the justifying quote must be the athlete's actual words
        if not n.quote or _norm(n.quote) not in msg_norm:
            rejected.append((n, "quote_not_verbatim"))
            continue
        # 2. confidence sane
        if not (0.0 <= n.confidence <= 1.0):
            rejected.append((n, "bad_confidence"))
            continue
        # 3. dates well-formed and ordered when present (future dates are allowed — that's the
        #    whole point of a capacity-up opportunity; we do NOT clamp to a lookback window)
        if n.start_date is not None and not _valid_date(n.start_date):
            rejected.append((n, "bad_start_date"))
            continue
        if n.end_date is not None and not _valid_date(n.end_date):
            rejected.append((n, "bad_end_date"))
            continue
        if (n.start_date and n.end_date
                and datetime.date.fromisoformat(n.end_date) < datetime.date.fromisoformat(n.start_date)):
            rejected.append((n, "end_before_start"))
            continue
        # 4. ambiguous must ask
        if n.kind == AdjustmentKind.ambiguous and not (n.clarifying_question or "").strip():
            rejected.append((n, "ambiguous_without_question"))
            continue
        # 5. hard kinds must carry the minimum input they map to (else they can't recompute)
        if n.kind == AdjustmentKind.hard_time_loss and not (n.start_date and n.end_date):
            rejected.append((n, "time_loss_without_dates"))
            continue
        if n.kind == AdjustmentKind.hard_capacity_up and not (n.available_hours or n.start_date):
            rejected.append((n, "capacity_up_without_window"))
            continue
        accepted.append(n)
    return accepted, rejected


# --------------------------------------------------------------------------- #
# Context we hand the model so relative dates ("last Tuesday", "this week") resolve
# deterministically against the athlete's actual plan, not the model's guess.
# --------------------------------------------------------------------------- #
def _context_block(as_of, plan_weeks, weekly_hours, back_days=14, fwd_days=28):
    anchor = datetime.date.fromisoformat(as_of)
    cal = []
    for i in range(back_days, -fwd_days - 1, -1):
        d = anchor - datetime.timedelta(days=i)
        tag = " (today / check-in day)" if i == 0 else ""
        cal.append(f"  {d.strftime('%A')} = {d.isoformat()}{tag}")
    weeks = "\n".join(f"  wk{w['week']} starts {w['week_start']} ({w['block']})"
                      for w in (plan_weeks or [])[:12]) or "  (no plan weeks)"
    return (f"Today (check-in date): {as_of}\n"
            f"Athlete's standing weekly hours budget: {weekly_hours}\n"
            f"Calendar (use ONLY this to resolve day references):\n" + "\n".join(cal) +
            f"\n\nUpcoming plan weeks (for 'this week' / 'next week'):\n{weeks}")


CLASSIFY_SYSTEM = """You read an athlete's coaching check-in and decide whether anything in it \
should change their TRAINING PLAN, and if so, what INPUT it changes.

You output classifications and extracted inputs ONLY. You NEVER output training load: no TSS, \
no CTL, no ramp, no week-by-week numbers. There is nowhere to put them. Code computes the plan \
from the inputs you extract.

Classify each distinct plan-relevant statement into exactly one kind:
- hard_time_loss: illness / injury / work / travel that costs training days. Extract start_date \
and end_date of the time out (resolve from the calendar). Extract severity and reason if stated.
- hard_capacity_change: an ongoing limiter that should hold training down for a while ("knee \
needs easy weeks"). Set intensity_capped and duration_weeks; reason.
- hard_capacity_up: a TEMPORARY opportunity to do more ("family's away, I have 12 hours this \
week"). Extract available_hours and the affected week (start_date). Do NOT promise the athlete \
all of it — the plan's safety guardrails decide how much is usable; you only note the opening.
- soft: how they feel — tired, flat, sore, motivated, "I feel great". Informational only. \
Readiness and enthusiasm are ALWAYS soft: feeling great after time off does NOT justify more \
load. No dates/hours needed.
- ambiguous: plan-relevant but underspecified or you are not confident (illness with no idea \
how long, an injury you can't gauge, a vague "might travel"). Put your single best clarifying \
question in clarifying_question. Prefer ambiguous over guessing a hard change.
- none: pleasantries, questions, anything not about the plan.

Rules:
- Be conservative. When torn between soft and a hard change, choose ambiguous and ask.
- For illness/injury, if the athlete did not say how long they'll be out or how bad it is, do \
NOT invent it — classify ambiguous and ask. Re-entry caution is decided in conversation, not \
guessed.
- Every item's `quote` must be copied verbatim from the message.
- One item per distinct statement; skip pleasantries. A message may yield several items, one, \
or none."""


# --------------------------------------------------------------------------- #
# Soft-signal advisory layer (Slice 4.5, step 3) — STRICTLY non-binding.
# Recurring subjective themes across check-ins are surfaced so the coach reliably
# notices them and the athlete sees them. This NEVER changes a plan number: there is
# no recompute path here, only an observation. Soft informs; it never overrides.
# --------------------------------------------------------------------------- #
THEME_LABEL = {
    "fatigue": "fatigue", "soreness_pain": "soreness/pain", "sleep": "sleep",
    "stress": "stress", "illness": "illness", "feel": "how the legs feel",
    "motivation": "motivation", "time_constraint": "time pressure", "life_event": "life events",
}
# Categories worth flagging when they recur (the wellness signals that blunt how training lands).
# 'time_constraint'/'life_event' recur for logistics reasons and aren't wellness themes; excluded.
THEME_CATEGORIES = ("fatigue", "soreness_pain", "sleep", "stress", "illness", "feel", "motivation")


def recurring_themes(rows, min_checkins=3):
    """Pure. rows = iterable of (checkin_id, category, quote). Returns themes (a wellness category
    mentioned across >= min_checkins DISTINCT check-ins), most-recurring first. No dates/plan —
    just 'this keeps coming up'. The caller hands these to the coach as soft context."""
    by_cat = {}
    for checkin_id, category, quote in rows:
        if category not in THEME_CATEGORIES:
            continue
        d = by_cat.setdefault(category, {"checkins": set(), "quotes": []})
        d["checkins"].add(checkin_id)
        if quote and quote not in d["quotes"]:
            d["quotes"].append(quote)
    themes = [{"category": c, "label": THEME_LABEL.get(c, c), "checkins": len(v["checkins"]),
               "quotes": v["quotes"][:4]}
              for c, v in by_cat.items() if len(v["checkins"]) >= min_checkins]
    return sorted(themes, key=lambda t: -t["checkins"])


def advisory_text(themes):
    """One compact, NEUTRAL line per recurring theme for the coach's context. Observational —
    'keeps coming up', not a diagnosis or an instruction to change the plan."""
    if not themes:
        return None
    return "\n".join(f"- {t['label']}: raised in {t['checkins']} recent check-ins "
                     f"(e.g. \"{t['quotes'][0]}\")" for t in themes if t["quotes"])


def read_diary(message, as_of, plan_weeks, weekly_hours, client, model, max_tokens=700):
    """Classify a check-in message into plan-adjustment PROPOSALS, then validate.
    Returns (accepted, rejected). Pure w.r.t. the plan — nothing is applied. The caller passes
    the coach's Anthropic client + model id (the id lives once in coach config, not here)."""
    ctx = _context_block(as_of, plan_weeks, weekly_hours)
    response = client.messages.parse(
        model=model, max_tokens=max_tokens, system=CLASSIFY_SYSTEM,
        messages=[{"role": "user",
                   "content": f"{ctx}\n\nAthlete's check-in message:\n\"\"\"\n{message}\n\"\"\""}],
        output_format=DiaryReading,
    )
    result = response.parsed_output
    items = result.items if result else []
    return validate_items(items, message)
