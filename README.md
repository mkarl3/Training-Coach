# Training Coach

A cycling training-analysis app built from WKO5 exports. It ingests an athlete's training
history, derives training-load metrics, detects failure modes (the ways an aerobic block
fails to produce adaptation), and surfaces them in a trend-first "watchman" dashboard.

Built in vertical slices, each self-contained and tested.

> **Honest framing:** the detectors and selection logic are encoded and tuned against **one
> athlete's** history. Passing tests prove correct encoding for that person, not that the
> fingerprints generalize. Validation comes with a second athlete.

## The app

[`app/`](app) is the **unified product**: one FastAPI backend (port 8000) composing all
slices, one React frontend (port 5179) with the watchman dashboard and the coach chat
side by side. The per-slice frontends/backends below still run standalone but are
superseded by `app/` for day-to-day use.

```bash
# backend (needs ANTHROPIC_API_KEY for the coach)
cd app && python -m uvicorn api.main:app --port 8000
# frontend
cd app/frontend && npm install && npm run dev      # -> http://127.0.0.1:5179
```

## Slices

| dir | what it is | tests |
|---|---|---|
| [`slice0/`](slice0) | **Ingestion** — parse WKO5 `.xlsx` exports into a clean, queryable SQLite dataset (daily + per-workout grain), with a validator that round-trips the data and flags anomalies. | 14 |
| [`slice1/`](slice1) | **Metrics + detectors** — a pure metrics library (ramp, monotony, ACWR-EWMA, TSB trajectory, decoupling, power-duration, time-in-zone, dynamic CTL floor) and six failure-mode detectors emitting a frozen findings contract. | 38 |
| [`slice2/`](slice2) | **Watchman** — a selection/suppression layer that turns the full findings set into "what's active now," a FastAPI backend, and a React (Vite) trend-first dashboard. | 13 |
| [`slice3/`](slice3) | **Coach** — RAG over the methodology corpus, structurally-bounded subjective capture, conversation memory, and the grounded LLM check-in. | 11 |
| `slice1/wko_metrics/profile.py` | **Slice 3.5 — Athlete profile.** Per-athlete identity + fixed facts (age/masters, units) + the relocated athlete-relative tuned constants. Detectors/watchman/coach read from it. | (in slice1) |
| [`slice4/`](slice4) | **Annual calendar (hybrid).** Season inputs (goals/availability/gaps) + a deterministic, traceable plan skeleton built on the Periodization Matrix block structure (Prep→Base 1-3→Build 1-2→Peak→Race, scaled to the weeks available) with the six failure modes as forward guardrails, the 50%-rule single-ride TSS cap per week, week alignment per the athlete's Monday/Sunday preference, and planned-vs-actual TSS once data passes the season start + the coach explaining it and conversationally recomputing on input changes. | 30 |
| `slice4/plan/diary.py` | **Slice 4.5 — Diary-driven adjustment.** A conservative classifier turns coach check-ins into plan-input *proposals* (time-loss → unavailable; opportunity → transient availability bump; limiter/re-entry → intensity-cap window; soft → informational; ambiguous → ask). Every change is proposed with a plan diff, applied only on confirm, recomputed deterministically, and reversible via an audit trail. Guardrails still bind the upside. Recurring soft themes across check-ins are surfaced to the coach + UI as non-binding context — they never move a number. | (in slice4) |

Deferred ideas are logged in [`slice1/deferred_modes.md`](slice1/deferred_modes.md).

## Stack

Python 3.11+ · pandas · FastAPI · SQLite · pytest · React (Vite). No LLM in the analysis
path — the detectors emit structured data; interpretation is a future slice.

## Adding new data

Two ways to feed new WKO5 exports:
- **In-app (easiest):** the **↑ Update training data** button in the app header. Pick the
  `.xlsx`; it ingests, re-validates, and hot-reloads the dashboard + coach. A bad file is
  rejected without touching the live dataset. Weekly snapshot files are first-class —
  drop a new "Week of …" each week. On any date two exports overlap, the **newer file wins**
  (by modification time; a full-year file beats a weekly snapshot on a tie).
- **Terminal:** drop files in `WKO5 Exports/` and run `.\refresh.ps1` (rebuilds + restarts
  the backend).

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
