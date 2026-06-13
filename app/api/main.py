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

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(APP_DIR)
for p in ("slice4", "slice3", "slice2", "slice1", "slice0"):
    sys.path.insert(0, os.path.join(ROOT, p))

from wko_metrics import metrics, detectors, profile, AthleteProfile, DEFAULT_PROFILE  # noqa: E402
from watchman import select, DEFAULT_SELECTION         # noqa: E402
from wko_ingest import loader, validator               # noqa: E402
from coach import store                                # noqa: E402
from coach.orchestrator import Coach                   # noqa: E402
from coach.retrieval import MethodologyIndex           # noqa: E402
from plan import store as plan_store, generator as plan_gen  # noqa: E402

WKO_DB = os.environ.get("WKO_DB", os.path.join(ROOT, "slice0", "wko.db"))
EXPORTS_DIR = os.path.join(ROOT, "WKO5 Exports")
COACH_DB = os.path.join(ROOT, "slice3", "coach.db")
INDEX_DB = os.path.join(ROOT, "slice3", "methodology.db")

app = FastAPI(title="Training Coach API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_S = {}


def _build_plan(conn, m, prof, as_of):
    """Generate the deterministic plan for the active season, or None if no season set."""
    season = plan_store.active_season(conn)
    if not season:
        return None, None
    events = plan_store.events_for(conn, season["id"])
    unavail = plan_store.unavailable_for(conn, season["id"])
    plan = plan_gen.generate_plan(m, prof, season, events, unavail, as_of)
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


def _load_training_data():
    """(Re)build the in-memory dashboard + coach from the current wko.db, using the loaded
    AthleteProfile for all athlete-relative constants. The coach.db connection (conversation
    history + the profile row) is opened once and reused across refreshes."""
    conn = _S.get("conn") or store.connect(COACH_DB)
    plan_store.init(conn)                             # ensure season tables exist in coach.db
    prof = _S.get("profile") or profile.load_profile(conn)

    m = metrics.Metrics(sqlite3.connect(WKO_DB, check_same_thread=False), profile=prof)
    findings = detectors.run_all(m)
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


def _refresh_plan():
    """Recompute the plan after a season-input change and push it into the coach context."""
    season, plan = _build_plan(_S["conn"], _S["m"], _S["profile"], _S["as_of"])
    _S["season"], _S["plan"] = season, plan
    _S["coach"].plan_summary = _plan_summary(plan)
    return plan


@app.on_event("startup")
def _startup():
    _load_training_data()


# ---------------- watchman ----------------
@app.get("/api/meta")
def meta():
    last = store.latest_conversation(_S["conn"])
    return {"date_min": _S["date_min"], "date_max": _S["as_of"],
            "default_as_of": _S["as_of"], "board_status": _S["status"],
            "latest_conversation_id": last[0] if last else None}


@app.get("/api/watchman")
def watchman(as_of: str = Query(...), window: int = Query(120, ge=14, le=400)):
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


@app.post("/api/coach/message")
def message(body: MessageIn):
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    cid = body.conversation_id or store.start_conversation(_S["conn"], _S["as_of"], now)
    # 1. If the message changes a season input, apply it + recompute BEFORE replying, so the
    #    coach explains the freshly-recomputed plan (it never edits numbers itself).
    edit_note = _try_season_edit(body.text, now)
    out = _S["coach"].respond(body.text, cid, _S["as_of"], now)
    out["conversation_id"] = cid
    if edit_note:
        out["plan_recomputed"] = edit_note
    return out


# ---------------- annual calendar ----------------
class SeasonIn(BaseModel):
    name: str
    start_date: str
    weekly_hours_budget: float


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
    s = _S.get("season")
    if s:
        plan_store.update_season(_S["conn"], s["id"], name=body.name, start_date=body.start_date,
                                 weekly_hours_budget=body.weekly_hours_budget)
    else:
        plan_store.create_season(_S["conn"], body.name, body.start_date,
                                 body.weekly_hours_budget, now)
    _refresh_plan()
    return {"ok": True, "plan": _S["plan"]}


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


# ---------------- data import ----------------
@app.post("/api/upload")
async def upload(file: UploadFile):
    """Ingest a new WKO5 export, then hot-reload. Safe: rebuilds to a temp DB and validates
    BEFORE committing — a bad file is rejected and the live dataset is left untouched."""
    name = os.path.basename(file.filename or "")
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload a WKO5 .xlsx export.")
    if loader._classify(name) == "?":
        raise HTTPException(400, "Filename not recognized. Expected one starting with "
                                 "'Training History', 'PMC Report', 'Daily TiZ', or 'Week of'.")
    data = await file.read()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        sheets = [ws.title for ws in wb.worksheets]
        wb.close()
    except Exception:
        raise HTTPException(400, "That file isn't a readable Excel workbook.")

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    dest = os.path.join(EXPORTS_DIR, name)
    backup = dest + ".bak" if os.path.exists(dest) else None
    if backup:
        os.replace(dest, backup)
    with open(dest, "wb") as fh:
        fh.write(data)
    os.utime(dest, None)                              # fresh mtime -> newer file wins on overlap

    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    tmp = WKO_DB + ".tmp"
    try:
        loader.build_database(tmp, EXPORTS_DIR, loaded_at=now)
        report = validator.run(tmp, EXPORTS_DIR)
        if not report["round_trip_ok"]:
            fails = [n for n, ok, _ in report["round_trip"] if not ok]
            raise RuntimeError("round-trip checks failed: " + ", ".join(fails))
    except Exception as e:                            # rollback — leave the live dataset intact
        os.remove(dest)
        if backup:
            os.replace(backup, dest)
        if os.path.exists(tmp):
            os.remove(tmp)
        raise HTTPException(422, f"Upload rejected — dataset wouldn't rebuild cleanly: {e}")

    os.replace(tmp, WKO_DB)
    if backup and os.path.exists(backup):
        os.remove(backup)
    _load_training_data()
    return {"ok": True, "filename": name, "sheets": sheets,
            "data_through": _S["as_of"], "board_status": _S["status"]}


# ---------------- athlete profile ----------------
_INT_FIELDS = {"birth_year", "floor_hold_weeks", "floor_window_months"}
_STR_FIELDS = {"name", "units", "week_starts_on"}
_NULLABLE = {"birth_year"}


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
    year = int(_S["as_of"][:4])
    return {
        "profile": dataclasses.asdict(p),
        "fixed_fact_fields": list(AthleteProfile.FIXED_FACT_FIELDS),
        "tuned_fields": list(AthleteProfile.TUNED_FIELDS),
        "derived": {"age": p.age(year), "is_masters": p.is_masters(year)},
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
