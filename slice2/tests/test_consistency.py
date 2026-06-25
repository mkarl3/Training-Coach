"""Consistency Gauge tests (handoff §10.4). Frozen heart logic via pure helpers; flag/stand-down
equivalence via the real-data fixtures (conftest `m` + `findings`). The gauge must REFLECT the
gap_unravel detector, never decide the flag itself."""
import pandas as pd
import pytest

from wko_metrics.config import DETECTORS
from watchman import consistency_gauge, select, reset_satisfied
from watchman.consistency import (
    derive_hearts, consecutive_miss_weeks, clean_week_streak,
    HEART_COLOR, WATTSON_MOOD, ZONE_BY_HEARTS,
)

MIN = 3   # fixed threshold for the pure-helper LOGIC tests (intentionally decoupled from the
          # live config value, which Mike tunes; the integration tests use the real constant)


def _has_ride(pattern, end="2026-06-10"):
    """Daily 0/1 has_ride Series ending at `end` (oldest first)."""
    idx = pd.date_range(end=end, periods=len(pattern), freq="D")
    return pd.Series(pattern, index=idx)


# ---------------- FROZEN heart logic (pure, no m) ----------------
def test_color_and_tone_maps_frozen():
    assert HEART_COLOR == {4: "red", 3: "red", 2: "yellow", 1: "flash"}
    assert WATTSON_MOOD == {"healthy": "approving", "caution": "calm", "warn": "alarmed", "flag": "alarmed"}
    assert ZONE_BY_HEARTS == {4: "healthy", 3: "caution", 2: "warn"}


def test_buffer_derivation_0_1_2_misses():
    assert derive_hearts(False, 0) == (4, "healthy")
    assert derive_hearts(False, 1) == (3, "caution")
    assert derive_hearts(False, 2) == (2, "warn")


def test_buffer_clamps_at_2_never_1_or_0():
    for misses in range(2, 12):
        hearts, zone = derive_hearts(False, misses)
        assert hearts == 2 and zone == "warn"        # never 1, never 0


def test_detector_wins_on_conflict():
    # buffer would be 4 (0 misses) but the flag forces 1
    assert derive_hearts(True, 0) == (1, "flag")
    assert derive_hearts(True, 9) == (1, "flag")


def test_zero_is_unreachable():
    assert all(derive_hearts(False, k)[0] >= 2 for k in range(0, 20))
    assert all(derive_hearts(True, k)[0] == 1 for k in range(0, 20))


def test_exit_from_flag_lands_at_2_then_climbs():
    # exit_cap = 2 + clean weeks since the stand-down boundary
    assert derive_hearts(False, 0, exit_cap=2) == (2, "warn")    # the stand-down boundary
    assert derive_hearts(False, 0, exit_cap=3) == (3, "caution")  # +1 clean week
    assert derive_hearts(False, 0, exit_cap=4) == (4, "healthy")  # full
    # a large historical clean run cannot re-derive >2 while the cap binds
    assert derive_hearts(False, 0, exit_cap=2) == (2, "warn")


# ---------------- predicate helpers (synthetic series) ----------------
def test_miss_and_clean_week_predicate():
    clean_wk = [1, 1, 1, 0, 0, 0, 1]      # 4 ride days ≥ MIN(3) → clean
    miss_wk = [1, 0, 0, 0, 0, 0, 1]       # 2 ride days < 3 → miss
    assert consecutive_miss_weeks(_has_ride(clean_wk), pd.Timestamp("2026-06-10"), MIN) == 0
    assert consecutive_miss_weeks(_has_ride(miss_wk), pd.Timestamp("2026-06-10"), MIN) == 1


def test_consecutive_miss_weeks_counts_back_then_stops():
    # newest→: miss, miss, clean (oldest). 14 days = 2 weeks of misses then a clean week
    pattern = [1, 1, 1, 0, 0, 0, 0] + [0, 1, 0, 0, 0, 0, 0] + [1, 0, 0, 0, 0, 0, 0]
    s = _has_ride(pattern)
    assert consecutive_miss_weeks(s, pd.Timestamp("2026-06-10"), MIN) == 2


def test_streak_resets_on_miss():
    # three clean weeks then (older) a miss — streak counts only the clean run from today
    pattern = [0, 1, 0, 0, 0, 0, 0] + [1, 1, 1, 0, 0, 0, 1] + [1, 1, 1, 0, 1, 0, 0] + [1, 1, 1, 0, 0, 1, 0]
    s = _has_ride(pattern)
    streak = clean_week_streak(s, pd.Timestamp("2026-06-10"), MIN)
    assert streak == 3       # the oldest week is a miss → streak stops there
    # a miss in the most recent week → streak 0
    s2 = _has_ride([1, 1, 1, 1, 0, 0, 0] + [0, 1, 0, 0, 0, 0, 0])  # newest week = 1 ride day = miss
    assert clean_week_streak(s2, pd.Timestamp("2026-06-10"), MIN) == 0


# ---------------- integration vs the real detector (conftest m + findings) ----------------
def test_determinism(findings, m):
    a = consistency_gauge(findings, "2026-06-10", m)
    b = consistency_gauge(findings, "2026-06-10", m)
    assert a == b


def test_flagged_reflects_select_exactly(findings, m):
    """flagged ⟺ select() surfaces a confirmed, non-provisional gap_unravel tripwire — checked
    across many dates so it can never silently diverge from the detector (ownership invariant)."""
    for d in pd.date_range("2024-01-01", "2026-06-14", freq="17D"):
        sel = select(findings, d, m)
        expected = any(t["mode_id"] == "gap_unravel" and t["severity"] == "confirmed"
                       and not t["provisional"] for t in sel["tripwires"])
        g = consistency_gauge(findings, d, m)
        assert g["flagged"] == expected
        if g["flagged"]:
            assert g["hearts"] == 1 and g["zone"] == "flag"
            assert g["source_finding"] is not None and g["source_finding"]["mode_id"] == "gap_unravel"
        else:
            assert 2 <= g["hearts"] <= 4 and g["source_finding"] is None


def test_flag_branch_is_exercised_somewhere(findings, m):
    """There IS at least one date where the flag fires (otherwise the above test is vacuous)."""
    fired = any(consistency_gauge(findings, d, m)["flagged"]
                for d in pd.date_range("2024-01-01", "2026-06-14", freq="7D"))
    assert fired, "expected gap_unravel to flag on at least one date in the athlete's history"


def test_standdown_binds_to_reset_satisfied(findings, m):
    """When flagged, stand-down.met must equal the detector's real reset, never a clean-week count."""
    checked = False
    for d in pd.date_range("2024-01-01", "2026-06-14", freq="7D"):
        g = consistency_gauge(findings, d, m)
        if g["flagged"]:
            we = g["source_finding"]["window_end"]
            assert g["standdown"] == {"condition": "gap_unravel_reset",
                                      "met": bool(reset_satisfied("gap_unravel", m, we, d, DETECTORS))}
            checked = True
    assert checked
