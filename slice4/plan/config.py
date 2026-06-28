"""Periodization method constants for the deterministic plan skeleton.

These are UNIVERSAL method parameters (how periodization works), not athlete values.
Athlete-relative values — ramp cap, CTL floor, masters flag, failure-mode thresholds —
come from the AthleteProfile (Slice 3.5). Availability comes from the season (Slice 4).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CalendarConfig:
    # --- nominal weekly CTL ramp by phase (pts/wk), BEFORE caps / target clamp ---
    ramp_base: float = 3.5          # early aerobic build climbs fastest from low fitness
    ramp_build: float = 2.5         # consolidation; slower as CTL nears the ceiling
    ramp_peak: float = 0.0          # hold & sharpen, don't add fitness
    taper_frac: float = 0.08        # taper sheds ~8%/wk of CTL (PROPORTIONAL, not flat) so
                                    # freshness rises without throwing away the season's fitness

    # --- recovery cadence & trough depth (masters get more frequent, shallower troughs) ---
    rec_every_open: int = 4         # a recovery week every 4th week, open category
    rec_every_masters: int = 3      # every 3rd for masters (fingerprint doc: lengthen recovery)
    recovery_dip: float = 2.0       # CTL drop in a recovery week (open)
    masters_trough_factor: float = 0.6   # masters troughs are shallower (×0.6)

    # --- canonical block structure (BASELINE = the project's Periodization Matrix: a Friel
    # period structure with WKO development sequencing). Scaled to the weeks available; the
    # CTL math, ramp caps, recovery troughs and failure-mode guardrails layer on top, keyed
    # on each block's `family`. focus / target_metric / advance_when come straight from the
    # matrix (the WKO signal a block is working + the trigger to move on). ---
    peak_weeks: int = 2
    race_weeks: int = 1
    # focus / target_metric / advance_when are DISPLAY copy (Wattson's voice): the generator passes
    # them through verbatim and the gate computes on real metrics, so these never drive logic. Written
    # as clean phrases that read after "the focus is …", "I'm watching your …", and "we move on when
    # …", and named to the VALIDATED metrics only (no FRC — parked/unrecoverable; TTE = observed).
    canonical_blocks: tuple = field(default_factory=lambda: (
        # name,     family,  nominal_wk, focus,                 target_metric,            advance_when
        ("Prep",    "base",  4, "frequency",          "fitness ramping on schedule",
         "you've strung together steady weeks and fitness is climbing"),
        ("Base 1",  "base",  4, "frequency and duration", "aerobic efficiency climbing with heart-rate drift under 5%",
         "efficiency plateaus and heart-rate drift holds under 5%"),
        ("Base 2",  "base",  4, "duration",           "aerobic efficiency holding at higher power",
         "you can hold ~40 min of tempo and efficiency flattens"),
        ("Base 3",  "base",  4, "duration and intensity", "threshold (mFTP) climbing and time-to-exhaustion stretching out",
         "mFTP and TTE plateau for 2-3 weeks"),
        ("Build 1", "build", 3, "intensity",          "aerobic power (pVO2max) and top-end (Pmax) sharpening while threshold holds",
         "aerobic power and top-end flatten while threshold holds"),
        ("Build 2", "build", 3, "intensity",          "top-end (Pmax) holding as the intensity piles up",
         "top-end plateaus and fatigue's running high"),
        ("Peak",    "peak",  2, "race-specific",      "form (TSB) turning positive and power numbers hitting season-bests",
         "form's positive and your power curve's at season-best"),
        ("Race",    "taper", 1, "race and taper",     "form (TSB) up and fresh for race day",
         "race day arrives"),
    ))

    # --- 50% rule (TrainerRoad "Ask a Cycling Coach" dataset analysis): a single ride above
    # ~half the week's TSS sharply raises the next workout's failure/skip rate. Surface a
    # per-week single-ride TSS cap so no one ride dominates the week. ---
    single_ride_cap_frac: float = 0.5

    # --- PMC relation: daily ΔCTL = (TSS - CTL)/τ ; used to turn a CTL ramp into a TSS load ---
    pmc_decay_days: int = 42

    # --- event_type -> build emphasis: (label, planning IF, distribution Rx, long-ride priority) ---
    emphasis: dict = field(default_factory=lambda: {
        "road_race_hilly": ("durability", 0.72, "polarized — long Z2 base + threshold", True),
        "gran_fondo":      ("durability", 0.70, "polarized — long Z2 + tempo", True),
        "climbing_gc":     ("durability", 0.74, "threshold + sustained climbs", True),
        "time_trial":      ("threshold", 0.80, "sweet-spot / threshold blocks", False),
        "road_race_flat":  ("threshold", 0.78, "threshold + race-pace efforts", False),
        "criterium":       ("anaerobic", 0.82, "VO2 / anaerobic + openers", False),
        "mixed":           ("balanced", 0.75, "mixed aerobic + quality", False),
    })
    default_emphasis: tuple = ("balanced", 0.75, "mixed aerobic + quality", False)
    # long-ride progression (hours) when durability is prioritized, by phase
    long_ride_hours: dict = field(default_factory=lambda: {"base": 2.5, "build": 3.0, "peak": 3.5})


DEFAULT_CALENDAR = CalendarConfig()
