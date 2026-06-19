"""Metrics tests: synthetic hand-checked cases for every pure function (including
gating), plus real-date integration checks against this athlete's data."""
import numpy as np
import pandas as pd
import pytest

from wko_metrics import MetricsConfig, metrics


def days(n, start="2025-01-01"):
    return pd.date_range(start, periods=n, freq="D")


# --------------------------------------------------------------------------- #
# Ramp rate
# --------------------------------------------------------------------------- #
def test_ramp_rate_linear_ctl():
    # CTL rising 1/day -> +7 over a 7-day window -> 7 pts/week.
    ctl = pd.Series(np.arange(10, 18, dtype=float), index=days(8))
    r = metrics.ramp_rate(ctl, 7)
    assert pd.isna(r.iloc[6])              # not enough history yet
    assert r.iloc[7] == pytest.approx(7.0)


def test_ramp_rate_window_scaling():
    # 14-day window of +1/day -> +14 over 14 days -> still 7 pts/week.
    ctl = pd.Series(np.arange(0, 15, dtype=float), index=days(15))
    assert metrics.ramp_rate(ctl, 14).iloc[14] == pytest.approx(7.0)


# --------------------------------------------------------------------------- #
# Foster monotony & strain
# --------------------------------------------------------------------------- #
def test_monotony_matches_definition():
    loads = pd.Series([36, 63, 0, 0, 0, 41, 85], index=days(7), dtype=float)
    a = loads.to_numpy()
    expected = a.mean() / a.std(ddof=0)
    assert metrics.foster_monotony(loads, 7, ddof=0).iloc[6] == pytest.approx(expected)


def test_strain_is_weekly_load_times_monotony():
    loads = pd.Series([36, 63, 0, 0, 0, 41, 85], index=days(7), dtype=float)
    mono = metrics.foster_monotony(loads, 7, ddof=0).iloc[6]
    assert metrics.foster_strain(loads, 7, ddof=0).iloc[6] == pytest.approx(loads.sum() * mono)


def test_monotony_flat_window_is_nan_not_inf():
    # SD==0 must be undefined (NaN), never infinity.
    loads = pd.Series([50.0] * 7, index=days(7))
    assert pd.isna(metrics.foster_monotony(loads, 7, ddof=0).iloc[6])


def test_rest_days_are_real_inputs():
    # A week with rest days has lower monotony than a flat-busy week (zeros count).
    busy = pd.Series([50, 50, 50, 50, 50, 50, 60], index=days(7), dtype=float)
    spiky = pd.Series([50, 0, 50, 0, 50, 0, 60], index=days(7), dtype=float)
    assert (metrics.foster_monotony(busy, 7).iloc[6]
            > metrics.foster_monotony(spiky, 7).iloc[6])


# --------------------------------------------------------------------------- #
# ACWR (EWMA)
# --------------------------------------------------------------------------- #
def test_acwr_ewma_matches_recursive_definition():
    rng = pd.Series(np.linspace(10, 100, 40), index=days(40))

    def ewma(a, span):
        al = 2.0 / (span + 1)
        out = np.empty_like(a)
        out[0] = a[0]
        for i in range(1, len(a)):
            out[i] = al * a[i] + (1 - al) * out[i - 1]
        return out

    arr = rng.to_numpy()
    out = metrics.acwr_ewma(rng, 7, 28, min_days=28)
    assert out["acute"].iloc[35] == pytest.approx(ewma(arr, 7)[35])
    assert out["chronic"].iloc[35] == pytest.approx(ewma(arr, 28)[35])
    assert out["acwr"].iloc[35] == pytest.approx(ewma(arr, 7)[35] / ewma(arr, 28)[35])


def test_acwr_gated_until_min_days():
    rng = pd.Series(np.ones(40), index=days(40))
    out = metrics.acwr_ewma(rng, 7, 28, min_days=28)
    assert out["acwr"].iloc[:28].isna().all()
    assert out["acwr"].iloc[28:].notna().all()


# --------------------------------------------------------------------------- #
# TSB trajectory
# --------------------------------------------------------------------------- #
def test_tsb_slope_and_direction():
    rising = pd.Series(2.0 * np.arange(14) + 5, index=days(14))
    out = metrics.tsb_trajectory(rising, 14, flat_eps=0.10)
    assert out["tsb_slope"].iloc[13] == pytest.approx(2.0)
    assert out["tsb_direction"].iloc[13] == "rising"

    flat = pd.Series([3.0] * 14, index=days(14))
    assert metrics.tsb_trajectory(flat, 14, 0.10)["tsb_direction"].iloc[13] == "flat"

    falling = pd.Series(-1.5 * np.arange(14), index=days(14))
    assert metrics.tsb_trajectory(falling, 14, 0.10)["tsb_direction"].iloc[13] == "falling"


# --------------------------------------------------------------------------- #
# Aerobic decoupling — gating
# --------------------------------------------------------------------------- #
def test_decoupling_gates_short_rides_and_missing_data():
    w = pd.DataFrame([
        # long ride, full data -> sufficient, decoupled (>5%)
        dict(date="2025-01-01", started_at="a", is_cycling=1, duration_sec=10000,
             pwhr_pct=6.0, avg_hr_bpm=150, np_w=200),
        # long ride, missing pwHr -> included but insufficient
        dict(date="2025-01-02", started_at="b", is_cycling=1, duration_sec=11000,
             pwhr_pct=None, avg_hr_bpm=150, np_w=200),
        # short ride -> excluded entirely
        dict(date="2025-01-03", started_at="c", is_cycling=1, duration_sec=3000,
             pwhr_pct=4.0, avg_hr_bpm=150, np_w=200),
    ])
    out = metrics.aerobic_decoupling(w, long_ride_min_sec=9000, high_pct=5.0)
    assert set(out["started_at"]) == {"a", "b"}            # short ride gated out
    a = out[out["started_at"] == "a"].iloc[0]
    b = out[out["started_at"] == "b"].iloc[0]
    assert a["sufficient"] and a["decoupling_pct"] == 6.0 and a["decoupled"] is True
    assert (not b["sufficient"]) and pd.isna(b["decoupling_pct"])


# --------------------------------------------------------------------------- #
# Power-duration — gating
# --------------------------------------------------------------------------- #
def test_power_duration_gated_when_no_2hr_sample():
    w = pd.DataFrame([
        dict(date="2025-01-01", started_at="a", is_cycling=1, p1hr_w=200.0, p2hr_w=180.0),
        dict(date="2025-01-02", started_at="b", is_cycling=1, p1hr_w=190.0, p2hr_w=None),
    ])
    out = metrics.power_duration_ratio(w)
    a = out[out["started_at"] == "a"].iloc[0]
    b = out[out["started_at"] == "b"].iloc[0]
    assert a["sufficient"] and a["pd_ratio_1h_2h"] == pytest.approx(200 / 180)
    assert a["pd_gap_1h_2h_w"] == pytest.approx(20.0)
    assert (not b["sufficient"]) and pd.isna(b["pd_ratio_1h_2h"])


# --------------------------------------------------------------------------- #
# Time-in-zone distribution
# --------------------------------------------------------------------------- #
def test_tiz_shares_sum_to_one_and_gate_zero_total():
    df = pd.DataFrame({
        "z1_sec": [60, 0, 0],
        "z2_sec": [60, 0, 120],
    }, index=days(3))
    out = metrics.tiz_distribution(df, ["z1_sec", "z2_sec"], window_days=1)
    assert out.iloc[0].sum() == pytest.approx(1.0)
    assert out.iloc[0]["z1_share"] == pytest.approx(0.5)
    assert out.iloc[1].isna().all()                    # zero total -> NaN, not 0/0 error
    assert out.iloc[2]["z2_share"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Config is the single source of constants (no inline literals)
# --------------------------------------------------------------------------- #
def test_config_window_changes_output(conn):
    m7 = metrics.Metrics(conn, MetricsConfig(ramp_window_days=7))
    m14 = metrics.Metrics(conn, MetricsConfig(ramp_window_days=14))
    # Different configured window -> different ramp series (proves no hard-coded 7).
    assert not m7.ramp_rate().equals(m14.ramp_rate())


# --------------------------------------------------------------------------- #
# Real-date integration checks (mirror verify.py)
# --------------------------------------------------------------------------- #
def test_integration_known_dates(conn):
    m = metrics.Metrics(conn)
    assert float(m.ramp_rate().loc["2025-03-15"]) == pytest.approx(2.0)
    assert float(m.monotony().loc["2025-03-15"]) == pytest.approx(1.020915, abs=1e-5)
    assert float(m.acwr().loc["2025-03-15"]["acwr"]) == pytest.approx(1.454797, abs=1e-5)
    dec = m.decoupling()
    row = dec[dec["started_at"] == "2023-08-05T06:17:00"].iloc[0]
    assert float(row["decoupling_pct"]) == pytest.approx(5.78)


def test_floor_no_lookahead_asof():
    # Weekly CTL flat at 30, then a sustained 45-block only in the last 10 weeks.
    wk = [30.0] * 30 + [45.0] * 10
    idx = pd.date_range("2024-01-07", periods=len(wk), freq="W")
    # expand weekly -> daily so resample('W') reproduces the weekly values
    ctl = pd.Series(wk, index=idx).resample("D").ffill()
    f = metrics.demonstrated_sustainable_floor(ctl, hold_weeks=8, window_weeks=78, as_of=True)
    fw = f.resample("W").last()
    # Before the 45-block is held 8 wks, the as-of floor must NOT know about 45.
    assert fw.iloc[20] == pytest.approx(30.0)          # mid early period
    # Only after 8 consecutive 45-weeks does the floor rise to 45 (no lookahead leak).
    assert fw.iloc[-1] == pytest.approx(45.0)
    assert fw.iloc[31] == pytest.approx(30.0)          # one 45-week in: 8-wk min still 30


def test_floor_retrospective_is_best_held_base():
    wk = [30.0] * 30 + [45.0] * 10
    idx = pd.date_range("2024-01-07", periods=len(wk), freq="W")
    ctl = pd.Series(wk, index=idx).resample("D").ffill()
    f = metrics.demonstrated_sustainable_floor(ctl, 8, 78, as_of=False)
    assert f.iloc[0] == pytest.approx(45.0)            # constant = best base ever held


def test_floor_real_athlete_best_held_base(conn):
    m = metrics.Metrics(conn)
    # Retrospective best-ever-held base lands in the high-30s/low-40s (data-derived, unvalidated).
    assert float(m.personal_ctl_floor().iloc[-1]) == pytest.approx(41.0, abs=2.0)
    # As-of floor never exceeds the retrospective best, by construction (NaN warm-up dropped).
    asof = m.personal_ctl_floor_asof()
    retro = m.personal_ctl_floor()
    assert (asof.dropna() <= retro.loc[asof.dropna().index] + 1e-9).all()
    # The high base aged out of the trailing window: today's as-of floor < all-time best.
    assert float(asof.iloc[-1]) < float(retro.iloc[-1])


def test_sustainable_ramp_excludes_the_crash_and_caps():
    # Two +4/wk climbs: the first is HELD (sustained), the second CRASHES back (spike-then-
    # crash). Only the sustained climb should count -> p75 of {4,4,4} = 4, then capped to 3.
    wk = pd.date_range("2025-01-05", periods=14, freq="W")
    ctl = pd.Series([20, 24, 28, 32, 32, 32, 32,      # climb +4*3 then HELD flat
                     36, 40, 44, 20, 20, 20, 20],     # climb +4*3 then CRASH back to 20
                    index=wk, dtype=float)
    floor = pd.Series(40.0, index=wk)                  # gate = 20; all weeks qualify
    # uncapped: the three sustained +4 gains survive; the crash climb's gains are dropped
    assert metrics.demonstrated_sustainable_ramp(ctl, floor, ramp_cap=99, percentile=75) == 4.0
    # the profile cap binds the result
    assert metrics.demonstrated_sustainable_ramp(ctl, floor, ramp_cap=3.0, percentile=75) == 3.0
    # thin history -> None (caller falls back to a method default)
    assert metrics.demonstrated_sustainable_ramp(ctl.iloc[:4], floor.iloc[:4], 99) is None


def test_sustainable_ramp_real_athlete(conn):
    m = metrics.Metrics(conn)
    psr = m.personal_sustainable_ramp()
    assert psr is not None and 0 < psr <= m.profile.ramp_rate_cap
    # demonstrated-safe, not historical max: well under the spike-crash ceiling, and monotonic
    assert m.personal_sustainable_ramp(percentile=50) <= psr <= m.personal_sustainable_ramp(percentile=90)
    assert m.personal_sustainable_ramp() == m.personal_sustainable_ramp()   # deterministic


def test_safe_acute_ratio_excludes_the_crash():
    # one step-up that HELD (safe) and one of the same size that COLLAPSED after (spike-then-crash).
    # Only the sustained one counts -> the demonstrated-safe ratio is the safe jump, not the crash.
    wk = pd.date_range("2025-01-05", periods=13, freq="W")
    tss = pd.Series([100, 100, 100, 100, 150,           # +50% jump that HOLDS -> safe (1.5)
                     100, 100, 100, 100, 150,           # +50% jump that then...
                     60, 60, 60],                       # ...COLLAPSES -> excluded
                    index=wk, dtype=float)
    assert metrics.demonstrated_safe_acute_ratio(tss, min_chronic=20, percentile=75) == 1.5
    assert metrics.demonstrated_safe_acute_ratio(tss.iloc[:5], min_chronic=20) is None   # thin history


def test_safe_acute_ratio_real_athlete(conn):
    m = metrics.Metrics(conn)
    r = m.personal_safe_acute_ratio()
    assert r is None or r >= 1.0                        # a ratio, derived from summed actual TSS


def test_readiness_from_form_is_a_tighten_only_backstop(conn):
    m = metrics.Metrics(conn)
    r = m.readiness_from_form()
    assert 0.7 <= r <= 1.0                              # 0..1 ease factor, never amplifies


def test_projected_days_excluded_from_series(conn):
    m = metrics.Metrics(conn)
    # Daily index ends at the actual horizon; no 2026-08-01 projected row leaks in.
    assert pd.Timestamp("2026-08-01") not in m.daily.index
