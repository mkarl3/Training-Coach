"""Coach API — the weekly check-in backend.

Startup: loads the Metrics facade, runs the Slice-1 detectors, computes the Slice-2
selection for the latest data date, and opens the methodology index + coach.db. The LLM
is only ever handed findings + retrieved passages + notes (see orchestrator.py).
"""
import datetime
import os
import sqlite3
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

API_DIR = os.path.dirname(os.path.abspath(__file__))
SLICE3 = os.path.dirname(API_DIR)
ROOT = os.path.dirname(SLICE3)
for p in (SLICE3, os.path.join(ROOT, "slice2"), os.path.join(ROOT, "slice1")):
    sys.path.insert(0, p)

from wko_metrics import metrics, detectors          # noqa: E402
from watchman import select                          # noqa: E402
from coach import store                              # noqa: E402
from coach.orchestrator import Coach                 # noqa: E402
from coach.retrieval import MethodologyIndex         # noqa: E402

WKO_DB = os.environ.get("WKO_DB", os.path.join(ROOT, "slice0", "wko.db"))
COACH_DB = os.path.join(SLICE3, "coach.db")
INDEX_DB = os.path.join(SLICE3, "methodology.db")

app = FastAPI(title="Coach API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_S = {}


@app.on_event("startup")
def _load():
    m = metrics.Metrics(sqlite3.connect(WKO_DB, check_same_thread=False))
    findings = detectors.run_all(m)
    as_of = m.daily.index.max().strftime("%Y-%m-%d")
    watch_state = select(findings, as_of, m)
    watch_state.pop("trajectory", None)              # the coach reads findings, not series
    cutoff = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=365)).isoformat()
    ranked = detectors.action_rank(
        [f for f in findings if f["severity"] == "confirmed" and f["window_end"] >= cutoff])
    conn = store.connect(COACH_DB)
    _S.update(
        as_of=as_of,
        conn=conn,
        coach=Coach(conn, watch_state, ranked, MethodologyIndex(INDEX_DB)),
        status=watch_state["status"],
    )


class MessageIn(BaseModel):
    text: str
    conversation_id: int | None = None


@app.get("/api/coach/meta")
def meta():
    last = store.latest_conversation(_S["conn"])
    return {"as_of": _S["as_of"], "board_status": _S["status"],
            "latest_conversation_id": last[0] if last else None}


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


@app.get("/api/health")
def health():
    return {"ok": True, "loaded": bool(_S)}
