# Slice 1, Part A — Derived-Metrics Library

Pure, tested metric functions over the Slice-0 SQLite dataset. **No detectors, findings,
dashboard, or LLM.** Part B (detectors) will consume `wko_metrics.metrics.Metrics` only —
never the raw tables — so each metric is defined exactly once.

## Run
```
python verify.py            # module output vs independent recomputation on real dates
python -m pytest tests/ -q  # 15 tests
```
Reads `../slice0/wko.db`. Reconciliation (`tss_if_mismatch`) is stamped by the Slice-0
validator into `daily.data_flags` (advisory only; no row edited or excluded).

## Layout
- `wko_metrics/config.py` — `MetricsConfig`: every tunable constant (windows, IF band,
  ACWR spans/thresholds, time constants) in one place. No inline literals in metrics.
- `wko_metrics/metrics.py` — pure functions (Series in/out) + `Metrics` facade.

## Metrics (daily-grain, rolling/windowed)
| metric | definition | notes |
|---|---|---|
| ramp rate | `(CTL - CTL.shift(w)) * 7/w` | CTL pts/week, window configurable |
| Foster monotony | rolling `mean/SD` of daily `tss_sum` | rest days (0) are real inputs; SD=0 → NaN |
| Foster strain | rolling `sum(load) * monotony` | |
| ACWR | EWMA `acute/chronic`, α=2/(span+1) | **coupled numerator/denominator; validity contested** — descriptive only |
| TSB trajectory | OLS slope of `tsb` over window | same-day `TSB = CTL − ATL`; rising/flat/falling |
| aerobic decoupling | WKO `pwHr` % per long ride | intra-ride streams not exported; gated to rides ≥ `long_ride_min_sec` |
| power-duration | `p1hr/p2hr` ratio & gap | gated insufficient where no 2-hr sample |
| TiZ distribution | rolling per-zone share | power Z1–6, HR Z1–5; zero-total → NaN |
| personal CTL floor | **dynamic** — highest weekly-mean CTL held ≥8 wk in trailing 18 mo | def. A "demonstrated sustainable base"; `personal_ctl_floor()` (retrospective best-held) + `personal_ctl_floor_asof()` (no-lookahead). Athlete-relative, unvalidated. |

## Part B — Detector engine (`wko_metrics/detectors.py`)
Six failure-mode detectors, each a **pure function over the `Metrics` facade** (never raw
tables, never re-derived, never `if_daily`). Each emits the **frozen `Finding` dict** —
data only, no prose. Two artifacts per mode (`retrospective` / `early_warning`), two-tier
severity (`watch`/`confirmed`), family tag, `priority` (action rank), and `data_flags`
(advisory flags from days the window touches — e.g. `tss_if_mismatch`). Reset/exit
conditions per mode live in `DetectorConfig.reset_conditions` (Slice-2 consumes them).

`python report_findings.py` runs all six and prints the action-ranked findings.

**gap_unravel fitness gate is dynamic & per-athlete.** A gap only counts as a build-and-crash
if a real build preceded it: recent-peak CTL (trailing 56 d) ≥ the athlete's own **CTL p80**,
computed as-of (expanding, no-lookahead) for early-warning and all-history for retrospective
(`Metrics.ctl_percentile_threshold`). This self-scales to whoever the athlete is and replaced
the thread-alive gate that fired on every rest week (early-warning watch 107 → 49). p80 ≈ 36
here — above the athlete's normal range (~p50=31) yet below the late-Feb-2026 build (CTL 37),
so it fires the real build-crash and skips ordinary January dips (recent peak 33–35).

**HONEST FRAMING:** tests assert each detector is correctly *encoded* against this one
athlete's confirmed episodes — they do **not** validate that the fingerprints generalize.
That needs athlete #2. Overtraining has no positive episode here (negative-test only).
ACWR-EWMA is noisy on this time-crunched athlete (~44 confirmed spike-clusters in 3.3 yr,
after a chronic/acute gate + hysteresis); injury_spike flags **load risk, never tissue**.
