"""Consistency Gauge — a watchman READOUT over the existing gap_unravel tripwire (handoff brief).

A four-heart vitality gauge. Two tiers, one boundary, two owners:
  • Above the line (hearts 2-4) — THIS module owns it: an ungated, plan-independent weekly-adherence
    buffer. Show up → hearts hold/climb; miss → hearts drop. Clamps [2,4]; never reaches 1.
  • The flag (heart 1) — the gap_unravel detector owns it. We only REFLECT select()'s decision and
    reset_satisfied()'s stand-down. We never decide the flag and never substitute a clean-week count.

The clean/miss predicate + its constant now live in wko_metrics.consistency (Slice 1) so the Prep
progression gate shares the EXACT same definition — re-exported here for the gauge's existing API.
Deterministic; all heart arithmetic is Python, the React component renders only.
"""
from __future__ import annotations

import pandas as pd

from wko_metrics.config import DETECTORS
from wko_metrics.consistency import (CONSISTENCY_CLEAN_MIN_RIDE_DAYS,  # noqa: F401  (re-exported)
                                     consecutive_miss_weeks, clean_week_streak, week_active_days)
from .config import DEFAULT_SELECTION
from .select import select, reset_satisfied

# FROZEN render maps (handoff §7) — kept here (not in JS) so the component computes nothing and the
# maps are unit-testable. heart_color by COUNT; wattson mood by ZONE.
HEART_COLOR = {4: "red", 3: "red", 2: "yellow", 1: "flash"}     # 1 = filled heart strobes red↔cream
WATTSON_MOOD = {"healthy": "approving", "caution": "calm", "warn": "alarmed", "flag": "alarmed"}
ZONE_BY_HEARTS = {4: "healthy", 3: "caution", 2: "warn"}        # buffer zones (flag handled separately)


def derive_hearts(flagged: bool, miss_weeks: int, exit_cap: int = 99):
    """FROZEN (handoff §4). Detector wins on conflict (flagged → 1). Otherwise the buffer:
    4 - miss_weeks, capped by the post-stand-down climb, clamped to [2,4] (never 1, never 0)."""
    if flagged:
        return 1, "flag"
    hearts = max(2, min(4, min(4 - miss_weeks, exit_cap)))
    return hearts, ZONE_BY_HEARTS[hearts]


def _standdown_boundary(findings, m, today, reset_val):
    """The day gap_unravel's reset (8-wk base re-hold) was first re-achieved after the last crash —
    the buffer baselines to 2 here, then climbs +1/wk. None if no crash or not yet reset."""
    gaps = [f for f in findings if f.get("mode_id") == "gap_unravel"
            and f.get("severity") == "confirmed" and pd.Timestamp(f["window_end"]) <= today]
    if not gaps:
        return None
    last_end = max(pd.Timestamp(f["window_end"]) for f in gaps)
    cw = m.consecutive_weeks_above_floor(as_of=True)
    seg = cw[(cw.index > last_end) & (cw.index <= today) & (cw >= reset_val)]
    return None if seg.empty else seg.index[0]


def consistency_gauge(findings, today, m, scfg=DEFAULT_SELECTION, dcfg=DETECTORS) -> dict:
    """The gauge reading. flagged + source_finding + stand-down come straight from the detector via
    select()/reset_satisfied; the 2-4 buffer is computed here. The React component renders this."""
    today = pd.Timestamp(today)
    sel = select(findings, today, m, scfg, dcfg)
    trip = next((t for t in sel["tripwires"]
                 if t.get("mode_id") == "gap_unravel" and t.get("severity") == "confirmed"
                 and not t.get("provisional")), None)
    flagged = trip is not None

    min_days = CONSISTENCY_CLEAN_MIN_RIDE_DAYS
    has_ride = m.has_ride
    miss_weeks = consecutive_miss_weeks(has_ride, today, min_days)
    streak = clean_week_streak(has_ride, today, min_days)

    reset_val = dcfg.reset_conditions["gap_unravel"]["value"]
    boundary = None if flagged else _standdown_boundary(findings, m, today, reset_val)
    exit_cap = (2 + max(0, (today - boundary).days // 7)) if boundary is not None else 99

    hearts, zone = derive_hearts(flagged, miss_weeks, exit_cap)

    standdown = None
    if flagged:
        we = pd.Timestamp(trip["window_end"])
        standdown = {"condition": "gap_unravel_reset",
                     "met": bool(reset_satisfied("gap_unravel", m, we, today, dcfg))}

    return {
        "as_of": today.strftime("%Y-%m-%d"),
        "hearts": hearts,
        "zone": zone,
        "flagged": flagged,
        "clean_week_streak": int(streak),
        "standdown": standdown,
        "source_finding": trip,
        "heart_color": HEART_COLOR[hearts],     # frozen render maps (§7), derived here not in JS
        "wattson_mood": WATTSON_MOOD[zone],
    }
