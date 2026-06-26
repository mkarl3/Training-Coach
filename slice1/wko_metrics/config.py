"""Named, tunable constants for the derived-metrics library.

Every value here is athlete-relative and will be tuned. NOTHING in metrics.py may
hard-code these as inline literals — they are passed in via a MetricsConfig instance.
Detectors (Part B) will read the same config so a constant is defined exactly once.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricsConfig:
    # --- Ramp rate (CTL change per week) ---
    ramp_window_days: int = 7          # window over which CTL change is measured
    ctl_hold_weeks: int = 8            # "8-week hold": baseline-stability horizon for ramp context

    # --- Foster monotony & strain ---
    monotony_window_days: int = 7      # rolling window of daily tss_sum
    monotony_sd_ddof: int = 0          # Foster's original uses population SD (ddof=0)
    monotony_min_days: int = 7         # require a full window before emitting a value

    # --- ACWR (EWMA formulation; Williams et al. 2017) ---
    # NOTE: ACWR has well-documented caveats — acute load is mathematically COUPLED into
    # chronic load (the ratio's numerator is part of its denominator), and its predictive
    # validity for injury is contested. Treated here as a descriptive ratio only.
    acwr_acute_span_days: int = 7      # EWMA span N -> alpha = 2/(N+1)
    acwr_chronic_span_days: int = 28
    acwr_low: float = 0.80             # "undertraining/detraining" boundary (descriptive)
    acwr_high: float = 1.30            # "spike" boundary (descriptive)
    acwr_min_days: int = 28            # gate until chronic EWMA has enough history

    # --- TSB trajectory ---
    # Uses the confirmed same-day convention TSB = CTL - ATL (already stored in daily.tsb).
    tsb_window_days: int = 14          # window for direction/slope (OLS)
    tsb_flat_eps: float = 0.10         # |slope| <= eps (TSB pts/day) counts as "flat"

    # --- Intensity-factor band (for downstream intensity context) ---
    if_band_low: float = 0.78
    if_band_high: float = 0.84

    # --- Aerobic decoupling (per long ride) ---
    # WKO5 stores Pw:Hr decoupling % directly (workout.pwhr_pct); intra-ride streams are
    # not in the export, so decoupling is surfaced from that field, gated to long rides.
    long_ride_min_sec: int = 9000      # 2.5 h: minimum duration to assess decoupling
    decoupling_high_pct: float = 5.0   # >5% commonly read as aerobically "decoupled"

    # --- Power-duration ratios ---
    pd_min_ratio_samples: int = 1      # need p1hr & p2hr both present to emit a ratio

    # --- Time-in-zone distribution ---
    tiz_window_days: int = 28          # rolling window for zone-share aggregation
    tiz_power_zones: tuple = field(default_factory=lambda: (1, 2, 3, 4, 5, 6))
    tiz_hr_zones: tuple = field(default_factory=lambda: (1, 2, 3, 4, 5))

    # --- Personal CTL floor (DYNAMIC, "demonstrated sustainable base") ---
    # The two athlete-relative knobs that DEFINE the floor — floor_hold_weeks and
    # floor_window_months — now live on the AthleteProfile (profile.py), not here.
    # Only the universal data-sufficiency gate stays:
    ctl_percentile_min_days: int = 60  # min history before an as-of CTL percentile is emitted


DEFAULT = MetricsConfig()


@dataclass(frozen=True)
class DetectorConfig:
    """UNIVERSAL detector thresholds only — methodological/absolute (ABS) values and
    structural maps. The athlete-relative (REL) thresholds were relocated to the
    AthleteProfile (profile.py) in Slice 3.5; detectors read those from `m.profile`.
    (PLAN)=needs season plan (deferred)."""

    # ACTION priority (1=highest). NOT diagnosis rank. safety/acute -> overtraining ->
    # trajectory (gap/under_load/monotony) -> standing gauge.
    priority: dict = field(default_factory=lambda: {
        "injury_spike": 1, "overtraining": 2, "gap_unravel": 3,
        "under_load": 4, "monotony": 5, "fragile_ftp": 6,
    })
    # detector_family per the brief table (gap_unravel: tripwire early / trend retro).
    family: dict = field(default_factory=lambda: {
        ("gap_unravel", "early_warning"): "tripwire",
        ("gap_unravel", "retrospective"): "trend",
        ("under_load", "early_warning"): "trend",
        ("under_load", "retrospective"): "trend",
        ("overtraining", "early_warning"): "trend",
        ("overtraining", "retrospective"): "trend",
        ("fragile_ftp", "early_warning"): "gauge",
        ("fragile_ftp", "retrospective"): "gauge",
        ("injury_spike", "early_warning"): "tripwire",
        ("injury_spike", "retrospective"): "tripwire",
        ("monotony", "early_warning"): "trend",
        ("monotony", "retrospective"): "trend",
    })

    # 1 gap_unravel   (REL -> profile: gap_confirmed_ctl_drop, genuine_peak_margin,
    #                  gap_fitness_percentile)
    gap_watch_days: int = 3                  # (ABS) zero-ride streak -> watch
    gap_confirmed_days: int = 7              # (ABS) -> confirmed
    gap_active_prior_days: int = 14          # (ABS) "after a period above floor" = thread-alive window
    gap_active_min_ride_days: int = 4        # (ABS) >= this many ride days in prior window
    fwf_window_weeks: int = 4                # (ABS) fresh-while-fading window
    fwf_ctl_decline: float = 3.0             # (ABS) CTL falls >= this across window
    fwf_tsb_positive: float = 0.0            # (ABS) window-end TSB into positive territory
    floor_sustain_weeks: int = 8             # (ABS) never_sustained: held base < this
    gap_recent_peak_window_days: int = 56    # (ABS) trailing window for "recently built"

    # 2 under_load   (REL -> profile: underload_below_floor_frac, underload_ramp_watch)
    underload_window_weeks: int = 8          # (ABS) flat-low persistence
    underload_peak_lookback_weeks: int = 16  # (ABS) trailing span for "no peak to fall from"
    underload_target_date: str = None        # (PLAN) ramp-to-floor-by-date; None -> deferred

    # 3 overtraining   (REL -> profile: ot_tsb_percentile)
    ot_k_days: int = 14                       # (ABS) TSB below cutoff for K days
    ot_atl_over_ctl_weeks: int = 8           # (ABS) ATL>CTL sustained (retrospective)
    ot_monotony_rising_slope: float = 0.0    # (ABS) rising monotony (early-warning precursor)

    # 4 fragile_ftp   (REL -> profile: fragile_gap_watch_w, fragile_gap_confirmed_w)
    fragile_decoupling_pct: float = 5.0      # (ABS) long-ride Pw:Hr decoupling
    fragile_window_days: int = 120           # (ABS) gauge trend window for "is it moving"

    # 5 injury_spike   (REL -> profile: acwr_min_acute_load, acwr_min_chronic_load)
    acwr_watch: float = 1.3                  # (ABS) EWMA ACWR
    acwr_confirmed: float = 1.5              # (ABS)
    injury_stop_lookahead_days: int = 21     # (ABS) retrospective: stop within 1-3 wks

    # 6 monotony   (REL -> profile: monotony_band_frac, tiz_concentration_watch)
    monotony_watch: float = 1.5              # (ABS) Foster monotony
    monotony_confirmed: float = 2.0          # (ABS)

    # Reset / exit conditions (consumed by Slice-2 watchman; DEFINED here per detector).
    # Each: the metric + comparison that CLEARS an open finding. metric names map to
    # facade accessors; the watchman evaluates these, the detector only declares them.
    reset_conditions: dict = field(default_factory=lambda: {
        # gap_unravel clears once you've re-held your base for 3 consecutive weeks above floor. Was 8
        # weeks (56d), which could NEVER fit inside the finding's recency window (trend 28d / tripwire
        # 10d) — so the reset was dead and the warning only ever aged out by time. 3 weeks (21d) fits
        # the 28-day trend window, so a strong return-to-training now clears the standing gap zone
        # early instead of waiting out the full window. (The acute early-warning tripwire still ages
        # out via its own 10-day window — appropriate for a momentary "in a gap right now" event.)
        "gap_unravel": {"metric": "consecutive_weeks_above_floor", "op": ">=", "value": 3},
        "under_load": {"metric": "ramp_rate", "op": ">=", "value": 1.0, "for_weeks": 3},
        "overtraining": {"metric": "tsb", "op": ">=", "value": 0, "for_days": 7},
        "fragile_ftp": {"metric": "decoupling_pct", "op": "<", "value": 5.0},
        # injury_spike is an ACUTE one-day event, not a chronic condition — a single big day washes
        # out of the 7-day acute window fast, so recovery is demonstrated in a few easy days, not a
        # week. It clears on 3 clean days back under the line (vs the full week the chronic detectors
        # need). The 10-day tripwire recency window stays the backstop for when weekend rides keep
        # breaking the streak. Shortening this doesn't blind sustained overload — that's overtraining
        # / monotony, which keep their own 7-day resets.
        "injury_spike": {"metric": "acwr", "op": "<", "value": 1.3, "for_days": 3},
        "monotony": {"metric": "monotony", "op": "<", "value": 1.5, "for_days": 7},
    })


DETECTORS = DetectorConfig()
