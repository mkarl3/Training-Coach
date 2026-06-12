# Slice 0 — WKO5 ingestion

Ingests the WKO5 `.xlsx` exports into a clean, queryable SQLite dataset. **Ingestion only** —
no analytics, detectors, dashboard, or LLM. Stops when data loads clean and tests pass.

## Run
```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
python build.py            # builds wko.db, validates, prints ingest_meta + data_flags
python -m pytest tests/ -q # 14 tests
```
`build.py [exports_dir] [db_path]` — defaults to the WKO5 Exports folder and `./wko.db`.

## Schema (`wko_ingest/schema.sql`)
- **`workout`** — per-workout grain (one row per Training History activity; multi-ride days = multiple rows).
- **`daily`** — one row per calendar day across the full span; no-ride days are explicit rows.
- **`ingest_meta`** — provenance: which sheet, role (loaded / validation-only), row counts, date range.
- **`column_doc`** — queryable notes for the load-bearing semantic columns.

### Non-negotiable rules baked in
1. **`if_daily` is display-only** — never a detector input (see column comment + `column_doc`).
   Monotony/distribution/intensity logic must use `daily.tss_sum` and workout-grain `if_`.
2. **No-ride day = `tss_sum` 0, not NULL.** `NULL` = unknown/not tracked (used only for `is_projected` days).
3. **`daily.data_flags`** — validator stamps per-day anomalies so findings survive at query time.

### Load rules
- Field mapping keyed on row-2 header **names**, not column index (handles year-to-year drift).
- PMC dual rows per date merged: midnight 00:00 row → metrics; intraday rows → wellness.
- Dedup workouts by `(started_at, activity_type, duration_sec)`.
- `Week of …xlsx` is validation-only, **except** its one `2026-05-29` Training History row.
- `is_projected` set by the **ride horizon** (last actual ride day); wellness-only days do not extend it.

## Validation (`wko_ingest/validator.py`)
- Round-trip invariants (contiguous spine, TSS conservation, rest-day = 0, projected = NULL, units).
- Anomaly stamping → `data_flags` (`tss_without_duration`, `cycling_zero_tss`, `ctl_discontinuity`,
  `tsb_inconsistent`, `missing_ctl_actual`).
- Cross-check vs the independent Week-of-5/25 snapshot, split into parse-fidelity (must match) and
  reconciliation (cross-source divergence on volatile recent acute-load — reported, not failed).
