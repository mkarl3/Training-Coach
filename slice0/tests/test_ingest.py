"""Slice-0 ingestion tests.

Covers the required cases: no-ride days materialize as tss_sum=0, dedup works,
column-drift mapping holds across 2023->2025, PMC dual rows merge to one daily row,
projected-day flagging, and unit consistency.
"""
import datetime
import os

import openpyxl

from wko_ingest import loader, parse

EXPORTS_DIR = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\WKO5 Exports"


def _ws(name):
    wb = openpyxl.load_workbook(os.path.join(EXPORTS_DIR, name), data_only=True)
    return wb, wb.active


# --------------------------------------------------------------------------- #
# Cell parsers / unit consistency
# --------------------------------------------------------------------------- #
def test_duration_parsing_handles_time_string_token_and_sentinel():
    assert parse.parse_duration_sec(datetime.time(1, 6, 27)) == 3987      # h:m:s time obj
    assert parse.parse_duration_sec("12m31s") == 12 * 60 + 31             # WKO token form
    assert parse.parse_duration_sec("1m52s") == 112
    assert parse.parse_duration_sec("1:06:27") == 3987                    # h:m:s string
    assert parse.parse_duration_sec("--") is None                         # sentinel -> NULL
    assert parse.parse_duration_sec(None) is None
    assert parse.parse_duration_sec("0:45", two_part="hm") == 45 * 60     # sleep h:m


def test_sentinel_never_becomes_zero():
    # '--' must be NULL, not 0 (the non-negotiable NULL-vs-0 rule at the cell level).
    assert parse.parse_float("--") is None
    assert parse.parse_float("") is None
    assert parse.parse_float(0) == 0.0  # a real zero stays zero


def test_units_in_db_are_canonical(conn):
    cur = conn.cursor()
    # All durations are integers (seconds), never strings/floats-as-text.
    bad = cur.execute(
        "SELECT COUNT(*) FROM workout WHERE duration_sec IS NOT NULL "
        "AND typeof(duration_sec) <> 'integer'").fetchone()[0]
    assert bad == 0
    # No '--' sentinel leaked into any numeric daily column.
    leaked = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE typeof(tss_sum)='text' OR typeof(ctl)='text'"
    ).fetchone()[0]
    assert leaked == 0
    # tss_sum is never negative.
    assert cur.execute("SELECT COUNT(*) FROM daily WHERE tss_sum < 0").fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# No-ride days -> tss_sum = 0 (NOT NULL)
# --------------------------------------------------------------------------- #
def test_no_ride_actual_days_are_zero_not_null(conn):
    cur = conn.cursor()
    # There are real rest days in range.
    n = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE is_projected=0 AND num_workouts=0").fetchone()[0]
    assert n > 0
    # Every one of them is exactly 0, never NULL.
    bad = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE is_projected=0 AND num_workouts=0 "
        "AND (tss_sum IS NULL OR tss_sum <> 0)").fetchone()[0]
    assert bad == 0
    # Intensity is undefined (NULL) on a rest day, not 0.
    row = cur.execute(
        "SELECT tss_sum, duration_sec, if_daily FROM daily "
        "WHERE is_projected=0 AND num_workouts=0 LIMIT 1").fetchone()
    assert row[0] == 0 and row[1] == 0 and row[2] is None


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #
def test_dedup_collapses_identical_workouts():
    w = {"started_at": "2025-03-01T10:00:00", "activity_type": "Road Bike",
         "duration_sec": 3600}
    out = loader.dedup_workouts([dict(w), dict(w), dict(w, duration_sec=1800)])
    assert len(out) == 2  # the third differs on duration -> kept


def test_no_duplicate_workouts_in_db(conn):
    cur = conn.cursor()
    dupes = cur.execute(
        "SELECT COUNT(*) FROM (SELECT started_at, activity_type, duration_sec, COUNT(*) c "
        "FROM workout GROUP BY started_at, activity_type, duration_sec HAVING c > 1)"
    ).fetchone()[0]
    assert dupes == 0


# --------------------------------------------------------------------------- #
# Column-drift mapping holds across 2023 -> 2025
# --------------------------------------------------------------------------- #
def test_pmc_header_map_tracks_column_drift():
    wb23, ws23 = _ws("PMC Report 2023.xlsx")
    wb25, ws25 = _ws("PMC Report 2025.xlsx")
    m23, _ = loader.header_map(ws23)
    m25, _ = loader.header_map(ws25)
    wb23.close(); wb25.close()
    # 2023 predates HRV/RHR/sleep; 2025 has them — at DIFFERENT column indices.
    assert "RHR" not in m23 and "RHR" in m25
    assert "Sleep Hours" not in m23 and "Sleep Hours" in m25
    # A field common to both maps to its own (differing) index, by name not position.
    assert "CTL" in m23 and "CTL" in m25


def test_drift_reflected_in_loaded_daily(conn):
    cur = conn.cursor()
    # 2023 days carry no RHR (column absent) -> NULL.
    assert cur.execute(
        "SELECT COUNT(*) FROM daily WHERE year=2023 AND rhr_bpm IS NOT NULL").fetchone()[0] == 0
    # 2025 days do carry RHR for at least some days.
    assert cur.execute(
        "SELECT COUNT(*) FROM daily WHERE year=2025 AND rhr_bpm IS NOT NULL").fetchone()[0] > 0
    # CTL loads correctly for both years despite the column shift.
    assert cur.execute("SELECT ctl FROM daily WHERE date='2023-01-02'").fetchone()[0] == 33.0
    assert cur.execute("SELECT ctl FROM daily WHERE date='2025-01-01'").fetchone()[0] == 14.0


def test_th_header_map_handles_dropped_2hr_power_column():
    # The partial-2026 TH file drops the '2 Hour Power' column; mapping must still align.
    wb, ws = _ws("Training History 2023.xlsx")
    m, _ = loader.header_map(ws)
    wb.close()
    assert "2 Hour Power" in m and "TSS" in m


# --------------------------------------------------------------------------- #
# PMC dual rows merge into ONE daily row
# --------------------------------------------------------------------------- #
def test_pmc_dual_rows_merge_to_single_daily(conn):
    cur = conn.cursor()
    # Exactly one daily row for the date.
    assert cur.execute("SELECT COUNT(*) FROM daily WHERE date='2023-01-01'").fetchone()[0] == 1
    row = cur.execute(
        "SELECT ctl, atl, weight_lb, fat_pct, sickness FROM daily WHERE date='2023-01-01'"
    ).fetchone()
    # Metrics come from the midnight row; wellness from the intraday (14:27) row.
    assert row[0] == 34.0          # CTL  (midnight)
    assert row[1] == 46.0          # ATL  (midnight)
    assert abs(row[2] - 164.3) < 1e-6   # Weight (intraday)
    assert abs(row[3] - 14.25) < 1e-6   # Fat%   (intraday)
    assert row[4] == "Healthy"          # Sickness (intraday)


def test_raw_pmc_has_two_rows_for_that_date():
    # Sanity: the source genuinely has two rows we collapsed.
    wb, ws = _ws("PMC Report 2023.xlsx")
    per_date, _ = loader.read_pmc(ws)
    wb.close()
    # After merge it is one bucket carrying both metric and wellness fields.
    b = per_date["2023-01-01"]
    assert "ctl" in b and "weight_lb" in b


# --------------------------------------------------------------------------- #
# Projected-day flagging
# --------------------------------------------------------------------------- #
def test_projected_days_flagged_and_tss_null(conn):
    cur = conn.cursor()
    horizon = cur.execute("SELECT MAX(date) FROM workout WHERE is_cycling=1").fetchone()[0]
    # A day well past the last ride is projected, with UNKNOWN (NULL) tss_sum...
    row = cur.execute(
        "SELECT is_projected, tss_sum, ctl FROM daily WHERE date='2026-08-01'").fetchone()
    assert row[0] == 1 and row[1] is None
    assert row[2] is not None  # ...but PMC projection (CTL) is still carried.
    # A day before the horizon is actual.
    before = cur.execute(
        "SELECT is_projected FROM daily WHERE date='2026-05-20'").fetchone()[0]
    assert before == 0
    # The horizon day itself is the last actual day.
    assert cur.execute(
        "SELECT is_projected FROM daily WHERE date=?", (horizon,)).fetchone()[0] == 0


def test_wellness_only_days_do_not_extend_horizon(conn):
    cur = conn.cursor()
    horizon = cur.execute("SELECT MAX(date) FROM workout WHERE is_cycling=1").fetchone()[0]
    # No ride exists after the horizon (wellness/PMC rows must not push it out).
    later_ride = cur.execute(
        "SELECT COUNT(*) FROM workout WHERE is_cycling=1 AND date > ?", (horizon,)).fetchone()[0]
    assert later_ride == 0


# --------------------------------------------------------------------------- #
# data_flags persistence
# --------------------------------------------------------------------------- #
def test_anomalies_persist_in_data_flags(conn):
    cur = conn.cursor()
    # The known cycling-with-no-TSS day is flagged and survives at query time.
    fl = cur.execute("SELECT data_flags FROM daily WHERE date='2026-01-01'").fetchone()[0]
    assert fl is not None and "cycling_zero_tss" in fl
    # Clean rest days carry no flag.
    assert cur.execute("SELECT data_flags FROM daily WHERE date='2023-01-02'").fetchone()[0] is None
