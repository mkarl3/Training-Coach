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
for p in ("slice3", "slice2", "slice1", "slice0"):
    sys.path.insert(0, os.path.join(ROOT, p))

from wko_metrics import metrics, detectors            # noqa: E402
from watchman import select, DEFAULT_SELECTION         # noqa: E402
from wko_ingest import loader, validator               # noqa: E402
from coach import store                                # noqa: E402
from coach.orchestrator import Coach                   # noqa: E402
from coach.retrieval import MethodologyIndex           # noqa: E402

WKO_DB = os.environ.get("WKO_DB", os.path.join(ROOT, "slice0", "wko.db"))
EXPORTS_DIR = os.path.join(ROOT, "WKO5 Exports")
COACH_DB = os.path.join(ROOT, "slice3", "coach.db")
INDEX_DB = os.path.join(ROOT, "slice3", "methodology.db")

app = FastAPI(title="Training Coach API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_S = {}


def _load_training_data():
    """(Re)build the in-memory dashboard + coach from the current wko.db. The coach.db
    connection (conversation history) is opened once and reused across refreshes."""
    m = metrics.Metrics(sqlite3.connect(WKO_DB, check_same_thread=False))
    findings = detectors.run_all(m)
    as_of = m.daily.index.max().strftime("%Y-%m-%d")
    watch_now = select(findings, as_of, m)

    coach_state = dict(watch_now)
    coach_state.pop("trajectory", None)               # the coach reads findings, not series
    cutoff = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=365)).isoformat()
    ranked = detectors.action_rank(
        [f for f in findings if f["severity"] == "confirmed" and f["window_end"] >= cutoff])

    conn = _S.get("conn") or store.connect(COACH_DB)
    _S.update(
        m=m, findings=findings, as_of=as_of, status=watch_now["status"], conn=conn,
        coach=Coach(conn, coach_state, ranked, MethodologyIndex(INDEX_DB)),
        date_min=m.daily.index.min().strftime("%Y-%m-%d"),
    )


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


@app.post("/api/coach/message")
def message(body: MessageIn):
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    cid = body.conversation_id or store.start_conversation(_S["conn"], _S["as_of"], now)
    out = _S["coach"].respond(body.text, cid, _S["as_of"], now)
    out["conversation_id"] = cid
    return out


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


@app.get("/api/health")
def health():
    return {"ok": True, "loaded": bool(_S)}
