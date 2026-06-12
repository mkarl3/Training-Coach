"""Detector tests — each fires correctly against THIS athlete's confirmed episodes.

HONEST FRAMING (brief): a green test proves the detector is correctly ENCODED against
the one example it was given — NOT that the fingerprint generalizes. Real validation
needs athlete #2. These tests do not assert the fingerprints are valid.

Confirmed episodes (user-signed-off):
  gap_unravel  early-warning : 2026-03-12..03-19, 2026-04-07..04-14
  under_load   retrospective : 2025-01..2025-03
  fragile_ftp  gauge         : 2024-07-21 (1h-2h gap 81W), 2025-07-16 (decoupling 15%)
  injury_spike tripwire      : 2023-04-15, 2024-04-20
  monotony     trend         : 2025-11-08..14
  overtraining               : NONE (negative-test only)
"""
import pandas as pd
import pytest

from wko_metrics import metrics, detectors
from wko_metrics.config import DETECTORS

REQUIRED_KEYS = {"mode_id", "variant", "severity", "detector_family", "window_start",
                 "window_end", "evidence", "discriminator_result", "data_flags", "priority"}


@pytest.fixture(scope="module")
def m(conn):
    return metrics.Metrics(conn)


def _covers(f, d):
    return f["window_start"] <= d <= f["window_end"]


def _pick(findings, mode=None, variant=None, date=None, sev=None):
    return [f for f in findings
            if (mode is None or f["mode_id"] == mode)
            and (variant is None or f["variant"] == variant)
            and (sev is None or f["severity"] == sev)
            and (date is None or _covers(f, date))]


# --------------------------------------------------------------------------- #
# Findings schema (the frozen contract)
# --------------------------------------------------------------------------- #
def test_every_finding_matches_frozen_schema(m):
    findings = detectors.run_all(m)
    assert findings
    for f in findings:
        assert set(f.keys()) == REQUIRED_KEYS, f
        assert f["variant"] in ("retrospective", "early_warning")
        assert f["severity"] in ("watch", "confirmed")
        assert f["detector_family"] in ("tripwire", "trend", "gauge")
        assert f["detector_family"] == DETECTORS.family[(f["mode_id"], f["variant"])]
        assert f["priority"] == DETECTORS.priority[f["mode_id"]]
        assert f["window_start"] <= f["window_end"]
        assert isinstance(f["evidence"], dict) and isinstance(f["discriminator_result"], dict)
        assert isinstance(f["data_flags"], list)
        for t in f["discriminator_result"].values():            # each discriminator test shape
            assert set(t.keys()) == {"passed", "value", "threshold"}


def test_detectors_emit_data_only_no_prose(m):
    # No free-text sentences leak into evidence values (data contract, not narration).
    for f in detectors.run_all(m):
        for v in f["evidence"].values():
            if isinstance(v, str):
                assert len(v.split()) <= 3, (f["mode_id"], v)   # dates/labels only, never sentences


# --------------------------------------------------------------------------- #
# 1. gap_unravel
# --------------------------------------------------------------------------- #
def test_gap_unravel_early_warning_fires_confirmed_on_crash(m):
    g = detectors.detect_gap_unravel(m)
    conf = [f for f in _pick(g, "gap_unravel", "early_warning", sev="confirmed")
            if "2026-02-15" <= f["window_end"] <= "2026-04-30"]
    assert conf, "the 2026 build-and-crash should fire a confirmed early-warning"
    assert conf[0]["evidence"]["zero_ride_streak_days"] >= DETECTORS.gap_confirmed_days
    assert conf[0]["discriminator_result"]["ctl_dropped"]["passed"]


def test_gap_crash_collapses_to_single_finding(m):
    # Hysteresis: the whole Feb-Apr 2026 crash surfaces as ONE confirmed finding (was ~7),
    # plus at most one preceding watch — not one per rest gap.
    g = detectors.detect_gap_unravel(m)
    crash = [f for f in _pick(g, "gap_unravel", "early_warning")
             if "2026-02-15" <= f["window_end"] <= "2026-05-01"]
    assert sum(f["severity"] == "confirmed" for f in crash) == 1
    assert sum(f["severity"] == "watch" for f in crash) <= 1
    assert len(crash) <= 2


def test_gap_fitness_gate_fires_on_build_crash_not_ordinary_dips(m):
    # The dynamic per-athlete fitness gate (CTL p80, as-of) must fire on the late-Feb-2026
    # build-and-crash but stay silent on the ordinary January-2026 rest dips (recent peak
    # 33-35, below the ~36 fitness line).
    g = detectors.detect_gap_unravel(m)
    ew = _pick(g, "gap_unravel", "early_warning")
    fires = {f["window_end"] for f in ew}
    # ordinary January dips did NOT fire
    assert not any("2026-01-01" <= d <= "2026-02-14" for d in fires), \
        "fitness gate should suppress ordinary January rest dips"
    # the build-and-crash (after the Feb peak) DID fire
    assert any("2026-02-15" <= d <= "2026-04-30" for d in fires), \
        "fitness gate should fire on the late-Feb-2026 build-and-crash"
    # every fire actually cleared the athlete's own fitness percentile
    for f in ew:
        assert f["evidence"]["recent_peak_ctl"] >= f["evidence"]["fitness_threshold"]


def test_gap_fitness_threshold_is_dynamic_and_self_scaling(m):
    # Not a hardcoded number: it's the athlete's own CTL percentile, and the as-of form
    # has no lookahead (it only rises/adapts from history-to-date).
    thr = m.ctl_percentile_threshold(DETECTORS.gap_fitness_percentile, as_of=True)
    feb = float(thr.loc["2026-02-24"])
    assert 34 <= feb <= 38                      # ~36 for this athlete, between dips and the build
    # dynamic, not a constant: the as-of percentile adapts as history accrues...
    assert thr.dropna().nunique() > 1
    # ...and it tracks the athlete's own CTL range (a real percentile, never outside it).
    assert m.ctl.min() <= feb <= m.ctl.max()


def test_gap_is_has_ride_not_tss_zero(m):
    # 2026-01-01 is a logged Road Bike with missing TSS (tss_sum==0 but has_ride==1).
    # It must NOT count as a gap day.
    streak = m.zero_ride_streak()
    assert float(m.daily.loc["2026-01-01", "tss_sum"]) == 0.0
    assert int(m.daily.loc["2026-01-01", "has_ride"]) == 1
    assert int(streak.loc["2026-01-01"]) == 0


def test_gap_unravel_retrospective_confirms_a_never_sustained_decline(m):
    g = detectors.detect_gap_unravel(m)
    assert _pick(g, "gap_unravel", "retrospective", sev="confirmed")
    # both variants are produced (two artifacts per mode)
    assert _pick(g, "gap_unravel", "early_warning") and _pick(g, "gap_unravel", "retrospective")


# --------------------------------------------------------------------------- #
# 2. under_load
# --------------------------------------------------------------------------- #
def test_under_load_fires_on_2025_flat_low(m):
    u = detectors.detect_under_load(m)
    hit = _pick(u, "under_load", date="2025-02-20", sev="confirmed")
    assert hit, "under_load should fire on the 2025-01..03 flat-low block"
    assert hit[0]["discriminator_result"]["no_peak_to_fall_from"]["passed"]


def test_under_load_does_not_fire_at_2023_peak(m):
    # 2023 built a genuine CTL peak (~50); the peak weeks are NOT never-built.
    u = detectors.detect_under_load(m)
    assert not _pick(u, "under_load", date="2023-05-01")


# --------------------------------------------------------------------------- #
# 3. overtraining — negative-test only (no positive episode in this athlete)
# --------------------------------------------------------------------------- #
def test_overtraining_does_not_fire(m):
    assert detectors.detect_overtraining(m) == []


# --------------------------------------------------------------------------- #
# 4. fragile_ftp (gauge) + data_flags propagation
# --------------------------------------------------------------------------- #
def test_fragile_power_duration_leg(m):
    fr = detectors.detect_fragile_ftp(m)
    hit = _pick(fr, "fragile_ftp", date="2024-07-21", sev="confirmed")
    assert hit and hit[0]["detector_family"] == "gauge"
    assert hit[0]["evidence"]["gap_1h_2h_w"] == pytest.approx(81.0)


def test_fragile_decoupling_leg(m):
    fr = detectors.detect_fragile_ftp(m)
    hit = _pick(fr, "fragile_ftp", date="2025-07-16", sev="confirmed")
    assert hit and hit[0]["evidence"]["decoupling_pct"] == pytest.approx(15.12, abs=0.1)


def test_advisory_flag_travels_into_finding(m):
    # 2024-07-21 is a tss_if_mismatch day; any finding whose window touches it carries it.
    fr = detectors.detect_fragile_ftp(m)
    hit = _pick(fr, "fragile_ftp", date="2024-07-21")[0]
    assert "tss_if_mismatch" in hit["data_flags"]
    # and a clean day carries no flag
    assert detectors.detect_fragile_ftp(m) and "tss_if_mismatch" not in \
        _pick(fr, "fragile_ftp", date="2025-07-16")[0]["data_flags"]


# --------------------------------------------------------------------------- #
# 5. injury_spike — tripwire, load-signal only, hysteresis
# --------------------------------------------------------------------------- #
def test_injury_spike_fires_on_known_spikes(m):
    inj = detectors.detect_injury_spike(m)
    assert _pick(inj, "injury_spike", "early_warning", "2023-04-15", "confirmed")
    assert _pick(inj, "injury_spike", "retrospective", "2023-04-15", "confirmed")
    assert _pick(inj, "injury_spike", date="2024-04-20", sev="confirmed")


def test_injury_is_load_signal_only(m):
    # Discriminators reference LOAD only — never tissue/diagnosis terms.
    for f in detectors.detect_injury_spike(m):
        keys = set(f["discriminator_result"])
        assert keys <= {"acwr_crossing", "acute_load_gate", "consequent_stop"}


def test_injury_hysteresis_dedupes_clusters(m):
    inj = detectors.detect_injury_spike(m)
    early_conf_days = sorted(f["window_start"] for f in
                             _pick(inj, "injury_spike", "early_warning", sev="confirmed"))
    # Fewer confirmed fires than days above 1.5 — clusters are collapsed, not re-fired daily.
    days_above = int((m.acwr()["acwr"] >= DETECTORS.acwr_confirmed).sum())
    assert 0 < len(early_conf_days) < days_above
    # The real hysteresis guarantee: no two confirmed fires on adjacent days (one per cluster).
    for a, b in zip(early_conf_days, early_conf_days[1:]):
        assert (pd.Timestamp(b) - pd.Timestamp(a)).days >= 2


# --------------------------------------------------------------------------- #
# 6. monotony
# --------------------------------------------------------------------------- #
def test_monotony_fires_on_2025_11_peak(m):
    mo = detectors.detect_monotony(m)
    conf = [f for f in _pick(mo, "monotony", sev="confirmed")
            if "2025-11-08" <= f["window_start"] <= "2025-11-14"]
    assert conf and conf[0]["evidence"]["monotony"] >= DETECTORS.monotony_confirmed


# --------------------------------------------------------------------------- #
# Ranking — action priority is distinct from diagnosis
# --------------------------------------------------------------------------- #
def test_action_rank_orders_by_priority_then_severity():
    fake = [
        {"mode_id": "fragile_ftp", "priority": 6, "severity": "confirmed", "window_end": "2025-01-01"},
        {"mode_id": "injury_spike", "priority": 1, "severity": "watch", "window_end": "2025-01-01"},
        {"mode_id": "under_load", "priority": 4, "severity": "confirmed", "window_end": "2025-01-01"},
    ]
    ranked = detectors.action_rank(fake)
    assert [f["mode_id"] for f in ranked] == ["injury_spike", "under_load", "fragile_ftp"]


def test_reset_conditions_defined_for_every_mode():
    # Every detector declares a reset/exit condition (Slice-2 consumes these).
    assert set(DETECTORS.reset_conditions) == set(DETECTORS.priority)
