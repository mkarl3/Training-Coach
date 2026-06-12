"""Watchman API — exposes the trajectory series + the selected active-findings set.

Computes nothing new: builds the Metrics facade + Slice-1 findings ONCE at startup and
serves the deterministic selection output. No LLM. Read-only.
"""
import dataclasses
import os
import sqlite3
import sys

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

API_DIR = os.path.dirname(os.path.abspath(__file__))
SLICE2 = os.path.dirname(API_DIR)
SLICE1 = os.path.join(os.path.dirname(SLICE2), "slice1")
for p in (SLICE2, SLICE1):
    sys.path.insert(0, p)

from wko_metrics import metrics, detectors          # noqa: E402
from watchman import select, DEFAULT_SELECTION       # noqa: E402

DB = os.environ.get("WKO_DB", r"C:\Users\mkarl\OneDrive\Documents\Training Coach\slice0\wko.db")

app = FastAPI(title="Watchman API", version="0.1")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATE = {}


@app.on_event("startup")
def _load():
    conn = sqlite3.connect(DB, check_same_thread=False)
    m = metrics.Metrics(conn)              # loads data into DataFrames; conn unused afterwards
    _STATE["m"] = m
    _STATE["findings"] = detectors.run_all(m)
    _STATE["date_min"] = m.daily.index.min().strftime("%Y-%m-%d")
    _STATE["date_max"] = m.daily.index.max().strftime("%Y-%m-%d")


@app.get("/api/meta")
def meta():
    return {
        "date_min": _STATE["date_min"],
        "date_max": _STATE["date_max"],
        "default_as_of": _STATE["date_max"],
        "findings_total": len(_STATE["findings"]),
    }


@app.get("/api/watchman")
def watchman(as_of: str = Query(...), window: int = Query(90, ge=14, le=400)):
    m = _STATE["m"]
    if not (_STATE["date_min"] <= as_of <= _STATE["date_max"]):
        raise HTTPException(400, f"as_of must be in [{_STATE['date_min']}, {_STATE['date_max']}]")
    scfg = dataclasses.replace(DEFAULT_SELECTION, trajectory_window_days=window)
    return select(_STATE["findings"], as_of, m, scfg)


@app.get("/api/health")
def health():
    return {"ok": True, "loaded": bool(_STATE)}
