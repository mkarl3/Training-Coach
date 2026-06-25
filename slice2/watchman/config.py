"""Selection/suppression config for the watchman. All knobs named here, not inline.
Tuned against ONE athlete — sensible output proves encoding, not generalization."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionConfig:
    # "Now" window for TREND findings: older than this is HISTORY (trend view), not a live alert.
    recency_days: int = 28
    # Tripwires are momentary EVENTS ("this happened on this date") — they go stale fast and
    # must not linger as alerts, or a once-a-month load spike keeps the board red. Short window.
    tripwire_recency_days: int = 10
    # Trailing edge is provisional: WKO recomputes ATL/TSB for the newest ~1-2 days as data
    # posts. Confirmed findings whose evidence is younger than this are shown SOFT, not fired.
    provisional_days: int = 2
    # Hero trajectory window (selectable in UI later; default here).
    trajectory_window_days: int = 90
    # How far back to look for the latest durability-gauge readout (a standing dial, not an alert).
    gauge_lookback_days: int = 240
    # NOTE: detraining_pctile (the athlete-relative "below normal range" CTL percentile) was
    # relocated to the AthleteProfile in Slice 3.5; the watchman reads it from m.profile.


DEFAULT_SELECTION = SelectionConfig()

# --- Consistency clean/miss threshold ------------------------------------------------------- #
# Canonical home is wko_metrics.consistency (Slice 1) so the Prep progression gate shares the exact
# same number as the Consistency Gauge. Re-exported here for back-compat with the gauge's brief.
from wko_metrics.consistency import CONSISTENCY_CLEAN_MIN_RIDE_DAYS  # noqa: E402,F401
