"""Failure-mode detector engine (Slice 1, Part B).

Each detector is a PURE function over the `Metrics` facade — it thresholds metric
values and emits structured `Finding` dicts. It never reads raw tables, never
re-derives a metric, and never reads daily.if_daily (display-only). Detectors emit
DATA ONLY — no prose; the LLM coach (later slice) consumes these.

Two artifacts per mode: variant="retrospective" (closed window, may use lookahead)
and variant="early_warning" (data-to-date, no lookahead). Two-tier severity
watch/confirmed. Reset/exit conditions live in DetectorConfig (Slice-2 consumes them).

HONEST FRAMING: green tests prove each detector is correctly encoded against the ONE
episode it was shown — NOT that the fingerprint generalizes. Validation needs athlete #2.
"""
from typing import Any, Literal, TypedDict

import numpy as np
import pandas as pd

from .config import DETECTORS, DEFAULT


class DiscriminatorTest(TypedDict):
    passed: bool
    value: Any
    threshold: Any


class Finding(TypedDict):
    mode_id: str
    variant: Literal["retrospective", "early_warning"]
    severity: Literal["watch", "confirmed"]
    detector_family: Literal["tripwire", "trend", "gauge"]
    window_start: str
    window_end: str
    evidence: dict
    discriminator_result: dict
    data_flags: list
    priority: int


def _iso(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _t(passed, value, threshold) -> DiscriminatorTest:
    return {"passed": bool(passed), "value": value, "threshold": threshold}


def _round(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


class _Builder:
    def __init__(self, m, dcfg):
        self.m = m
        self.dcfg = dcfg

    def make(self, mode_id, variant, severity, start, end, evidence, discriminators) -> Finding:
        return {
            "mode_id": mode_id,
            "variant": variant,
            "severity": severity,
            "detector_family": self.dcfg.family[(mode_id, variant)],
            "window_start": _iso(start),
            "window_end": _iso(end),
            "evidence": evidence,
            "discriminator_result": discriminators,
            "data_flags": self.m.flags_in_window(_iso(start), _iso(end)),
            "priority": self.dcfg.priority[mode_id],
        }


# --------------------------------------------------------------------------- #
# 1. gap_unravel
# --------------------------------------------------------------------------- #
def detect_gap_unravel(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    idx = m.daily.index
    streak = m.zero_ride_streak()
    ctl = m.ctl
    tsb = m.tsb
    # Dynamic per-athlete fitness gate: the gap only counts as a build-and-crash if a real
    # build preceded it — recent peak CTL reached the athlete's own Pxx percentile (as-of,
    # no lookahead). This replaces the thread-alive gate that fired on every rest week.
    fit_thr = m.ctl_percentile_threshold(m.profile.gap_fitness_percentile, as_of=True)
    recent_peak = m.recent_peak_ctl(dcfg.gap_recent_peak_window_days)

    # ---- early_warning: streak-break tripwire (no lookahead) ----
    # Hysteresis (same as injury_spike): one crash episode -> ONE finding per tier, not one
    # per gap. The episode persists while the build is still recent (recent_peak >= fitness
    # line); re-arm only once that build ages out of the window (the crash is over).
    sv = streak.values
    armed_watch = armed_conf = True
    for i in range(len(sv)):
        thr = fit_thr.iloc[i]
        peak_now = float(recent_peak.iloc[i])
        if pd.isna(thr) or peak_now < thr:            # not in a built-then-crashing state
            armed_watch = armed_conf = True           # episode over -> re-arm
            continue
        n = int(sv[i])
        if n < dcfg.gap_watch_days:
            continue
        start_i = i - n + 1
        peak = float(recent_peak.iloc[max(start_i - 1, 0)])
        ctl_start = float(ctl.iloc[max(start_i - 1, 0)])
        ctl_now = float(ctl.iloc[i])
        drop = ctl_start - ctl_now
        ev = {"zero_ride_streak_days": n, "recent_peak_ctl": _round(peak),
              "fitness_threshold": _round(thr), "ctl_now": _round(ctl_now),
              "ctl_drop": _round(drop), "tsb_now": _round(tsb.iloc[i])}
        disc = {
            "built_to_personal_high": _t(True, _round(peak),
                                         {"pct": m.profile.gap_fitness_percentile, "value": _round(thr)}),
        }
        if n >= dcfg.gap_confirmed_days and drop > m.profile.gap_confirmed_ctl_drop and armed_conf:
            disc["zero_ride_streak"] = _t(True, n, dcfg.gap_confirmed_days)
            disc["ctl_dropped"] = _t(True, _round(drop), m.profile.gap_confirmed_ctl_drop)
            out.append(b.make("gap_unravel", "early_warning", "confirmed",
                              idx[start_i], idx[i], ev, disc))
            armed_conf = armed_watch = False
        elif armed_watch:
            disc["zero_ride_streak"] = _t(True, n, dcfg.gap_watch_days)
            out.append(b.make("gap_unravel", "early_warning", "watch",
                              idx[start_i], idx[i], ev, disc))
            armed_watch = False

    # ---- retrospective: fresh-while-fading + never-sustained + genuine prior peak ----
    wk_ctl = m.weekly_ctl()
    wk_tsb = tsb.resample("W").mean()
    fit_thr_retro = m.ctl_percentile_threshold(m.profile.gap_fitness_percentile, as_of=False)
    weeks_above = m.consecutive_weeks_above_floor(as_of=True)
    prior_peak = m.prior_peak_ctl()
    W = dcfg.fwf_window_weeks
    fired_weeks = set()
    for j in range(W, len(wk_ctl)):
        c0, c1 = wk_ctl.iloc[j - W], wk_ctl.iloc[j]
        if pd.isna(c0) or pd.isna(c1):
            continue
        decline = c0 - c1
        end_tsb = wk_tsb.iloc[j]
        fwf = (decline >= dcfg.fwf_ctl_decline) and (end_tsb > dcfg.fwf_tsb_positive)
        if not fwf or j in fired_weeks:
            continue
        start_w, end_w = wk_ctl.index[j - W], wk_ctl.index[j]
        # discriminators
        peak_before = float(prior_peak.loc[:start_w].max())
        fl = float(fit_thr_retro.iloc[0])               # all-history Pxx fitness line
        genuine_peak = peak_before >= fl                 # fell from a genuine (personal-high) build
        # never_sustained: assessed over the build leading INTO this episode (trailing
        # ~26 wk), not all-history — else one held base ever makes every later dip "sustained".
        recent_above = weeks_above.loc[:end_w].iloc[-26:]
        held = int(recent_above.max()) if recent_above.size else 0
        never_sustained = held < dcfg.floor_sustain_weeks
        disc = {
            "fresh_while_fading": _t(True, {"ctl_decline": _round(decline), "end_tsb": _round(end_tsb)},
                                     {"decline>=": dcfg.fwf_ctl_decline, "tsb>": dcfg.fwf_tsb_positive}),
            "never_sustained": _t(never_sustained, held, dcfg.floor_sustain_weeks),
            "genuine_prior_peak": _t(genuine_peak, _round(peak_before), _round(fl)),
        }
        # genuine_prior_peak is what separates this from under_load — required to fire.
        if not genuine_peak:
            continue
        sev = "confirmed" if never_sustained else "watch"
        ev = {"ctl_peak_before": _round(peak_before), "ctl_decline_over_window": _round(decline),
              "end_tsb": _round(end_tsb), "weeks_held_above_floor": held, "fitness_threshold": _round(fl)}
        out.append(b.make("gap_unravel", "retrospective", sev, start_w, end_w, ev, disc))
        fired_weeks.update(range(j, min(j + W, len(wk_ctl))))  # de-dupe overlapping windows
    return out


# --------------------------------------------------------------------------- #
# 2. under_load
# --------------------------------------------------------------------------- #
def detect_under_load(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    wk_ctl = m.weekly_ctl()
    floor_w = m.personal_ctl_floor_asof().resample("W").last()
    ramp = m.ramp_rate()
    Wn = dcfg.underload_window_weeks
    fired = set()
    for j in range(Wn, len(wk_ctl)):
        seg = wk_ctl.iloc[j - Wn:j]
        fl = floor_w.iloc[j] if not pd.isna(floor_w.iloc[j]) else np.nan
        if pd.isna(fl) or seg.isna().all():
            continue
        below_frac = float((seg < fl).mean())
        # "no peak to fall from" must look back beyond the window — a recent peak (e.g. a
        # prior in-season build) means a decline here is gap/normal, NOT never-built.
        look0 = max(0, j - dcfg.underload_peak_lookback_weeks)
        peak_recent = float(wk_ctl.iloc[look0:j].max())
        # margin keeps under_load and gap_unravel separable: a peak within `margin` of the
        # floor counts as a build (gap territory), not never-built.
        no_peak = peak_recent < (fl - m.profile.genuine_peak_margin)
        flat_low = below_frac >= m.profile.underload_below_floor_frac
        if not (flat_low and no_peak) or j in fired:
            continue
        start_w, end_w = wk_ctl.index[j - Wn], wk_ctl.index[j - 1]
        # ramp-to-floor-by-target is PLAN-AWARE -> deferred when no target date set.
        ramp_now = float(ramp.loc[:end_w].dropna().iloc[-1]) if ramp.loc[:end_w].dropna().size else np.nan
        if dcfg.underload_target_date is None:
            ramp_test = {"passed": False, "value": _round(ramp_now), "threshold": "deferred (no season plan)"}
        else:
            ramp_test = _t(ramp_now < m.profile.underload_ramp_watch, _round(ramp_now), m.profile.underload_ramp_watch)
        disc = {
            "no_peak_to_fall_from": _t(no_peak, _round(peak_recent), _round(fl)),
            "chronically_below_floor": _t(flat_low, _round(below_frac), m.profile.underload_below_floor_frac),
            "ramp_to_floor_by_target": ramp_test,
        }
        sev = "confirmed" if below_frac >= 0.95 else "watch"
        ev = {"weeks_below_floor_frac": _round(below_frac), "recent_peak_ctl": _round(peak_recent),
              "floor": _round(fl), "trailing_ramp": _round(ramp_now)}
        out.append(b.make("under_load", "early_warning" if dcfg.underload_target_date else "retrospective",
                          sev, start_w, end_w, ev, disc))
        fired.update(range(j, min(j + Wn, len(wk_ctl))))
    return out


# --------------------------------------------------------------------------- #
# 3. overtraining  (negative-test only on this athlete)
# --------------------------------------------------------------------------- #
def detect_overtraining(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    ctl, atl, tsb = m.ctl, m.atl, m.tsb
    mono = m.monotony()
    mftp = m.mftp
    ramp = m.ramp_rate()
    tsb_cut = m.tsb_percentile(m.profile.ot_tsb_percentile)

    # ---- retrospective: ATL>CTL sustained + TSB deeply negative + performance declining ----
    over = (atl > ctl).astype(int)
    # longest run of ATL>CTL
    runs = (over != over.shift()).cumsum()
    for _, grp in over[over == 1].groupby(runs):
        if len(grp) < dcfg.ot_atl_over_ctl_weeks * 7:
            continue
        s, e = grp.index[0], grp.index[-1]
        seg_tsb = tsb.loc[s:e]
        deep = bool((seg_tsb <= tsb_cut).mean() >= 0.5)
        mftp_slope = float(np.polyfit(range(len(mftp.loc[s:e].dropna())),
                                      mftp.loc[s:e].dropna().values, 1)[0]) if mftp.loc[s:e].dropna().size > 2 else np.nan
        declining = (not np.isnan(mftp_slope)) and mftp_slope < 0
        disc = {
            "atl_over_ctl_sustained": _t(True, len(grp), dcfg.ot_atl_over_ctl_weeks * 7),
            "tsb_deeply_negative": _t(deep, _round(float(seg_tsb.median())), _round(tsb_cut)),
            "performance_declining": _t(declining, _round(mftp_slope, 4), 0),
        }
        if deep and declining:
            ev = {"atl_over_ctl_days": len(grp), "tsb_median": _round(float(seg_tsb.median())),
                  "mftp_slope_per_day": _round(mftp_slope, 4)}
            out.append(b.make("overtraining", "retrospective", "confirmed", s, e, ev, disc))

    # ---- early_warning: TSB below cutoff K days + positive ramp + rising monotony ----
    below = (tsb <= tsb_cut).astype(int)
    runK = (below != below.shift()).cumsum()
    for _, grp in below[below == 1].groupby(runK):
        if len(grp) < dcfg.ot_k_days:
            continue
        s, e = grp.index[0], grp.index[-1]
        ramp_now = float(ramp.loc[s:e].dropna().iloc[-1]) if ramp.loc[s:e].dropna().size else np.nan
        mono_seg = mono.loc[s:e].dropna()
        mono_rising = mono_seg.size > 2 and np.polyfit(range(len(mono_seg)), mono_seg.values, 1)[0] > dcfg.ot_monotony_rising_slope
        pos_ramp = (not np.isnan(ramp_now)) and ramp_now > 0
        disc = {
            "tsb_below_cutoff_k_days": _t(True, len(grp), dcfg.ot_k_days),
            "positive_ramp": _t(pos_ramp, _round(ramp_now), 0),
            "rising_monotony": _t(bool(mono_rising), None, dcfg.ot_monotony_rising_slope),
        }
        if pos_ramp and mono_rising:
            ev = {"tsb_below_cutoff_days": len(grp), "tsb_cutoff": _round(tsb_cut),
                  "trailing_ramp": _round(ramp_now)}
            out.append(b.make("overtraining", "early_warning", "watch", s, e, ev, disc))
    return out


# --------------------------------------------------------------------------- #
# 4. fragile_ftp  (gauge — no tripwire)
# --------------------------------------------------------------------------- #
def detect_fragile_ftp(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    # decoupling leg (long rides, Pw:Hr)
    dec = m.decoupling()
    dec = dec[dec["sufficient"]]
    for _, r in dec.iterrows():
        if r["decoupling_pct"] is None or pd.isna(r["decoupling_pct"]):
            continue
        if r["decoupling_pct"] < dcfg.fragile_decoupling_pct:
            continue
        d = r["date"]
        disc = {"long_ride_decoupling": _t(True, _round(r["decoupling_pct"]), dcfg.fragile_decoupling_pct)}
        sev = "confirmed" if r["decoupling_pct"] >= 2 * dcfg.fragile_decoupling_pct else "watch"
        ev = {"leg": "decoupling", "decoupling_pct": _round(r["decoupling_pct"]),
              "ride_hours": _round(r["duration_sec"] / 3600.0)}
        out.append(b.make("fragile_ftp", "retrospective", sev, d, d, ev, disc))

    # power-duration leg (1h-2h fade)
    pdr = m.power_duration()
    pdr = pdr[pdr["sufficient"]]
    for _, r in pdr.iterrows():
        gap = float(r["pd_gap_1h_2h_w"])
        if gap < m.profile.fragile_gap_watch_w:
            continue
        d = r["date"]
        disc = {"power_duration_gap_1h_2h": _t(True, _round(gap),
                {"watch": m.profile.fragile_gap_watch_w, "confirmed": m.profile.fragile_gap_confirmed_w})}
        sev = "confirmed" if gap >= m.profile.fragile_gap_confirmed_w else "watch"
        ev = {"leg": "power_duration", "gap_1h_2h_w": _round(gap),
              "p1hr_w": _round(r["p1hr_w"]), "p2hr_w": _round(r["p2hr_w"])}
        out.append(b.make("fragile_ftp", "retrospective", sev, d, d, ev, disc))
    return out


# --------------------------------------------------------------------------- #
# 5. injury_spike  (tripwire — load signal only, never diagnoses tissue)
# --------------------------------------------------------------------------- #
def detect_injury_spike(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    aw = m.acwr()
    acwr, acute, chronic = aw["acwr"], aw["acute"], aw["chronic"]
    streak = m.zero_ride_streak()
    idx = m.daily.index
    av = acwr.values
    # Hysteresis: ACWR whipsaws badly on this spiky load, so collapse each spike CLUSTER
    # to one finding per tier. Re-arm only after ACWR falls back below the watch line.
    armed_watch = armed_conf = True
    for i in range(len(av)):
        cur = av[i]
        if np.isnan(cur):
            continue
        if cur < dcfg.acwr_watch:
            armed_watch = armed_conf = True            # reset/exit -> re-armed
            continue
        ac = float(acute.iloc[i])
        ch = float(chronic.iloc[i])
        if ac < m.profile.acwr_min_acute_load or ch < m.profile.acwr_min_chronic_load:  # absolute-load gates
            continue
        # Low-base cap: with a small chronic load the acute window is dominated by one ride, so the
        # ratio over-reads as a spike. Hold a would-be CONFIRMED at WATCH until the base is built.
        low_base = ch < m.profile.acwr_confirmed_min_chronic_load
        hit_conf = cur >= dcfg.acwr_confirmed
        if hit_conf and not low_base and armed_conf:
            thr, sev = dcfg.acwr_confirmed, "confirmed"
            armed_conf = armed_watch = False
        elif hit_conf and low_base and armed_conf:
            # Base too low for a red alert, but this IS a real escalation across the confirmed line.
            # Register it (as watch) on THIS day, on the confirmed arming, so the finding dates to
            # the actual peak ride — not just the leading-edge watch crossing the hysteresis caught.
            thr, sev = dcfg.acwr_watch, "watch"
            armed_conf = False
        elif cur >= dcfg.acwr_watch and armed_watch:
            thr, sev = dcfg.acwr_watch, "watch"
            armed_watch = False
        else:
            continue
        disc = {
            "acwr_crossing": _t(True, _round(cur), thr),
            "acute_load_gate": _t(True, _round(ac), m.profile.acwr_min_acute_load),
        }
        if low_base and hit_conf:                     # record why a red-tier spike was held at watch
            disc["low_base_cap"] = _t(True, _round(ch), m.profile.acwr_confirmed_min_chronic_load)
        ev = {"acwr": _round(cur), "acute_ewma": _round(ac)}
        out.append(b.make("injury_spike", "early_warning", sev, idx[i], idx[i], ev, dict(disc)))
        # retrospective: consequent stop within 1-3 wks (lookahead)
        fwd = streak.iloc[i:i + dcfg.injury_stop_lookahead_days]
        stop = fwd[fwd >= dcfg.gap_watch_days]
        if stop.size:
            stop_day = stop.index[0]
            disc_r = dict(disc)
            disc_r["consequent_stop"] = _t(True, _iso(stop_day), f"<= {dcfg.injury_stop_lookahead_days}d")
            out.append(b.make("injury_spike", "retrospective", sev, idx[i], stop_day,
                              {**ev, "stop_date": _iso(stop_day)}, disc_r))
    return out


# --------------------------------------------------------------------------- #
# 6. monotony
# --------------------------------------------------------------------------- #
def detect_monotony(m, dcfg=DETECTORS):
    b = _Builder(m, dcfg)
    out = []
    mono = m.monotony()
    band = m.gray_zone_if_fraction()
    conc = m.tiz_power_concentration()
    idx = m.daily.index
    mv = mono.values
    for i in range(1, len(mv)):
        prev, cur = mv[i - 1], mv[i]
        if np.isnan(cur):
            continue
        for thr, sev in ((dcfg.monotony_confirmed, "confirmed"), (dcfg.monotony_watch, "watch")):
            crossed = (np.isnan(prev) or prev < thr) and cur >= thr
            if not crossed:
                continue
            bf = float(band.iloc[i]) if not pd.isna(band.iloc[i]) else None
            cc = float(conc.iloc[i]) if not pd.isna(conc.iloc[i]) else None
            disc = {
                "foster_monotony": _t(True, _round(cur), thr),
                "if_gray_band_fraction": _t(bf is not None and bf >= m.profile.monotony_band_frac,
                                            _round(bf), m.profile.monotony_band_frac),
                "tiz_narrowing": _t(cc is not None and cc >= m.profile.tiz_concentration_watch,
                                    _round(cc), m.profile.tiz_concentration_watch),
            }
            ev = {"monotony": _round(cur), "if_band_fraction": _round(bf), "tiz_concentration": _round(cc)}
            out.append(b.make("monotony", "early_warning", sev, idx[i], idx[i], ev, disc))
            break
    return out


# --------------------------------------------------------------------------- #
# Run-all + ranking
# --------------------------------------------------------------------------- #
ALL_DETECTORS = {
    "gap_unravel": detect_gap_unravel,
    "under_load": detect_under_load,
    "overtraining": detect_overtraining,
    "fragile_ftp": detect_fragile_ftp,
    "injury_spike": detect_injury_spike,
    "monotony": detect_monotony,
}


def run_all(m, dcfg=DETECTORS):
    """Run every detector; return all findings. Caller filters by date/variant."""
    findings = []
    for fn in ALL_DETECTORS.values():
        findings.extend(fn(m, dcfg))
    return findings


def action_rank(findings):
    """Order findings by ACTION priority (1=highest), then severity (confirmed first).
    This is the watchman ordering — NOT retrospective diagnosis rank."""
    sev_rank = {"confirmed": 0, "watch": 1}
    return sorted(findings, key=lambda f: (f["priority"], sev_rank[f["severity"]], f["window_end"]))
