"""Source-agnostic activity model — the migration insurance.

Every data source (Strava now; .fit / Garmin / Wahoo / intervals.icu later) maps its payload
into this one shape. The metrics engine and everything downstream consume `Activity`, never a
provider's raw JSON — so adding or swapping a source is a new connector, not a rewrite.

Deliberately thin: the raw per-second streams plus the few summary fields we can't always derive
cheaply. Everything else (TSS, NP, PD bests, CTL/ATL/TSB) is COMPUTED from `streams` by the
metrics engine, identically regardless of which source produced the activity.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Activity:
    source: str                      # 'strava' | 'fit' | 'intervals' | ...
    source_id: str                   # provider's id, for dedupe across syncs
    start: str                       # ISO-8601 local start datetime
    sport: str                       # 'Ride' | 'VirtualRide' | 'Run' | ...
    duration_s: int                  # moving or elapsed seconds (source decides; we note which)
    elapsed: bool = True             # True if duration_s is elapsed time, False if moving
    distance_m: float | None = None
    avg_power_w: float | None = None  # provider-reported average power, if any (sanity check only)
    device_watts: bool | None = None  # True = real power meter; False = estimated; None = unknown
    # per-second streams, each a list aligned by index; 'time' is seconds-from-start
    streams: dict[str, list] = field(default_factory=dict)  # keys: 'time','watts','heartrate','cadence'

    @property
    def has_power(self) -> bool:
        return bool(self.streams.get("watts")) and self.device_watts is not False

    def __repr__(self) -> str:
        n = len(self.streams.get("watts") or [])
        return (f"Activity({self.source}:{self.source_id} {self.start} {self.sport} "
                f"{self.duration_s}s power_samples={n})")
