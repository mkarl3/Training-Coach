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
    # CTL below this percentile of the athlete's own history => quiet "below normal range" context
    # (stopgap for the deferred multi-year detraining-drift mode; informational, not an alarm).
    detraining_pctile: float = 25.0


DEFAULT_SELECTION = SelectionConfig()
