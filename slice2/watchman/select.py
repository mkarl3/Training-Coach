"""Selection / suppression layer — the heart of Slice 2.

Turns the full Slice-1 findings set into "what is active and relevant NOW" for a given
`today`. Computes nothing new and re-derives no metric: trajectory + reset evaluation all
come from the `Metrics` facade. Deterministic: same (findings, today, data) -> same output.

The rules (from the brief):
  1. Trailing-edge only for "now"   -> a finding older than recency_days is history, not an alert.
  2. Trailing edge is provisional   -> confirmed findings on data younger than provisional_days
                                       are shown SOFT (provisional), not fired hard.
  3. Watch-tier collapses           -> watch findings are rolled up, never listed as alerts.
  4. Reset/exit conditions clear     -> a finding whose detector reset condition has since been
                                       met is cleared (the board can go back to green).
Families render in their native form (tripwire / trend / gauge) — tagged, not merged.
"""
from collections import defaultdict

import pandas as pd

from wko_metrics.config import DETECTORS
from .config import DEFAULT_SELECTION


# --------------------------------------------------------------------------- #
# Reset / exit evaluation (uses each detector's reset condition from config)
# --------------------------------------------------------------------------- #
def _longest_true_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if bool(v) else 0
        best = max(best, cur)
    return best


def _daily_metric(mode, m):
    return {
        "ramp_rate": lambda: m.ramp_rate(),
        "tsb": lambda: m.tsb,
        "acwr": lambda: m.acwr()["acwr"],
        "monotony": lambda: m.monotony(),
    }[mode]()


def reset_satisfied(mode, m, after, until, dcfg=DETECTORS):
    """Has `mode`'s reset/exit condition been met on any day in (after, until]?
    (i.e. has the athlete recovered since the finding, so the warning should clear?)"""
    cond = dcfg.reset_conditions.get(mode)
    if not cond:
        return False
    after, until = pd.Timestamp(after), pd.Timestamp(until)
    metric, op, val = cond["metric"], cond["op"], cond["value"]

    if metric == "consecutive_weeks_above_floor":
        s = m.consecutive_weeks_above_floor(as_of=True)
        seg = s[(s.index > after) & (s.index <= until)]
        return bool((seg >= val).any())                      # a full 8-wk hold re-achieved

    if metric == "decoupling_pct":
        dec = m.decoupling()
        dec = dec[dec["sufficient"]].copy()
        dec["d"] = pd.to_datetime(dec["date"])
        dec = dec[(dec["d"] > after) & (dec["d"] <= until)].sort_values("d")
        if dec.empty:
            return False
        return bool(dec.iloc[-1]["decoupling_pct"] < val)    # latest long ride back under threshold

    series = _daily_metric(metric, m)
    seg = series[(series.index > after) & (series.index <= until)].dropna()
    if seg.empty:
        return False
    mask = (seg >= val) if op == ">=" else (seg < val)
    need = cond.get("for_days") or (cond.get("for_weeks", 0) * 7) or 1
    return _longest_true_run(mask.values) >= need


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #
def _trajectory(m, as_of, scfg):
    start = as_of - pd.Timedelta(days=scfg.trajectory_window_days)
    prov_start = as_of - pd.Timedelta(days=scfg.provisional_days)
    seg = m.daily.loc[(m.daily.index > start) & (m.daily.index <= as_of)]
    rows = []
    for dt, r in seg.iterrows():
        rows.append({
            "date": dt.strftime("%Y-%m-%d"),
            "ctl": None if pd.isna(r["ctl"]) else round(float(r["ctl"]), 1),
            "atl": None if pd.isna(r["atl"]) else round(float(r["atl"]), 1),
            "tsb": None if pd.isna(r["tsb"]) else round(float(r["tsb"]), 1),
            "provisional": bool(dt > prov_start),
        })
    return rows


def _context_notes(m, as_of, scfg):
    """Low-key, non-alarm CONTEXT — honest signals no single-block detector catches.
    Stopgap surfacing of the deferred multi-year detraining drift (mode 8): when current
    CTL sits well below the athlete's own normal range, say so quietly even on a green board."""
    notes = []
    seg = m.daily.loc[m.daily.index <= as_of, "ctl"].dropna()
    if seg.empty:
        return notes
    ctl_now = float(seg.iloc[-1])
    p25 = float(m.ctl_percentile_threshold(scfg.detraining_pctile, as_of=True).asof(as_of))
    if not pd.isna(p25) and ctl_now < p25:
        notes.append({"id": "fitness_below_normal_range", "metric": "ctl",
                      "value": round(ctl_now, 1), "reference": round(p25, 1),
                      "label": "Fitness (CTL) is below your normal range — a slow multi-month drift "
                               "no single warning catches."})
    return notes


def _direction(m, as_of, window_days=28):
    """Trend-first headline: where CTL/TSB are heading over the trailing window."""
    seg = m.daily.loc[(m.daily.index > as_of - pd.Timedelta(days=window_days)) & (m.daily.index <= as_of)]
    out = {}
    for k in ("ctl", "atl", "tsb"):
        s = seg[k].dropna()
        if len(s) >= 2:
            chg = float(s.iloc[-1] - s.iloc[0])
            out[k] = {"now": round(float(s.iloc[-1]), 1), "change": round(chg, 1),
                      "dir": "rising" if chg > 1 else "falling" if chg < -1 else "flat"}
        else:
            out[k] = None
    return out


def select(findings, as_of, m, scfg=DEFAULT_SELECTION, dcfg=DETECTORS):
    """Return the deterministic dashboard state for `as_of` (ISO date or Timestamp)."""
    as_of = pd.Timestamp(as_of)
    recency_start = as_of - pd.Timedelta(days=scfg.recency_days)
    prov_start = as_of - pd.Timedelta(days=scfg.provisional_days)

    trip_start = as_of - pd.Timedelta(days=scfg.tripwire_recency_days)
    tripwire_alerts = {}          # mode -> chosen active tripwire (acute, dated alert)
    trend_active = defaultdict(list)   # mode -> active confirmed trend findings (standing zones)
    watch_rollup = defaultdict(list)
    latest_gauge = {}             # leg -> latest gauge finding

    for f in findings:
        we = pd.Timestamp(f["window_end"])
        if we > as_of:
            continue                                   # no lookahead past "today"
        fam, mode, sev, var = (f["detector_family"], f["mode_id"], f["severity"], f["variant"])

        if fam == "gauge":                             # standing readout, not recency-gated as an alarm
            if we >= as_of - pd.Timedelta(days=scfg.gauge_lookback_days):
                leg = f["evidence"].get("leg", "default")
                if leg not in latest_gauge or we > pd.Timestamp(latest_gauge[leg]["window_end"]):
                    latest_gauge[leg] = f
            continue

        if fam == "tripwire":
            # ACUTE event alert: no-lookahead variant, only while genuinely current.
            if var != "early_warning" or we < trip_start:
                continue
            if reset_satisfied(mode, m, we, as_of, dcfg):
                continue
            if sev == "watch":
                watch_rollup[mode].append(f)
                continue
            cand = dict(f)
            cand["provisional"] = bool(we > prov_start)
            prev = tripwire_alerts.get(mode)
            if prev is None or we > pd.Timestamp(prev["window_end"]):
                tripwire_alerts[mode] = cand
        else:                                          # TREND: standing condition -> trajectory zone
            if we < recency_start:
                continue                               # history -> full trend view, not "now"
            if reset_satisfied(mode, m, we, as_of, dcfg):
                continue
            if sev == "watch":
                watch_rollup[mode].append(f)           # rule 3: collapse, never list individually
                continue
            trend_active[mode].append(f)

    trip_list = sorted(tripwire_alerts.values(), key=lambda f: (f["priority"], f["window_end"]))
    firm_trip = [f for f in trip_list if not f["provisional"]]

    # Trends collapse into ONE standing annotation per mode (a zone on the trajectory).
    trend_annotations = []
    for mode, fs in sorted(trend_active.items(), key=lambda kv: DETECTORS.priority[kv[0]]):
        fs.sort(key=lambda f: f["window_start"])
        zone_start = min(f["window_start"] for f in fs)
        zone_end = max(f["window_end"] for f in fs)
        trend_annotations.append({
            "mode_id": mode, "priority": DETECTORS.priority[mode],
            "zone_start": zone_start, "zone_end": zone_end,
            "provisional": bool(pd.Timestamp(zone_end) > prov_start),
            "evidence": fs[-1]["evidence"], "data_flags": fs[-1]["data_flags"],
        })

    gauge_out = None
    if latest_gauge:
        legs = {}
        for leg, f in latest_gauge.items():
            ev = f["evidence"]
            legs[leg] = {"last_assessed": f["window_end"], "severity": f["severity"],
                         "decoupling_pct": ev.get("decoupling_pct"),
                         "gap_1h_2h_w": ev.get("gap_1h_2h_w"),
                         "data_flags": f["data_flags"]}
        gauge_out = {"mode_id": "fragile_ftp", "legs": legs}

    watch_summary = [{"mode_id": mode, "count": len(fs),
                      "latest": max(f["window_end"] for f in fs)}
                     for mode, fs in sorted(watch_rollup.items())]

    # Trend-first status: an ACUTE tripwire makes the board red; a standing trend or rolled-up
    # watch is amber CONTEXT; otherwise green (a valid, common state). A chronic condition never
    # holds the board red — it annotates the trajectory.
    if firm_trip:
        status = "alert"
    elif trip_list or trend_annotations or watch_summary:
        status = "watch"
    else:
        status = "green"

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "status": status,
        "direction": _direction(m, as_of),
        "tripwires": trip_list,               # acute dated alerts (the "watch out for" alerts)
        "trend_annotations": trend_annotations,  # standing zones drawn on the trajectory
        "gauge": gauge_out,                   # durability dial
        "watch_rollup": watch_summary,        # collapsed watch-tier (annotations, not alerts)
        "context": _context_notes(m, as_of, scfg),  # quiet honest notes (e.g. mode-8 drift)
        "trajectory": _trajectory(m, as_of, scfg),
    }
