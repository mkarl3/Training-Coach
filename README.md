# Training Coach

A cycling training-analysis app built from WKO5 exports. It ingests an athlete's training
history, derives training-load metrics, detects failure modes (the ways an aerobic block
fails to produce adaptation), and surfaces them in a trend-first "watchman" dashboard.

Built in vertical slices, each self-contained and tested.

> **Honest framing:** the detectors and selection logic are encoded and tuned against **one
> athlete's** history. Passing tests prove correct encoding for that person, not that the
> fingerprints generalize. Validation comes with a second athlete.

## Slices

| dir | what it is | tests |
|---|---|---|
| [`slice0/`](slice0) | **Ingestion** — parse WKO5 `.xlsx` exports into a clean, queryable SQLite dataset (daily + per-workout grain), with a validator that round-trips the data and flags anomalies. | 14 |
| [`slice1/`](slice1) | **Metrics + detectors** — a pure metrics library (ramp, monotony, ACWR-EWMA, TSB trajectory, decoupling, power-duration, time-in-zone, dynamic CTL floor) and six failure-mode detectors emitting a frozen findings contract. | 38 |
| [`slice2/`](slice2) | **Watchman** — a selection/suppression layer that turns the full findings set into "what's active now," a FastAPI backend, and a React (Vite) trend-first dashboard. | 13 |

Deferred ideas are logged in [`slice1/deferred_modes.md`](slice1/deferred_modes.md).

## Stack

Python 3.11+ · pandas · FastAPI · SQLite · pytest · React (Vite). No LLM in the analysis
path — the detectors emit structured data; interpretation is a future slice.

## Your data (not in this repo)

Personal WKO5 exports and the generated `wko.db` are **gitignored** — bring your own. Drop
WKO5 `.xlsx` exports into `WKO5 Exports/`, then build the dataset:

```bash
python -m venv .venv && .venv\Scripts\pip install -r slice0/requirements.txt pandas fastapi "uvicorn[standard]"
python slice0/build.py            # -> slice0/wko.db (validated)
```

## Run the dashboard

```bash
# backend (set WKO_DB if your db isn't at the default path)
python -m uvicorn api.main:app --port 8000      # from slice2/

# frontend
cd slice2/frontend && npm install && npm run dev # -> http://127.0.0.1:5180
```

## Test

```bash
cd slice0 && pytest -q
cd slice1 && pytest -q
cd slice2 && pytest -q
```
