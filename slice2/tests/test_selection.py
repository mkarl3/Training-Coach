"""Selection/suppression layer tests.

HONEST FRAMING: tuned against ONE athlete's findings. Sensible output proves correct
encoding for this person, not generalization (athlete #2 validates).
"""
import pandas as pd

from watchman import select, reset_satisfied, DEFAULT_SELECTION


def _modes(items, key="mode_id"):
    return {x[key] for x in items}


# --------------------------------------------------------------------------- #
# Core behavioral checkpoint cases
# --------------------------------------------------------------------------- #
def test_crash_surfaces_single_gap_alert(m, findings):
    s = select(findings, "2026-03-25", m)
    assert s["status"] == "alert"
    gap = [t for t in s["tripwires"] if t["mode_id"] == "gap_unravel"]
    assert len(gap) == 1                              # the whole crash = one alert (hysteresis upstream)
    assert gap[0]["severity"] == "confirmed" and not gap[0]["provisional"]


def test_quiet_period_is_green(m, findings):
    s = select(findings, "2025-10-05", m)
    assert s["status"] == "green"
    assert not s["tripwires"] and not s["trend_annotations"]


def test_no_lookahead_past_today(m, findings):
    # Before the crash gap, the crash finding (window_end 2026-03-18) must not surface.
    s = select(findings, "2026-03-01", m)
    assert all(t["window_end"] <= "2026-03-01" for t in s["tripwires"])
    assert not any(t["window_start"] == "2026-03-12" for t in s["tripwires"])


def test_trailing_edge_is_provisional(m, findings):
    # Evaluated exactly on a confirmed gap's window_end -> provisional, board not hard-alert.
    s = select(findings, "2026-03-18", m)
    gap = [t for t in s["tripwires"] if t["mode_id"] == "gap_unravel"]
    assert gap and gap[0]["provisional"] is True
    assert s["status"] == "watch"                    # soft on the trailing edge, not "alert"


def test_tripwire_goes_stale(m, findings):
    # 40 days after the crash gap, the acute tripwire has aged out of the alert panel.
    s = select(findings, "2026-04-30", m)
    assert not any(t["mode_id"] == "gap_unravel" for t in s["tripwires"])


def test_watch_tier_never_listed_as_alert(m, findings):
    # No surfaced alert or zone is watch-tier; watch-tier only appears collapsed in the rollup.
    for as_of in ("2026-03-25", "2025-02-20", "2023-05-20"):
        s = select(findings, as_of, m)
        assert all(t["severity"] == "confirmed" for t in s["tripwires"])


def test_chronic_trend_is_watch_context_not_alert(m, findings):
    # Deep in the 2025 flat-low stretch: under_load is a standing trend zone -> amber WATCH,
    # never a red alert (a chronic condition must not hold the board red).
    s = select(findings, "2025-02-04", m)
    assert s["status"] == "watch"
    assert any(a["mode_id"] == "under_load" for a in s["trend_annotations"])
    assert not s["tripwires"] or all(t["provisional"] for t in s["tripwires"])


# --------------------------------------------------------------------------- #
# Reset / exit conditions
# --------------------------------------------------------------------------- #
def test_reset_clears_after_recovery(m):
    # After the 2023-05-13 ACWR spike the athlete's ACWR falls back below 1.3 for 7+ days.
    assert reset_satisfied("injury_spike", m, "2023-05-13", "2023-07-15")
    # ...but not in the first couple of days right after (no recovery yet).
    assert not reset_satisfied("injury_spike", m, "2023-05-13", "2023-05-16")


def test_gap_reset_requires_eight_week_hold(m):
    # The athlete never re-holds an 8-wk base after the 2026 crash -> gap stays unreset.
    assert not reset_satisfied("gap_unravel", m, "2026-03-18", "2026-05-29")


# --------------------------------------------------------------------------- #
# Structure / invariants
# --------------------------------------------------------------------------- #
def test_deterministic(m, findings):
    assert select(findings, "2026-03-25", m) == select(findings, "2026-03-25", m)


def test_one_alert_per_mode(m, findings):
    for as_of in ("2026-03-25", "2024-04-25", "2023-05-20"):
        s = select(findings, as_of, m)
        ids = [t["mode_id"] for t in s["tripwires"]]
        assert len(ids) == len(set(ids))


def test_gauge_is_standing_readout(m, findings):
    # The durability gauge persists as a dial (last known durability), independent of alerts.
    s = select(findings, "2025-10-05", m)
    assert s["gauge"] and "decoupling" in s["gauge"]["legs"]


def test_trajectory_marks_recent_days_provisional(m, findings):
    s = select(findings, "2026-03-25", m)
    traj = s["trajectory"]
    assert traj and traj[-1]["provisional"] and not traj[0]["provisional"]
    assert sum(p["provisional"] for p in traj) == DEFAULT_SELECTION.provisional_days
