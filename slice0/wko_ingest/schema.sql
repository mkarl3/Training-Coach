-- WKO5 ingestion — Slice 0 schema (approved).
-- Conventions: dates are TEXT ISO 'YYYY-MM-DD'; all durations are INTEGER seconds.
-- The '--' export sentinel and blanks map to NULL, never 0.
-- NULL means "unknown / not tracked"; 0 means a real measured/derived zero.

PRAGMA foreign_keys = ON;

-- Per-workout grain: one row per Training History activity (multi-ride days = multiple rows).
CREATE TABLE workout (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,            -- calendar date 'YYYY-MM-DD'
    started_at      TEXT NOT NULL,            -- full ISO timestamp from the export
    activity_type   TEXT,
    is_cycling      INTEGER NOT NULL DEFAULT 0,
    duration_sec    INTEGER,
    distance_mi     REAL,
    tss             REAL,                     -- NULL for non-cycling / '--'
    work_kj         REAL,
    np_w            REAL,
    avg_hr_bpm      REAL,
    max_hr_bpm      REAL,
    cadence_rpm     REAL,
    if_             REAL,                     -- per-workout Intensity Factor (this IS a valid detector input)
    ef              REAL,
    vi              REAL,
    p5s_w           REAL,
    p1min_w         REAL,
    p5min_w         REAL,
    p10min_w        REAL,
    p20min_w        REAL,
    p1hr_w          REAL,
    p2hr_w          REAL,                     -- NULL where source column absent (partial-2026 / weekly)
    rpe             REAL,
    feeling         REAL,
    anaerobic_tis   REAL,
    aerobic_tis     REAL,
    pwhr_pct        REAL,
    source_file     TEXT NOT NULL
);
CREATE INDEX idx_workout_date ON workout(date);

-- Daily grain: ONE row per calendar day across the full span (no-ride days are explicit rows).
CREATE TABLE daily (
    date            TEXT PRIMARY KEY,         -- 'YYYY-MM-DD'
    year            INTEGER NOT NULL,
    is_projected    INTEGER NOT NULL DEFAULT 0, -- 1 = beyond the actual training horizon (last ride day).
                                                -- Wellness-only days do NOT extend the horizon.
    has_ride        INTEGER NOT NULL DEFAULT 0,
    num_workouts    INTEGER NOT NULL DEFAULT 0,

    -- Training aggregates (derived from `workout`).
    -- tss_sum SEMANTICS (non-negotiable): a no-ride / rest day on an ACTUAL date is 0, NOT NULL.
    --   0 = "trained zero"; NULL = "unknown / not tracked" (used only for is_projected days).
    --   Gap & ramp logic depends on this distinction.
    tss_sum         REAL,
    duration_sec    INTEGER,                  -- actual rest day = 0; projected = NULL
    distance_mi     REAL,
    work_kj         REAL,
    -- if_daily is DISPLAY-ONLY. Do NOT feed it into any detector. Monotony / distribution /
    -- intensity logic must derive from the daily tss_sum series and from workout-grain if_,
    -- never from this column. (Duration-weighted mean of per-workout IF; NULL on no-ride days.)
    if_daily        REAL,

    -- PMC daily metrics (from the PMC midnight 00:00 row; present on projected days too).
    atl             REAL,                     -- TSS/day
    ctl             REAL,                     -- TSS/day
    tsb             REAL,                     -- TSS/day
    mftp_w          REAL,
    frc_kj          REAL,
    pmax_w          REAL,
    pvo2max_w       REAL,                     -- modeled power at VO2max (Om3CP curve @5min); Strava pipeline only
    tte_sec         INTEGER,

    -- Wellness / body (from PMC intraday rows; sparse, nullable; absent in older years -> NULL).
    weight_lb       REAL,
    fat_pct         REAL,
    sickness        TEXT,
    hrv_7d_avg_ms   REAL,
    hrv_daily_ms    REAL,
    rhr_bpm         REAL,
    sleep_total_sec INTEGER,
    sleep_deep_sec  INTEGER,
    sleep_light_sec INTEGER,
    sleep_rem_sec   INTEGER,
    sleep_awake_sec INTEGER,

    -- Time-in-Zone (from Daily TiZ; nullable).
    tiz_pwr_z1_sec  INTEGER,
    tiz_pwr_z2_sec  INTEGER,
    tiz_pwr_z3_sec  INTEGER,
    tiz_pwr_z4_sec  INTEGER,
    tiz_pwr_z5_sec  INTEGER,
    tiz_pwr_z6_sec  INTEGER,
    tiz_hr_z1_sec   INTEGER,
    tiz_hr_z2_sec   INTEGER,
    tiz_hr_z3_sec   INTEGER,
    tiz_hr_z4_sec   INTEGER,
    tiz_hr_z5_sec   INTEGER,

    -- Per-day anomalies stamped by the validator (e.g. "tss_without_duration", "ctl_discontinuity").
    -- Findings survive at query time, not just in test output. ';'-separated; NULL = clean.
    data_flags      TEXT
);

-- Provenance / audit: one row per source sheet actually read.
CREATE TABLE ingest_meta (
    source_file     TEXT NOT NULL,
    sheet           TEXT NOT NULL,
    family          TEXT NOT NULL,            -- TH | PMC | TiZ | Week
    role            TEXT NOT NULL,            -- loaded | validation-only
    rows_read       INTEGER NOT NULL,
    rows_loaded     INTEGER NOT NULL,
    rows_rejected   INTEGER NOT NULL,
    date_min        TEXT,
    date_max        TEXT,
    loaded_at       TEXT NOT NULL
);

-- Queryable column documentation so the semantic rules survive outside this file.
CREATE TABLE column_doc (
    table_name      TEXT NOT NULL,
    column_name     TEXT NOT NULL,
    note            TEXT NOT NULL
);
INSERT INTO column_doc (table_name, column_name, note) VALUES
  ('daily','if_daily','DISPLAY-ONLY. Never an input to any detector. Monotony/distribution/intensity logic computes from daily.tss_sum and workout.if_, never from this column.'),
  ('daily','tss_sum','No-ride day on an actual date = 0 (trained zero), NOT NULL. NULL is reserved for is_projected days (unknown future).'),
  ('daily','is_projected','1 = date is beyond the actual training horizon (the last day with a real ride). Wellness-only days do not extend the horizon.'),
  ('daily','data_flags','Per-day anomalies stamped by the validator; '';''-separated; NULL = no anomaly.');
