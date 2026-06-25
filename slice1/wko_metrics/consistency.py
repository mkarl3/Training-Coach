"""Consistency predicate — the single source of truth for "did the athlete show up?", shared by
the Consistency Gauge (Slice 2 watchman) AND the Prep-phase progression gate (Slice 4). Lives in
Slice 1 because both layers already depend on wko_metrics; pure functions over a daily has_ride
Series (0/1), so they unit-test on synthetic data with no Metrics needed.

Behavioral, ungated, plan-independent: a trailing 7-day WEEK is CLEAN when the athlete rode at
least CONSISTENCY_CLEAN_MIN_RIDE_DAYS days — ride FREQUENCY, not TSS. A single hero day can't fake
it (it's one ride day), which is the whole point ("no hero days").
"""
from __future__ import annotations

import pandas as pd

# SIGNED OFF 2026-06-23 as a static 4 (ride 4+ days/week = clean). Backlog: once weekly workout
# PLANNING exists, this becomes the count of rides the plan SCHEDULES that week (plan-relative).
# Single source — the gauge and the Prep gate both read this exact value.
CONSISTENCY_CLEAN_MIN_RIDE_DAYS = 4


def week_active_days(has_ride: pd.Series, week_end) -> int:
    """Ride days in the trailing 7-day week ending (inclusive) at week_end."""
    week_end = pd.Timestamp(week_end)
    lo = week_end - pd.Timedelta(days=6)
    return int(has_ride[(has_ride.index >= lo) & (has_ride.index <= week_end)].sum())


def _is_miss(has_ride, week_end, min_days):
    return week_active_days(has_ride, week_end) < min_days


def consecutive_miss_weeks(has_ride, today, min_days, max_lookback=26) -> int:
    """Consecutive trailing 7-day weeks (ending at `today`) that are MISSES, until the first clean
    week. Plan-independent and ungated. Stops at the start of the data (no data ≠ a miss)."""
    if has_ride.empty:
        return 0
    today, floor = pd.Timestamp(today), has_ride.index.min()
    c = 0
    for w in range(max_lookback):
        we = today - pd.Timedelta(days=7 * w)
        if we < floor:
            break
        if _is_miss(has_ride, we, min_days):
            c += 1
        else:
            break
    return c


def clean_week_streak(has_ride, today, min_days, max_lookback=104) -> int:
    """Consecutive clean weeks ending at `today` (resets to 0 on any miss)."""
    if has_ride.empty:
        return 0
    today, floor = pd.Timestamp(today), has_ride.index.min()
    c = 0
    for w in range(max_lookback):
        we = today - pd.Timedelta(days=7 * w)
        if we < floor or _is_miss(has_ride, we, min_days):
            break
        c += 1
    return c
