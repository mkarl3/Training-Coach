"""Validator: round-trip checks, per-day anomaly stamping (-> daily.data_flags),
and a cross-check of computed aggregates against the Week-of-5/25 snapshot file.

Run after loader.build_database(). Anomalies are persisted into daily.data_flags so
findings survive at query time, not just in test output.
"""
import datetime
import glob
import os
import sqlite3

import openpyxl

from . import loader, parse

# Anomaly thresholds.
CTL_JUMP = 8.0       # CTL is a 42-day EWMA; day-over-day moves above this are suspect.
TSB_TOL = 1.5        # WKO convention: TSB[d] == CTL[d] - ATL[d] (same day), within rounding.
DUR_TOL_SEC = 90     # cross-check tolerance for durations
NUM_TOL = 1.0        # cross-check tolerance for TSS/CTL/ATL
TSS_IF_TOL = 0.15    # advisory: stored TSS vs duration_hr * IF^2 * 100, within +/-15%


def round_trip_checks(conn):
    """Structural invariants. Returns list of (name, ok, detail)."""
    out = []
    cur = conn.cursor()

    # 1. daily is a contiguous one-row-per-day spine.
    rows = [r[0] for r in cur.execute("SELECT date FROM daily ORDER BY date")]
    dmin, dmax = rows[0], rows[-1]
    expected = loader._all_days(dmin, dmax)
    out.append(("daily_contiguous_no_dupes", rows == expected,
                f"{len(rows)} rows, expected {len(expected)} unique contiguous days"))

    # 2. no-ride actual days are tss_sum=0 (never NULL).
    bad = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE is_projected=0 AND num_workouts=0 AND tss_sum IS NOT 0"
    ).fetchone()[0]
    out.append(("rest_days_are_zero_not_null", bad == 0, f"{bad} actual rest days not = 0"))

    # 3. projected days have tss_sum NULL (unknown, not 0).
    bad = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE is_projected=1 AND tss_sum IS NOT NULL"
    ).fetchone()[0]
    out.append(("projected_days_tss_null", bad == 0, f"{bad} projected days had non-NULL tss_sum"))

    # 4. daily tss_sum conserves workout TSS on actual days.
    daily_tss = cur.execute(
        "SELECT COALESCE(SUM(tss_sum),0) FROM daily WHERE is_projected=0"
    ).fetchone()[0]
    wk_tss = cur.execute(
        "SELECT COALESCE(SUM(COALESCE(w.tss,0)),0) FROM workout w "
        "JOIN daily d ON d.date=w.date WHERE d.is_projected=0"
    ).fetchone()[0]
    out.append(("tss_conserved_daily_vs_workout", abs(daily_tss - wk_tss) < 1e-6,
                f"daily={daily_tss} workout={wk_tss}"))

    # 5. num_workouts matches the workout table on actual days.
    mism = cur.execute(
        "SELECT COUNT(*) FROM daily d WHERE d.is_projected=0 AND d.num_workouts <> "
        "(SELECT COUNT(*) FROM workout w WHERE w.date=d.date)"
    ).fetchone()[0]
    out.append(("num_workouts_matches", mism == 0, f"{mism} days mismatched"))

    # 6. unit sanity: durations are non-negative ints; TiZ daily sum <= 24h.
    neg = cur.execute(
        "SELECT COUNT(*) FROM workout WHERE duration_sec IS NOT NULL AND duration_sec < 0"
    ).fetchone()[0]
    over = cur.execute(
        "SELECT COUNT(*) FROM daily WHERE COALESCE(tiz_pwr_z1_sec,0)+COALESCE(tiz_pwr_z2_sec,0)"
        "+COALESCE(tiz_pwr_z3_sec,0)+COALESCE(tiz_pwr_z4_sec,0)+COALESCE(tiz_pwr_z5_sec,0)"
        "+COALESCE(tiz_pwr_z6_sec,0) > 86400"
    ).fetchone()[0]
    out.append(("unit_sanity_durations", neg == 0 and over == 0,
                f"{neg} negative durations, {over} TiZ-days over 24h"))

    return out


def reconcile_tss_if_dates(conn, tol=TSS_IF_TOL):
    """Advisory: dates with a cycling workout whose stored TSS disagrees with
    duration_hr * IF^2 * 100 by more than `tol`. WKO5 is authoritative; nothing is
    edited or excluded — the date is merely flagged. Returns set of dates."""
    cur = conn.cursor()
    bad = set()
    for date, tss, iff, dur in cur.execute(
        "SELECT date, tss, if_, duration_sec FROM workout "
        "WHERE is_cycling=1 AND tss IS NOT NULL AND if_ IS NOT NULL "
        "AND duration_sec IS NOT NULL AND duration_sec > 0"
    ):
        expect = (dur / 3600.0) * iff * iff * 100.0
        if expect > 0 and abs(tss - expect) / expect > tol:
            bad.add(date)
    return bad


def stamp_anomalies(conn):
    """Detect per-day anomalies and write them to daily.data_flags. Returns {date: flags}."""
    cur = conn.cursor()
    tss_if_bad = reconcile_tss_if_dates(conn)
    rows = list(cur.execute(
        "SELECT date, is_projected, has_ride, num_workouts, tss_sum, duration_sec, "
        "ctl, atl, tsb FROM daily ORDER BY date"
    ))
    flags = {}
    prev = None
    for r in rows:
        (date, proj, has_ride, n, tss, dur, ctl, atl, tsb) = r
        fl = []
        if not proj:
            # TSS present but no duration recorded.
            if tss is not None and tss > 0 and (dur is None or dur == 0):
                fl.append("tss_without_duration")
            # Cycling workout(s) but zero aggregate TSS (missing/'--' TSS on a ride day).
            if has_ride and (tss is not None and tss == 0):
                fl.append("cycling_zero_tss")
            # Missing PMC load metric on an actual day.
            if ctl is None:
                fl.append("missing_ctl_actual")
            # CTL day-over-day discontinuity (42-day EWMA shouldn't jump).
            if prev and prev[1] == 0 and prev[6] is not None and ctl is not None:
                if abs(ctl - prev[6]) > CTL_JUMP:
                    fl.append("ctl_discontinuity")
            # TSB identity (WKO same-day convention): TSB == CTL - ATL.
            if ctl is not None and atl is not None and tsb is not None:
                if abs(tsb - (ctl - atl)) > TSB_TOL:
                    fl.append("tsb_inconsistent")
            # Advisory: stored TSS vs IF-implied TSS (WKO5 authoritative, not corrected).
            if date in tss_if_bad:
                fl.append("tss_if_mismatch")
        if fl:
            flags[date] = ";".join(fl)
        prev = r
    conn.executemany(
        "UPDATE daily SET data_flags=? WHERE date=?",
        [(v, k) for k, v in flags.items()],
    )
    conn.commit()
    return flags


def _find_week_file(exports_dir):
    for f in sorted(glob.glob(os.path.join(exports_dir, "*.xlsx"))):
        if os.path.basename(f).startswith("Week"):
            return f
    return None


def cross_check_week(conn, exports_dir):
    """Compare the daily table against the independent Week-of-5/25 snapshot.

    Each comparison is tagged 'fidelity' or 'reconcile':
      - fidelity  : must match. Proves the parser reads/aggregates consistently.
      - reconcile : PMC ATL/CTL/TSB on a date >= the ride horizon, where two source
                    exports legitimately disagree (the weekly snapshot holds stale,
                    then-current acute-load that the later yearly re-export recomputed).
                    Reported as an observation; does NOT fail the build.

    Returns list of (check, ok, detail, category).
    """
    out = []
    wf = _find_week_file(exports_dir)
    if not wf:
        out.append(("week_file_present", False, "no Week-of file found", "fidelity"))
        return out
    cur = conn.cursor()
    horizon = cur.execute("SELECT MAX(date) FROM workout WHERE is_cycling=1").fetchone()[0]
    wb = openpyxl.load_workbook(wf, data_only=True, read_only=False)
    try:
        for ws in wb.worksheets:
            title = ws.title.lower()
            if "pmc" in title:
                per_date, _ = loader.read_pmc(ws)
                for d, vals in per_date.items():
                    row = cur.execute("SELECT atl, ctl, tsb FROM daily WHERE date=?", (d,)).fetchone()
                    if not row:
                        out.append((f"pmc[{d}]_present", False, "date missing from daily", "fidelity"))
                        continue
                    for i, col in enumerate(("atl", "ctl", "tsb")):
                        wv, dv = vals.get(col), row[i]
                        if wv is None or dv is None:
                            continue
                        ok = abs(wv - dv) <= NUM_TOL
                        # Volatile recent acute-load past the horizon is allowed to diverge.
                        cat = "reconcile" if (horizon and d >= horizon) else "fidelity"
                        out.append((f"pmc[{d}].{col}", ok, f"week={wv} db={dv}", cat))
            elif "training" in title:
                recs = loader.read_training_history(ws, os.path.basename(wf))
                for w in recs:
                    d = w["date"]
                    row = cur.execute(
                        "SELECT COALESCE(SUM(COALESCE(tss,0)),0), COALESCE(SUM(COALESCE(duration_sec,0)),0) "
                        "FROM workout WHERE date=?", (d,)).fetchone()
                    if w["tss"] is not None:
                        ok = abs(w["tss"] - row[0]) <= NUM_TOL
                        out.append((f"th[{d}].tss", ok, f"week={w['tss']} db={row[0]}", "fidelity"))
                    if w["duration_sec"] is not None:
                        ok = abs(w["duration_sec"] - row[1]) <= DUR_TOL_SEC
                        out.append((f"th[{d}].dur", ok, f"week={w['duration_sec']} db={row[1]}", "fidelity"))
            elif "tiz" in title:
                per_date = loader.read_tiz(ws)
                for d, vals in per_date.items():
                    for col, wv in vals.items():
                        dv = cur.execute(f"SELECT {col} FROM daily WHERE date=?", (d,)).fetchone()
                        if dv is None or dv[0] is None:
                            continue
                        ok = abs(wv - dv[0]) <= DUR_TOL_SEC
                        out.append((f"tiz[{d}].{col}", ok, f"week={wv} db={dv[0]}", "fidelity"))
    finally:
        wb.close()
    return out


def run(db_path, exports_dir):
    """Run all validation, persist flags, and return a structured report."""
    conn = sqlite3.connect(db_path)
    try:
        rt = round_trip_checks(conn)
        flags = stamp_anomalies(conn)
        xc = cross_check_week(conn, exports_dir)
    finally:
        conn.close()
    fidelity = [c for c in xc if c[3] == "fidelity"]
    reconcile = [c for c in xc if c[3] == "reconcile"]
    return {
        "round_trip": rt,
        "flags": flags,
        "cross_check": xc,
        "cross_check_fidelity": fidelity,
        "cross_check_reconcile": reconcile,
        "round_trip_ok": all(ok for _, ok, _ in rt),
        "cross_check_ok": all(ok for _, ok, _, _ in fidelity),
    }
