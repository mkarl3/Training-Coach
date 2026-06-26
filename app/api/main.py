"""Unified Training Coach backend — composes the slices into one service.

Loads the Metrics facade + Slice-1 findings ONCE and serves:
  - the Slice-2 watchman selection  (/api/watchman, /api/meta)
  - the Slice-3 coach               (/api/coach/*)
The slices stay separate libraries; this is just the composition shell.
"""
import dataclasses
import datetime
import io
import os
import re
import sqlite3
import sys

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(APP_DIR)
for p in ("slice4", "slice3", "slice2", "slice1", "slice0"):
    sys.path.insert(0, os.path.join(ROOT, p))
sys.path.insert(0, ROOT)                                  # for the `sources` package (Strava ingest)

from wko_metrics import metrics, detectors, profile, AthleteProfile, DEFAULT_PROFILE  # noqa: E402
from wko_metrics import ftp_history                   # noqa: E402  (dated load-FTP history)
from watchman import (select, build_trend, DEFAULT_SELECTION, apply_life_events, load_life_events,  # noqa: E402
                      add_life_event, list_life_events, delete_life_event,
                      LIFE_EVENT_CATEGORIES, LIFE_EVENT_EFFECTS)
from wko_ingest import loader, validator               # noqa: E402
from coach import store, capture as coach_capture     # noqa: E402
from coach.orchestrator import Coach                   # noqa: E402
from coach.retrieval import MethodologyIndex           # noqa: E402
from plan import store as plan_store, generator as plan_gen, diary as plan_diary, review as plan_review  # noqa: E402
from plan import progression as plan_progression  # noqa: E402
from watchman import trend as wm_trend                 # noqa: E402  (projection helper for hold preview)

WKO_DB = os.environ.get("WKO_DB", os.path.join(ROOT, "slice0", "wko.db"))
EXPORTS_DIR = os.path.join(ROOT, "WKO5 Exports")
COACH_DB = os.path.join(ROOT, "slice3", "coach.db")
INDEX_DB = os.path.join(ROOT, "slice3", "methodology.db")

app = FastAPI(title="Watt Smith API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_S = {}


def _build_plan(conn, m, prof, as_of):
    """Generate the deterministic plan for the active season, or None if no season set."""
    season = plan_store.active_season(conn)
    if not season:
        return None, None
    events = plan_store.events_for(conn, season["id"])
    unavail = plan_store.unavailable_for(conn, season["id"])
    availability, intensity_caps = plan_store.active_modifiers(conn, season["id"])
    readiness = plan_store.active_readiness(conn, season["id"])
    holds = plan_store.active_block_holds(conn, season["id"])
    plan = plan_gen.generate_plan(m, prof, season, events, unavail, as_of,
                                  availability=availability, intensity_caps=intensity_caps,
                                  readiness=readiness, holds=holds,
                                  cal_today=datetime.date.today().isoformat())
    return season, plan


def _plan_summary(plan):
    """Compact text the coach EXPLAINS (it never writes these numbers)."""
    if not plan or "error" in plan:
        return None
    M = plan["meta"]
    lines = [f"A-race: {M['a_race']['name']} ({M['a_race']['type']}, emphasis "
             f"{M['a_race']['emphasis']}) on {M['a_race']['date']}.",
             f"{M['weeks']}-week plan from {M['plan_start']} (weeks start {M['week_starts_on']}); "
             f"blocks {M['block_weeks']}; distribution Rx: {M['distribution_rx']}.",
             f"CTL {M['anchor_ctl']} -> target {M['target_peak_ctl']} (floor {M['personal_floor']}); "
             f"peak achievable {M['peak_ctl_achieved']}; target_reached={M['target_reached']}; "
             f"masters={M['masters']}, ramp cap {M['ramp_cap']}/wk, budget {M['weekly_hours_budget']} h/wk.",
             (f"Ramp targets base {M['base_ramp']}/build {M['build_ramp']} CTL/wk, seeded from the "
              f"athlete's demonstrated sustainable ramp ({M['sustainable_ramp']}/wk)."
              if M['ramp_source'] == 'history' else
              f"Ramp targets base {M['base_ramp']}/build {M['build_ramp']} CTL/wk (method defaults — "
              f"history too thin to demonstrate a personal sustainable ramp)."),
             "50% rule: each week lists a single-ride TSS cap (no one ride above half the week's TSS)."]
    mg = M.get("monotony_guard")
    if mg:
        lines.append(
            f"Monotony guardrail: {'ACTIVE' if mg['prone'] else 'inactive'} — gray-IF-band fraction "
            f"{mg['gray_band_frac']} (cap {mg['gray_band_cap']}), TiZ concentration {mg['tiz_concentration']} "
            f"(cap {mg['tiz_concentration_cap']}). When active, training weeks enforce strict hard/easy "
            f"separation (easy capped at Z2, quality concentrated).")
    for w in plan["weeks"]:
        caps = ("  [" + "; ".join(w["constraints_fired"]) + "]") if w["constraints_fired"] else ""
        ft = " field-test" if w["field_test"] else ""
        act = f", actual {w['actual_tss']} TSS" if w["actual_tss"] is not None else ""
        lines.append(f"  wk{w['week']} {w['week_start']} {w['block']} ({w['focus']}){ft}"
                     f"{' (recovery)' if w['is_recovery'] else ''}: CTL {w['ctl_start']}->"
                     f"{w['ctl_target']}, {w['weekly_tss_target']} TSS (single-ride cap "
                     f"{w['single_ride_tss_cap']}) / {w['est_hours']}h{act}{caps}")
    return "\n".join(lines)


def _has_training_data():
    """True only when wko.db exists AND holds actual (non-projected) daily rows. Cold start
    (no file / empty DB) is tolerated — the app degrades to an 'awaiting intake' state."""
    if not os.path.exists(WKO_DB):
        return False
    try:
        c = sqlite3.connect(WKO_DB)
        n = c.execute("SELECT count(*) FROM daily WHERE is_projected=0").fetchone()[0]
        c.close()
        return n > 0
    except sqlite3.OperationalError:
        return False


def _load_training_data():
    """(Re)build the in-memory dashboard + coach from the current wko.db, using the loaded
    AthleteProfile for all athlete-relative constants. The coach.db connection (conversation
    history + the profile row) is opened once and reused across refreshes. Tolerant of a missing
    dataset: on cold start it degrades to an 'awaiting intake' state instead of crashing."""
    conn = _S.get("conn") or store.connect(COACH_DB)
    plan_store.init(conn)                             # ensure season tables exist in coach.db
    prof = _S.get("profile") or profile.load_profile(conn)

    if not _has_training_data():
        # awaiting intake — no metrics/findings/plan/coach yet; keep conn + profile so the intake
        # write paths (profile, season, life-event, upload) still work.
        _S.update(m=None, findings=[], as_of=None, status="awaiting", conn=conn, profile=prof,
                  season=plan_store.active_season(conn), plan=None, coach=None, date_min=None)
        _S.setdefault("pending", {})
        _S.setdefault("pending_seq", 0)
        return

    m = metrics.Metrics(sqlite3.connect(WKO_DB, check_same_thread=False), profile=prof)
    # life events (intake) explain/quiet overlapping findings BEFORE selection. `conn` is the
    # season-layer DB (coach.db) where plan_store.init created the life_event table.
    findings = apply_life_events(detectors.run_all(m), load_life_events(conn))
    as_of = m.daily.index.max().strftime("%Y-%m-%d")
    watch_now = select(findings, as_of, m)

    coach_state = dict(watch_now)
    coach_state.pop("trajectory", None)               # the coach reads findings, not series
    cutoff = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=365)).isoformat()
    ranked = detectors.action_rank(
        [f for f in findings if f["severity"] == "confirmed" and f["window_end"] >= cutoff])

    season, plan = _build_plan(conn, m, prof, as_of)
    _S.update(
        m=m, findings=findings, as_of=as_of, status=watch_now["status"], conn=conn, profile=prof,
        season=season, plan=plan,
        coach=Coach(conn, coach_state, ranked, MethodologyIndex(INDEX_DB), profile=prof,
                    plan_summary=_plan_summary(plan)),
        date_min=m.daily.index.min().strftime("%Y-%m-%d"),
    )
    _S.setdefault("pending", {})       # ephemeral diary proposals awaiting confirmation
    _S.setdefault("pending_seq", 0)
    _ensure_ftp_seed()                 # seed the dated load-FTP history on first run
    _refresh_advisories()              # seed recurring-theme context for the coach


def _ensure_ftp_seed():
    """First run: if there's no load-FTP history yet, seed one entry = the static config FTP,
    effective from the data start, so existing TSS is unchanged until the athlete adds dated values."""
    conn = _S.get("conn")
    if conn is None or _S.get("date_min") is None or ftp_history.list_entries(conn):
        return
    from sources import build_db
    ftp_history.add_entry(conn, _S["date_min"], build_db._config_ftp() or 200,
                          source="seed", created_at=_S["date_min"])


def _refresh_plan():
    """Recompute the plan after a season-input change and push it into the coach context."""
    season, plan = _build_plan(_S["conn"], _S["m"], _S["profile"], _S["as_of"])
    _S["season"], _S["plan"] = season, plan
    _S["coach"].plan_summary = _plan_summary(plan)
    return plan


def _compute_advisories(window_days=42):
    """Recurring subjective themes across recent check-ins (Slice 4.5 step 3) — soft context,
    never a plan change. Window is on real check-in time, not the data date."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=window_days)).isoformat()
    rows = coach_capture.notes_by_checkin_since(_S["conn"], cutoff)
    return plan_diary.recurring_themes(rows)


def _refresh_advisories():
    """Recompute themes and push the text into the coach context. Returns the structured themes."""
    themes = _compute_advisories()
    if _S.get("coach"):
        _S["coach"].soft_advisories = plan_diary.advisory_text(themes)
    return themes


@app.on_event("startup")
def _startup():
    _load_training_data()


# ---------------- intake status ----------------
def _require_loaded():
    """409 when there's no dataset (cold start) — for endpoints that need metrics/findings."""
    if _S.get("m") is None:
        raise HTTPException(409, "awaiting intake — no training data loaded yet")


def _months_of_history():
    if _S.get("m") is None or _S.get("date_min") is None or _S.get("as_of") is None:
        return 0.0
    span = (datetime.date.fromisoformat(_S["as_of"]) - datetime.date.fromisoformat(_S["date_min"])).days
    return round(span / 30.44, 1)


@app.get("/api/intake/status")
def intake_status():
    """Booleans + counts the frontend reads to choose onboarding vs the dashboard."""
    prof = _S.get("profile")
    has_data = _S.get("m") is not None
    months = _months_of_history()
    has_profile = bool(prof and prof.birth_year is not None)   # age/masters depend on birth_year
    season = plan_store.active_season(_S["conn"]) if _S.get("conn") else None
    has_goal = bool(season and (plan_store.events_for(_S["conn"], season["id"])
                                or season.get("general_goal")))
    return {
        "has_data": has_data,
        "months_of_history": months,
        "has_profile": has_profile,
        "has_season_or_goal": has_goal,
        "complete": bool(has_data and months >= 12 and has_profile),
    }


# ---------------- watchman ----------------
@app.get("/api/meta")
def meta():
    last = store.latest_conversation(_S["conn"]) if _S.get("conn") else None
    return {"date_min": _S["date_min"], "date_max": _S["as_of"],
            "default_as_of": _S["as_of"], "board_status": _S["status"],
            "latest_conversation_id": last[0] if last else None}


@app.get("/api/watchman")
def watchman(as_of: str = Query(...), window: int = Query(120, ge=14, le=400)):
    _require_loaded()
    if not (_S["date_min"] <= as_of <= _S["as_of"]):
        raise HTTPException(400, f"as_of must be in [{_S['date_min']}, {_S['as_of']}]")
    scfg = dataclasses.replace(DEFAULT_SELECTION, trajectory_window_days=window)
    return select(_S["findings"], as_of, _S["m"], scfg)


@app.get("/api/consistency")
def consistency(as_of: str = Query(None)):
    """Consistency Gauge reading (handoff brief): four-heart adherence buffer (gauge-owned) +
    the gap_unravel flag (detector-owned). Deterministic; the React component renders only."""
    _require_loaded()
    from watchman import consistency_gauge
    return consistency_gauge(_S["findings"], as_of or _S["as_of"], _S["m"])


@app.get("/api/trend")
def trend(as_of: str = Query(None)):
    """Long-range fitness-trend payload for the integrated dashboard: weekly CTL+TSS series, the
    demonstrated-safe ramp (for line colouring), and the capped, ranked, plain-language insights
    pinned to the timeline. Defaults to the latest data date."""
    _require_loaded()
    ao = as_of or _S["as_of"]
    if not (_S["date_min"] <= ao <= _S["as_of"]):
        raise HTTPException(400, f"as_of must be in [{_S['date_min']}, {_S['as_of']}]")
    return build_trend(_S["m"], _S["findings"], ao, plan=_S.get("plan"), status=_S.get("status"))


@app.get("/api/progression")
def progression(as_of: str = Query(None)):
    """Slice 5 — the deterministic phase-progression assessment (gate + verdict + contingency).
    Advises; never recomputes. Returns {state:'no_plan'} when there's no active plan."""
    _require_loaded()
    ao = as_of or _S["as_of"]
    return plan_progression.assess_progression(_S["m"], _S.get("plan"), ao, _S.get("profile"))


class HoldIn(BaseModel):
    block: str
    weeks: int = 1


@app.post("/api/progression/hold")
def progression_hold(body: HoldIn):
    """Apply a phase-progression HOLD: extend `block` by `weeks` (stolen from later base/build
    blocks — the honest cost) and recompute. Returns the diff. Undoable via the adjustment path."""
    _require_loaded()
    s = _S.get("season")
    if not s or not _S.get("plan"):
        raise HTTPException(400, "no active plan")
    if body.block not in {w["block"] for w in _S["plan"]["weeks"]}:
        raise HTTPException(400, f"unknown block {body.block!r}")
    weeks = max(1, min(2, body.weeks))
    edit = {"target": "block_hold", "block": body.block, "weeks": weeks}
    diff = plan_gen.diff_plans(_S["plan"], _candidate_plan(edit))
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    rid = plan_store.add_modifier(_S["conn"], s["id"], "block_hold", s["start_date"],
                                  s["start_date"], now, hours=weeks, reason=body.block)
    summary = f"Hold {body.block} +{weeks} wk"
    aid = plan_store.log_adjustment(_S["conn"], s["id"], "phase_hold", summary, edit,
                                    {"table": "plan_modifier", "id": rid}, now)
    _refresh_plan()
    return {"applied": summary, "adjustment_id": aid, "diff": diff, "plan": _S["plan"]}


@app.get("/api/progression/hold/preview")
def progression_hold_preview(block: str = Query(...), weeks: int = Query(1)):
    """Dry-run a phase-progression HOLD: return the diff + the eased forward projection WITHOUT
    applying anything. Lets the check-in show 'if eased' before the athlete commits to EASE IT."""
    _require_loaded()
    if not _S.get("season") or not _S.get("plan"):
        raise HTTPException(400, "no active plan")
    if block not in {w["block"] for w in _S["plan"]["weeks"]}:
        raise HTTPException(400, f"unknown block {block!r}")
    weeks = max(1, min(2, weeks))
    cand = _candidate_plan({"target": "block_hold", "block": block, "weeks": weeks})
    return {
        "block": block, "weeks": weeks,
        "diff": plan_gen.diff_plans(_S["plan"], cand),
        "projection_current": wm_trend._projection(_S["plan"]),
        "projection_eased": wm_trend._projection(cand),
    }


# ---------------- coach ----------------
class MessageIn(BaseModel):
    text: str
    conversation_id: int | None = None


@app.get("/api/coach/history")
def history(conversation_id: int):
    rows = store.history(_S["conn"], conversation_id)
    return {"messages": [{"role": r, "content": c, "at": t} for r, c, t in rows]}


class SeasonEdit(BaseModel):
    """Structured INPUT change the coach may infer from a chat message. The model emits this;
    code applies it and recomputes. The model never writes plan numbers — only inputs."""
    kind: str            # 'move_event' | 'set_hours' | 'add_unavailable' | 'none'
    event_name: str | None = None
    new_date: str | None = None
    weekly_hours: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    reason: str | None = None


_EDIT_SYS = ("Decide whether the athlete's message asks for a CONCRETE change to their season "
             "plan inputs. kinds: move_event (a race/event moved -> event_name + new_date "
             "YYYY-MM-DD), set_hours (weekly training hours changed -> weekly_hours), "
             "add_unavailable (a period they can't train -> start_date/end_date/reason), or "
             "none. Resolve relative dates against the events listed. Output 'none' for "
             "anything that isn't a concrete input change.")


def _try_season_edit(text, now):
    """Infer + APPLY a season-input change, then recompute. Returns a note or None.
    Boundary: the LLM picks the input edit; this code mutates inputs + re-runs the generator."""
    season = _S.get("season")
    if not season:
        return None
    events = plan_store.events_for(_S["conn"], season["id"])
    ctx = (f"Season events: {[{'name': e['name'], 'date': e['event_date']} for e in events]}. "
           f"Current weekly hours: {season['weekly_hours_budget']}. Message: {text}")
    try:
        edit = _S["coach"].client.messages.parse(
            model=_S["coach"].cfg.model, max_tokens=300,
            system=_EDIT_SYS, messages=[{"role": "user", "content": ctx}],
            output_format=SeasonEdit).parsed_output
    except Exception:
        return None
    if not edit or edit.kind == "none":
        return None
    if edit.kind == "move_event" and edit.new_date:
        match = next((e for e in events if not edit.event_name
                      or edit.event_name.lower() in e["name"].lower()), None)
        if not match:
            return None
        _S["conn"].execute("UPDATE goal_event SET event_date=? WHERE id=?",
                           (edit.new_date, match["id"]))
        _S["conn"].commit()
        note = f"moved '{match['name']}' to {edit.new_date}"
    elif edit.kind == "set_hours" and edit.weekly_hours:
        plan_store.update_season(_S["conn"], season["id"], weekly_hours_budget=edit.weekly_hours)
        note = f"set weekly hours to {edit.weekly_hours}"
    elif edit.kind == "add_unavailable" and edit.start_date and edit.end_date:
        plan_store.add_unavailable(_S["conn"], season["id"], edit.start_date, edit.end_date,
                                   now, reason=edit.reason)
        note = f"blocked {edit.start_date}..{edit.end_date} ({edit.reason or 'unavailable'})"
    else:
        return None
    _refresh_plan()                                   # deterministic recompute on new inputs
    return note


# --- diary-driven adjustment: PROPOSE -> (athlete confirms) -> apply + recompute (Slice 4.5) ---
def _week_start(d):
    return plan_gen._week_start(datetime.date.fromisoformat(d), _S["profile"].week_starts_on)


def _edit_from_item(it):
    """Map a classified hard diary item to a concrete INPUT edit (never load numbers). Returns a
    dict the confirm step applies, or None if it can't be mapped safely."""
    if it.kind.value == "hard_time_loss" and it.start_date and it.end_date:
        return {"target": "unavailable", "start_date": it.start_date, "end_date": it.end_date,
                "reason": it.reason or "illness/injury"}
    if it.kind.value == "hard_capacity_up" and (it.available_hours and it.start_date):
        ws = _week_start(it.start_date)
        return {"target": "availability", "start_date": ws.isoformat(),
                "end_date": (ws + datetime.timedelta(days=6)).isoformat(),
                "hours": it.available_hours, "reason": it.reason or "extra availability"}
    if it.kind.value == "hard_capacity_change":
        start = _week_start(it.start_date) if it.start_date else _week_start(_S["as_of"])
        wks = int(it.duration_weeks) if it.duration_weeks else 2
        return {"target": "intensity_cap", "start_date": start.isoformat(),
                "end_date": (start + datetime.timedelta(days=7 * max(wks, 1) - 1)).isoformat(),
                "reason": it.reason or "keep it easy"}
    # SOFT readiness — a reported feeling that can only EASE the coming days (decays ~10 days).
    if it.kind.value == "soft" and it.readiness in ("low", "moderate"):
        ws = _week_start(_S["as_of"])
        return {"target": "readiness", "start_date": ws.isoformat(),
                "end_date": (ws + datetime.timedelta(days=10)).isoformat(),
                "factor": 0.3 if it.readiness == "low" else 0.6,
                "reason": f"you said \"{it.quote}\""}
    return None


def _candidate_plan(edit):
    """Generate the plan that WOULD result from applying `edit`, without persisting anything."""
    s = _S["season"]
    events = plan_store.events_for(_S["conn"], s["id"])
    unavail = plan_store.unavailable_for(_S["conn"], s["id"])
    availability, intensity_caps = plan_store.active_modifiers(_S["conn"], s["id"])
    readiness = plan_store.active_readiness(_S["conn"], s["id"])
    holds = plan_store.active_block_holds(_S["conn"], s["id"])
    if edit["target"] == "unavailable":
        unavail = unavail + [edit]
    elif edit["target"] == "availability":
        availability = availability + [edit]
    elif edit["target"] == "intensity_cap":
        intensity_caps = intensity_caps + [edit]
    elif edit["target"] == "readiness":
        readiness = readiness + [edit]
    elif edit["target"] == "block_hold":
        holds = {**holds, edit["block"]: holds.get(edit["block"], 0) + edit["weeks"]}
    return plan_gen.generate_plan(_S["m"], _S["profile"], s, events, unavail, _S["as_of"],
                                  availability=availability, intensity_caps=intensity_caps,
                                  readiness=readiness, holds=holds,
                                  cal_today=datetime.date.today().isoformat())


def _propose(text):
    """Classify the message; build PENDING proposals (with diffs) for hard items, collect
    clarifying questions for ambiguous ones. Applies nothing. Returns (proposals, questions)."""
    s = _S.get("season")
    plan = _S.get("plan")
    if not s or not plan or "error" in plan:
        return [], []
    try:
        accepted, _ = plan_diary.read_diary(text, _S["as_of"], plan["weeks"],
                                            s["weekly_hours_budget"], _S["coach"].client,
                                            _S["coach"].cfg.model)
    except Exception:
        return [], []
    proposals, questions = [], []
    for it in accepted:
        if it.kind.value == "ambiguous":
            questions.append(it.clarifying_question)
            continue
        edit = _edit_from_item(it)
        if not edit:
            continue
        cand = _candidate_plan(edit)
        if "error" in cand:
            continue
        kind = "readiness" if edit["target"] == "readiness" else it.kind.value
        summary = ("Ease the next few days — you're feeling run-down" if kind == "readiness"
                   else it.summary)
        _S["pending_seq"] += 1
        pid = _S["pending_seq"]
        _S["pending"][pid] = {"kind": kind, "summary": summary, "edit": edit}
        proposals.append({"id": pid, "kind": kind, "summary": summary,
                          "quote": it.quote, "edit": edit,
                          "diff": plan_gen.diff_plans(plan, cand)})
    return proposals, questions


# a phase-hold becomes relevant when the athlete brings up advancing / holding / being ready.
_PROGRESS_INTENT = re.compile(
    r"\b(advanc\w*|ready|move (?:on|up|to)|next (?:block|phase)|progress\w*|graduat\w*|"
    r"hold\w*|not ready|stay (?:in|on|put)|extend\w*)\b", re.I)


def _hold_proposal(text):
    """When the athlete is talking about advancing/holding AND the live gate verdict is a HOLD,
    surface a tappable hold proposal: extend the current block by a week (the cost is stolen from a
    later block — the honest tradeoff). Routed through the SAME pending/confirm machinery as the
    diary proposals; applies nothing. Returns the proposal dict or None."""
    s, plan = _S.get("season"), _S.get("plan")
    if not s or not plan or "error" in plan or not _PROGRESS_INTENT.search(text or ""):
        return None
    prog = plan_progression.assess_progression(_S["m"], plan, _S["as_of"], _S.get("profile"))
    if prog.get("verdict") not in ("HOLD", "PROCEED_WITH_DEBT"):
        return None
    block = prog.get("block")
    if not block or block not in {w["block"] for w in plan["weeks"]}:
        return None
    edit = {"target": "block_hold", "block": block, "weeks": 1}
    cand = _candidate_plan(edit)
    if "error" in cand:
        return None
    _S["pending_seq"] += 1
    pid = _S["pending_seq"]
    summary = f"Hold {block} +1 wk"
    _S["pending"][pid] = {"kind": "phase_hold", "summary": summary, "edit": edit}
    return {"id": pid, "kind": "phase_hold", "summary": summary, "edit": edit,
            "diff": plan_gen.diff_plans(plan, cand)}


@app.post("/api/coach/message")
def message(body: MessageIn):
    _require_loaded()
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    cid = body.conversation_id or store.start_conversation(_S["conn"], _S["as_of"], now)
    # 1. Diary-driven adjustment is PROPOSE-ONLY: classify the message and, for hard constraints
    #    or opportunities, prepare a recompute the athlete must confirm (nothing applied here).
    proposals, questions = _propose(body.text)
    # 1b. No diary change but the athlete's on about advancing/holding + the gate says HOLD → offer it.
    if not proposals:
        hp = _hold_proposal(body.text)
        if hp:
            proposals = [hp]
    # 2. Only when the diary found no plan-relevant change do we fall back to the Slice 4 direct
    #    commands ("move my race", "I'm down to 5 h/wk") which apply immediately + explain.
    edit_note = None if proposals else _try_season_edit(body.text, now)
    out = _S["coach"].respond(body.text, cid, _S["as_of"], now)
    out["conversation_id"] = cid
    if edit_note:
        out["plan_recomputed"] = edit_note
    if proposals:
        out["plan_proposals"] = proposals
    if questions:
        out["clarifying_questions"] = questions
    # 3. Recompute recurring-theme advisories now that this check-in's notes are stored, and
    #    surface them (soft — they never changed the plan).
    themes = _refresh_advisories()
    if themes:
        out["recurring_themes"] = themes
    return out


@app.get("/api/coach/advisories")
def advisories():
    return {"recurring_themes": _compute_advisories()}


@app.get("/api/coach/dashboard")
def coach_dashboard(as_of: str = Query(None)):
    """The merged dashboard card: Wattson's deterministic read (hero + phase gate folded into one
    voice) + vitals + the gate-aware progress visual. Composed server-side so the UI never
    synthesizes coaching copy."""
    _require_loaded()
    ao = as_of or _S["as_of"]
    hero = wm_trend._hero(_S["m"], ao, _S.get("plan"), _S.get("status"))
    prog = plan_progression.assess_progression(_S["m"], _S.get("plan"), ao, _S.get("profile"))
    return plan_review.coach_card(hero, prog)


def _progression_text(p):
    """Compact text rendering of the phase-progression assessment for the coach context (beats 3-4)."""
    if not p or p.get("state") != "ok":
        return None
    g = p.get("gate", {})
    lines = [f"{p['block']} -> {p.get('next_block')}: verdict {p['verdict']}. {p.get('headline', '')}"]
    if p.get("started") and p.get("focus"):
        lines.append(f"Block context — week {p.get('week_in_block')} of {p.get('weeks_in_block')}, "
                     f"focus: {p['focus']}; what it's building: {p.get('watching')}; "
                     f"advance when: {p.get('advance_when')}.")
    if g.get("value") is not None:
        lines.append(f"Gate {g.get('name')}: {g['value']}% (target {g.get('target')}, "
                     f"confidence {g.get('confidence')}).")
    if p.get("this_week_test"):
        lines.append(f"This week tests: {p['this_week_test']}.")
    for br in p.get("branches", []):
        lines.append(f"If {br['outcome']} -> {br['action']} (calendar cost: {br['calendar_cost']}).")
    return " ".join(lines)


def _checkin_streak():
    """Consecutive weeks (ending at the latest) with at least one logged check-in."""
    try:
        rows = [r[0] for r in _S["conn"].execute("SELECT DISTINCT date FROM checkin")]
    except Exception:
        return 0
    if not rows:
        return 0
    mondays = sorted({(datetime.date.fromisoformat(d) - datetime.timedelta(days=datetime.date.fromisoformat(d).weekday()))
                      for d in rows}, reverse=True)
    streak = 1
    for i in range(1, len(mondays)):
        if (mondays[i - 1] - mondays[i]).days == 7:
            streak += 1
        else:
            break
    return streak


def _weekly_briefing():
    """Compose the deterministic weekly briefing + phase-progression and seed them into the coach's
    context so the next reply narrates them (the coach never recomputes these numbers)."""
    themes = _compute_advisories()
    b = plan_review.weekly_briefing(_S["m"], _S.get("plan"), _S["status"], themes, _S["as_of"])
    b["streak"] = _checkin_streak()
    prog = plan_progression.assess_progression(_S["m"], _S.get("plan"), _S["as_of"], _S.get("profile"))
    if _S.get("coach"):
        _S["coach"].weekly_briefing = plan_review.briefing_text(b)
        _S["coach"].phase_progression = _progression_text(prog)
    return b


@app.get("/api/coach/weekly-briefing")
def weekly_briefing():
    _require_loaded()
    return _weekly_briefing()


@app.post("/api/coach/first-read")
def first_read():
    """Coach Wattson's grounded first read on the loaded dataset — the intake validation
    checkpoint. Reuses the orchestrator's grounded context; writes nothing, computes nothing.
    general_goal (if set) reaches the read even when no dated plan exists."""
    _require_loaded()
    season = plan_store.active_season(_S["conn"])
    goal = season.get("general_goal") if season else None
    return _S["coach"].first_read(_S["as_of"], season_goal=goal)


class ConfirmIn(BaseModel):
    proposal_id: int


@app.post("/api/plan/adjustment/confirm")
def confirm_adjustment(body: ConfirmIn):
    """Apply a PENDING proposal the athlete confirmed: write the input, log it, recompute."""
    p = _S["pending"].pop(body.proposal_id, None)
    if not p:
        raise HTTPException(404, "no such pending proposal (it may have expired)")
    s, e, now = _S["season"], p["edit"], datetime.datetime.now().replace(microsecond=0).isoformat()
    if e["target"] == "unavailable":
        rid = plan_store.add_unavailable(_S["conn"], s["id"], e["start_date"], e["end_date"], now,
                                         reason=e["reason"])
        undo = {"table": "unavailable_period", "id": rid}
    elif e["target"] == "block_hold":                 # in-chat phase-hold (mirror /api/progression/hold)
        rid = plan_store.add_modifier(_S["conn"], s["id"], "block_hold", s["start_date"],
                                      s["start_date"], now, hours=e["weeks"], reason=e["block"])
        undo = {"table": "plan_modifier", "id": rid}
    else:
        kind = e["target"]                            # availability | intensity_cap | readiness
        val = e.get("hours") if kind == "availability" else (e.get("factor") if kind == "readiness" else None)
        rid = plan_store.add_modifier(_S["conn"], s["id"], kind, e["start_date"], e["end_date"],
                                      now, hours=val, reason=e.get("reason"))
        undo = {"table": "plan_modifier", "id": rid}
    aid = plan_store.log_adjustment(_S["conn"], s["id"], p["kind"], p["summary"], e, undo, now)
    _refresh_plan()
    return {"applied": p["summary"], "adjustment_id": aid, "plan": _S["plan"]}


@app.post("/api/plan/adjustment/{adjustment_id}/undo")
def undo_adjustment(adjustment_id: int):
    s = _S.get("season")
    if not s:
        raise HTTPException(400, "no active season")
    if plan_store.undo_adjustment(_S["conn"], adjustment_id) is None:
        raise HTTPException(404, "no such active adjustment")
    _refresh_plan()
    return {"undone": adjustment_id, "plan": _S["plan"]}


@app.get("/api/plan/adjustments")
def list_adjustments():
    s = _S.get("season")
    if not s:
        return {"adjustments": []}
    return {"adjustments": plan_store.adjustments_for(_S["conn"], s["id"])}


# ---------------- annual calendar ----------------
class SeasonIn(BaseModel):
    name: str
    start_date: str
    weekly_hours_budget: float
    general_goal: str | None = None      # no-event direction (emphasis only); validated in store


class EventIn(BaseModel):
    name: str
    event_date: str
    priority: str
    event_type: str
    note: str | None = None


class UnavailIn(BaseModel):
    start_date: str
    end_date: str
    reason: str | None = None


@app.get("/api/season")
def get_season():
    s = _S.get("season")
    if not s:
        return {"season": None, "events": [], "unavailable": [], "event_types": plan_store.EVENT_TYPES}
    return {"season": s, "events": plan_store.events_for(_S["conn"], s["id"]),
            "unavailable": plan_store.unavailable_for(_S["conn"], s["id"]),
            "event_types": plan_store.EVENT_TYPES}


@app.post("/api/season")
def upsert_season(body: SeasonIn):
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    s = plan_store.active_season(_S["conn"])          # don't rely on _S in the awaiting state
    try:
        if s:
            plan_store.update_season(_S["conn"], s["id"], name=body.name, start_date=body.start_date,
                                     weekly_hours_budget=body.weekly_hours_budget,
                                     general_goal=body.general_goal)
        else:
            plan_store.create_season(_S["conn"], body.name, body.start_date,
                                     body.weekly_hours_budget, now, general_goal=body.general_goal)
    except ValueError as e:                            # invalid general_goal -> 400
        raise HTTPException(400, str(e))
    # recompute when data is loaded; in the awaiting state just refresh the cached season.
    if _S.get("m") is not None:
        _refresh_plan()
    else:
        _S["season"] = plan_store.active_season(_S["conn"])
    return {"ok": True, "plan": _S.get("plan")}


@app.post("/api/season/event")
def add_event(body: EventIn):
    s = _S.get("season")
    if not s:
        raise HTTPException(400, "create a season first")
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    try:
        plan_store.add_event(_S["conn"], s["id"], body.name, body.event_date, body.priority,
                             body.event_type, now, note=body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _refresh_plan()
    return {"ok": True, "plan": _S["plan"]}


@app.delete("/api/season/event/{event_id}")
def del_event(event_id: int):
    plan_store.delete_event(_S["conn"], event_id)
    _refresh_plan()
    return {"ok": True, "plan": _S["plan"]}


@app.post("/api/season/unavailable")
def add_unavail(body: UnavailIn):
    s = _S.get("season")
    if not s:
        raise HTTPException(400, "create a season first")
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    plan_store.add_unavailable(_S["conn"], s["id"], body.start_date, body.end_date, now,
                               reason=body.reason)
    _refresh_plan()
    return {"ok": True, "plan": _S["plan"]}


@app.delete("/api/season/unavailable/{period_id}")
def del_unavail(period_id: int):
    plan_store.delete_unavailable(_S["conn"], period_id)
    _refresh_plan()
    return {"ok": True, "plan": _S["plan"]}


@app.get("/api/plan")
def get_plan():
    return _S.get("plan") or {"error": "no active season — add one to generate a plan"}


# ---------------- life events (historical context tagged at intake) ----------------
class LifeEventIn(BaseModel):
    start_date: str
    end_date: str | None = None
    category: str
    note: str | None = None
    detector_effect: str | None = None


@app.get("/api/life-event")
def get_life_events():
    return {"life_events": list_life_events(_S["conn"])}


@app.post("/api/life-event")
def post_life_event(body: LifeEventIn):
    if body.category not in LIFE_EVENT_CATEGORIES:
        raise HTTPException(400, f"category must be one of {LIFE_EVENT_CATEGORIES}")
    if body.detector_effect is not None and body.detector_effect not in LIFE_EVENT_EFFECTS:
        raise HTTPException(400, f"detector_effect must be one of {LIFE_EVENT_EFFECTS}")
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    eid = add_life_event(_S["conn"], body.start_date, body.category, now,
                         end_date=body.end_date, note=body.note,
                         detector_effect=body.detector_effect)
    _load_training_data()                             # re-apply the findings pre-pass -> board updates
    return {"ok": True, "id": eid, "board_status": _S["status"]}


@app.delete("/api/life-event/{event_id}")
def del_life_event(event_id: int):
    delete_life_event(_S["conn"], event_id)
    _load_training_data()
    return {"ok": True, "board_status": _S["status"]}


# ---------------- data import ----------------
def _rollback_uploads(written):
    """Undo the files written this request: remove each new file and restore any it replaced."""
    for dest, backup, _ in written:
        if os.path.exists(dest):
            os.remove(dest)
        if backup and os.path.exists(backup):
            os.replace(backup, dest)


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), intake: bool = Query(False)):
    """Ingest one or MORE WKO5 exports, then hot-reload. Safe: writes all the files, rebuilds to
    a temp DB and validates BEFORE committing — if anything is wrong the whole batch is rolled
    back and the live dataset is left untouched. intake=True additionally enforces a >=12-month
    history minimum on the rebuilt dataset (first-run onboarding); intake=False (default,
    incremental updates) keeps the unchanged no-minimum behavior."""
    if not files:
        raise HTTPException(400, "No files provided.")
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    written = []                                      # (dest, backup_or_None, name)
    all_sheets = set()
    try:
        for f in files:
            name = os.path.basename(f.filename or "")
            if not name.lower().endswith(".xlsx"):
                raise HTTPException(400, f"{name or 'a file'}: please upload WKO5 .xlsx exports.")
            data = await f.read()
            try:                                      # classify by CONTENT — any filename is fine
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
                fams = set()
                for ws in wb.worksheets:
                    all_sheets.add(ws.title)
                    sf = loader.classify_sheet(loader.header_map(ws)[0])
                    if sf:
                        fams.add(sf)
                wb.close()
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, f"{name}: that isn't a readable Excel workbook.")
            if not fams:
                raise HTTPException(400, f"{name}: doesn't look like a WKO5 export — no Training "
                                         "History, PMC, or Daily TiZ columns found in it.")
            dest = os.path.join(EXPORTS_DIR, name)
            backup = dest + ".bak" if os.path.exists(dest) else None
            if backup:
                os.replace(dest, backup)
            with open(dest, "wb") as fh:
                fh.write(data)
            os.utime(dest, None)                      # fresh mtime -> newer file wins on overlap
            written.append((dest, backup, name))
    except HTTPException:
        _rollback_uploads(written)                    # restore any files written before the bad one
        raise

    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    tmp = WKO_DB + ".tmp"
    try:
        loader.build_database(tmp, EXPORTS_DIR, loaded_at=now)
        report = validator.run(tmp, EXPORTS_DIR)
        if not report["round_trip_ok"]:
            fails = [n for n, ok, _ in report["round_trip"] if not ok]
            raise RuntimeError("round-trip checks failed: " + ", ".join(fails))
        if intake:                                    # first-run only: require >= 12 months
            c = sqlite3.connect(tmp)
            dmin, dmax = c.execute(
                "SELECT min(date), max(date) FROM daily WHERE is_projected=0").fetchone()
            c.close()
            span = (0 if dmin is None
                    else (datetime.date.fromisoformat(dmax) - datetime.date.fromisoformat(dmin)).days)
            if span < 365:
                raise RuntimeError(f"intake needs at least 12 months of history; these files span "
                                   f"{span} days ({dmin} to {dmax}).")
    except Exception as e:                            # rollback the WHOLE batch — live dataset intact
        _rollback_uploads(written)
        if os.path.exists(tmp):
            os.remove(tmp)
        raise HTTPException(422, f"Upload rejected — dataset wouldn't rebuild cleanly: {e}")

    os.replace(tmp, WKO_DB)
    for dest, backup, _ in written:
        if backup and os.path.exists(backup):
            os.remove(backup)
    _load_training_data()
    return {"ok": True, "files": [n for _, _, n in written], "sheets": sorted(all_sheets),
            "data_through": _S["as_of"], "board_status": _S["status"]}


def _swap_db(staging, dst):
    """Replace dst's CONTENTS in place via SQLite's backup API, instead of renaming over it.
    Under OneDrive (this project's folder is synced) the cloud client keeps a persistent handle
    on wko.db, so os.replace(...) → PermissionError [WinError 5]. Writing into the existing file
    sidesteps that — OneDrive blocks rename/delete, not writes."""
    src = sqlite3.connect(staging)
    d = sqlite3.connect(dst)
    try:
        src.backup(d)
        d.commit()
    finally:
        d.close()
        src.close()
    try:
        os.remove(staging)
    except OSError:
        pass


def _rebuild_db_from_cache() -> bool:
    """Recompute the daily/workout DB from the CACHED Strava summaries using the current dated
    FTP history, then hot-swap it in. No Strava call. Returns False (no rebuild) when there's no
    cached power data yet — e.g. still on the imported WKO5 DB, before any Strava pull."""
    import shutil
    from sources import pull_history, build_db
    summ = list(pull_history.load_cache().values())
    if not any(s.get("np") for s in summ):
        return False
    hist = ftp_history.history(_S["conn"]) if _S.get("conn") else None
    staging = WKO_DB + ".strava"
    build_db.build_db(summ, out_path=staging, load_ftp=hist)   # time-varying TSS from the history
    bak = WKO_DB + ".wko5bak"
    if os.path.exists(WKO_DB) and not os.path.exists(bak):
        shutil.copy2(WKO_DB, bak)                          # one-time WKO5 backup
    _swap_db(staging, WKO_DB)                              # in-place (OneDrive locks rename, not writes)
    _load_training_data()
    return True


@app.post("/api/strava/pull")
def strava_pull(full: bool = Query(False)):
    """Pull rides from Strava (incremental by default; full=True walks all history), capture the
    athlete's current set FTP as a dated history entry if it changed, rebuild the Strava-sourced DB
    (time-varying TSS), and hot-swap it in — same atomic + reload pattern as /api/upload."""
    import traceback
    from sources import pull_history, strava_client
    try:
        res = pull_history.pull(full=full)
        # Strava's current FTP is PROPOSED, not auto-applied — the athlete accepts/edits/dismisses.
        proposal = (ftp_history.propose_strava_ftp(_S["conn"], strava_client.get_athlete_ftp(),
                                                   datetime.date.today().isoformat())
                    if _S.get("conn") else None)
        if not _rebuild_db_from_cache():
            raise HTTPException(400, "No power rides available from Strava yet — nothing to build.")
        return {"ok": True, "data_through": _S["as_of"], "board_status": _S["status"],
                "ftp_proposal": proposal, **res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Strava pull failed at: {type(e).__name__}: {e}\n"
                                 + traceback.format_exc()[-800:])


class FtpEntryIn(BaseModel):
    effective_date: str
    ftp: float


@app.get("/api/ftp-history")
def get_ftp_history():
    """The athlete's dated load-FTP history (the set/threshold FTP used for TSS), oldest first, plus
    any open Strava-FTP proposal awaiting a decision."""
    _require_loaded()
    return {"entries": ftp_history.list_entries(_S["conn"]),
            "current": ftp_history.latest_ftp(_S["conn"]),
            "pending": ftp_history.get_pending(_S["conn"])}


@app.post("/api/ftp-history/accept-pending")
def accept_pending_ftp():
    """Accept the proposed Strava FTP (effective the date Strava reported it) and recompute TSS."""
    _require_loaded()
    accepted = ftp_history.accept_pending(_S["conn"])
    if not accepted:
        raise HTTPException(404, "no pending FTP to accept")
    applied = _rebuild_db_from_cache()
    return {"ok": True, "applied": applied, "accepted": accepted,
            "entries": ftp_history.list_entries(_S["conn"])}


@app.post("/api/ftp-history/dismiss-pending")
def dismiss_pending_ftp():
    """Dismiss the proposed Strava FTP — hides the notice and remembers the value so it won't prompt
    again unless Strava reports a different one. Applies nothing."""
    _require_loaded()
    ftp_history.dismiss_pending(_S["conn"])
    return {"ok": True}


@app.post("/api/ftp-history")
def add_ftp_entry(body: FtpEntryIn):
    """Add (or replace the same-day) dated FTP entry, then recompute TSS across history from the
    Strava cache. `applied` is False if there's no cache yet (it'll take effect on the next pull)."""
    _require_loaded()
    if not (0 < body.ftp <= 600):
        raise HTTPException(400, "FTP must be between 1 and 600 W")
    try:
        datetime.date.fromisoformat(body.effective_date)
    except ValueError:
        raise HTTPException(400, "effective_date must be ISO yyyy-mm-dd")
    ftp_history.add_entry(_S["conn"], body.effective_date, body.ftp, source="manual",
                          created_at=datetime.datetime.now().replace(microsecond=0).isoformat())
    ftp_history.clear_pending_if_value(_S["conn"], body.ftp)   # Edit path: hand-added the proposed FTP
    applied = _rebuild_db_from_cache()
    return {"ok": True, "applied": applied, "entries": ftp_history.list_entries(_S["conn"]),
            "data_through": _S.get("as_of")}


@app.delete("/api/ftp-history/{entry_id}")
def delete_ftp_entry(entry_id: int):
    _require_loaded()
    if ftp_history.delete_entry(_S["conn"], entry_id) == 0:
        raise HTTPException(404, "no such FTP entry")
    applied = _rebuild_db_from_cache()
    return {"ok": True, "applied": applied, "entries": ftp_history.list_entries(_S["conn"])}


@app.get("/api/log")
def training_log(year: int = Query(None), month: int = Query(None)):
    """Training-log month: per-day ride cards (zone-colored) + weekly TSS/Fitness actual-vs-plan.
    Built from the Strava cache + the live actual daily series + the plan."""
    _require_loaded()
    import pandas as pd
    from sources import pull_history, build_db, log as wlog
    ao = datetime.date.fromisoformat(_S["as_of"])
    year, month = year or ao.year, month or ao.month
    ftp = ftp_history.history(_S["conn"]) or build_db._config_ftp() or 200   # time-varying per ride
    summaries = list(pull_history.load_cache().values())
    daily_actual = {}
    m = _S.get("m")
    if m is not None:
        for ts in m.daily.index:
            c, t = m.daily.at[ts, "ctl"], m.daily.at[ts, "tss_sum"]
            daily_actual[ts.strftime("%Y-%m-%d")] = {
                "ctl": None if pd.isna(c) else float(c),
                "tss_sum": None if pd.isna(t) else float(t)}
    return wlog.build_month(summaries, daily_actual, _S.get("plan"), ftp, year, month)


# ---------------- athlete profile ----------------
_INT_FIELDS = {"birth_year", "floor_hold_weeks", "floor_window_months"}
_STR_FIELDS = {"name", "units", "week_starts_on"}
_NULLABLE = {"birth_year", "weight_kg"}      # empty weight saves as None (float otherwise)


def _coerce(field, value):
    """Coerce an incoming JSON value to the profile field's type; '' / None -> None for
    nullable fixed facts, else fall back to the default."""
    if value is None or value == "":
        return None if field in _NULLABLE else getattr(DEFAULT_PROFILE, field)
    if field in _STR_FIELDS:
        return str(value)
    if field in _INT_FIELDS:
        return int(value)
    return float(value)


@app.get("/api/profile")
def get_profile():
    p = _S["profile"]
    year = int(_S["as_of"][:4]) if _S.get("as_of") else None   # no data yet during cold-start intake
    return {
        "profile": dataclasses.asdict(p),
        "fixed_fact_fields": list(AthleteProfile.FIXED_FACT_FIELDS),
        "tuned_fields": list(AthleteProfile.TUNED_FIELDS),
        "derived": {"age": p.age(year) if year else None,
                    "is_masters": p.is_masters(year) if year else False},
    }


class ProfileIn(BaseModel):
    updates: dict


@app.post("/api/profile")
def update_profile(body: ProfileIn):
    valid = {f.name for f in dataclasses.fields(AthleteProfile)} - {"athlete_id"}
    merged = dataclasses.asdict(_S["profile"])
    for k, v in body.updates.items():
        if k in valid:
            merged[k] = _coerce(k, v)
    new_profile = AthleteProfile(**merged)
    profile.save_profile(_S["conn"], new_profile)
    _S["profile"] = new_profile
    _load_training_data()                            # athlete-relative constants changed -> recompute
    return {"ok": True, "board_status": _S["status"], "data_through": _S["as_of"]}


# ---------------- big-ride achievements (Wattson's celebration moment) ----------------
@app.get("/api/achievements/pending")
def achievements_pending():
    """The achievement to celebrate now (century / huge climb / longest-ever on the most recent
    ride), or {achievement: null}. The frontend's Celebration shows Wattson holding the object."""
    _require_loaded()
    from sources import pull_history, achievements
    summaries = list(pull_history.load_cache().values())
    return {"achievement": achievements.pending(summaries, achievements.dismissed_ids(_S["conn"]))}


class AchievementDismissIn(BaseModel):
    ride_id: str


@app.post("/api/achievements/dismiss")
def achievements_dismiss(body: AchievementDismissIn):
    """Stop showing the celebration for this ride (it would otherwise stay until the next ride)."""
    _require_loaded()
    from sources import achievements
    achievements.dismiss(_S["conn"], body.ride_id)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "loaded": bool(_S)}
