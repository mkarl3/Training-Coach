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
import sqlite3
import sys

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(APP_DIR)
for p in ("slice4", "slice3", "slice2", "slice1", "slice0"):
    sys.path.insert(0, os.path.join(ROOT, p))

from wko_metrics import metrics, detectors, profile, AthleteProfile, DEFAULT_PROFILE  # noqa: E402
from watchman import (select, DEFAULT_SELECTION, apply_life_events, load_life_events,  # noqa: E402
                      add_life_event, list_life_events, delete_life_event,
                      LIFE_EVENT_CATEGORIES, LIFE_EVENT_EFFECTS)
from wko_ingest import loader, validator               # noqa: E402
from coach import store, capture as coach_capture     # noqa: E402
from coach.orchestrator import Coach                   # noqa: E402
from coach.retrieval import MethodologyIndex           # noqa: E402
from plan import store as plan_store, generator as plan_gen, diary as plan_diary, review as plan_review  # noqa: E402

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
    plan = plan_gen.generate_plan(m, prof, season, events, unavail, as_of,
                                  availability=availability, intensity_caps=intensity_caps)
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
    _refresh_advisories()              # seed recurring-theme context for the coach


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
    return None


def _candidate_plan(edit):
    """Generate the plan that WOULD result from applying `edit`, without persisting anything."""
    s = _S["season"]
    events = plan_store.events_for(_S["conn"], s["id"])
    unavail = plan_store.unavailable_for(_S["conn"], s["id"])
    availability, intensity_caps = plan_store.active_modifiers(_S["conn"], s["id"])
    if edit["target"] == "unavailable":
        unavail = unavail + [edit]
    elif edit["target"] == "availability":
        availability = availability + [edit]
    elif edit["target"] == "intensity_cap":
        intensity_caps = intensity_caps + [edit]
    return plan_gen.generate_plan(_S["m"], _S["profile"], s, events, unavail, _S["as_of"],
                                  availability=availability, intensity_caps=intensity_caps)


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
        _S["pending_seq"] += 1
        pid = _S["pending_seq"]
        _S["pending"][pid] = {"kind": it.kind.value, "summary": it.summary, "edit": edit}
        proposals.append({"id": pid, "kind": it.kind.value, "summary": it.summary,
                          "quote": it.quote, "edit": edit,
                          "diff": plan_gen.diff_plans(plan, cand)})
    return proposals, questions


@app.post("/api/coach/message")
def message(body: MessageIn):
    _require_loaded()
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    cid = body.conversation_id or store.start_conversation(_S["conn"], _S["as_of"], now)
    # 1. Diary-driven adjustment is PROPOSE-ONLY: classify the message and, for hard constraints
    #    or opportunities, prepare a recompute the athlete must confirm (nothing applied here).
    proposals, questions = _propose(body.text)
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


def _weekly_briefing():
    """Compose the deterministic weekly briefing and seed it into the coach's context so the
    next reply narrates it (the coach never recomputes these numbers)."""
    themes = _compute_advisories()
    b = plan_review.weekly_briefing(_S["m"], _S.get("plan"), _S["status"], themes, _S["as_of"])
    if _S.get("coach"):
        _S["coach"].weekly_briefing = plan_review.briefing_text(b)
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
    else:
        kind = "availability" if e["target"] == "availability" else "intensity_cap"
        rid = plan_store.add_modifier(_S["conn"], s["id"], kind, e["start_date"], e["end_date"],
                                      now, hours=e.get("hours"), reason=e["reason"])
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


@app.get("/api/health")
def health():
    return {"ok": True, "loaded": bool(_S)}
