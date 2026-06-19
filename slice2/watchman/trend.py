"""Long-range TREND view assembly for the Watt Smith dashboard (the integrated PMC).

Deterministic. Turns the Metrics facade + the full Slice-1 findings into a payload shaped for
the trend chart: a WEEKLY fitness series (CTL + summed TSS), the athlete's demonstrated-safe
ramp (so the frontend can colour the line by how it was earned), and a small CAPPED, ranked set
of INSIGHTS — each pinned to a zone on the timeline and read in plain language.

THE ONE RULE holds here: nothing is computed that the deterministic engine didn't already
produce. Insight prose is TEMPLATED per mode_id from the detector's own evidence (no LLM), and
the jargon ("ACWR", "CTL drop") is translated to coach-speak. Same (m, findings, as_of) -> same
output.
"""
import datetime as dt

import pandas as pd

from wko_metrics.config import DETECTORS

# How a mode maps to a marker tone + Wattson's expression + a colour key the frontend knows.
_TONE = {
    "injury_spike":  ("hot",   "alarmed"),
    "gap_unravel":   ("lose",  "alarmed"),
    "under_load":    ("lose",  "alarmed"),
    "overtraining":  ("lose",  "alarmed"),
    "monotony":      ("hold",  "calm"),
    "fragile_ftp":   ("hold",  "calm"),
}
_EPISODE_GAP_DAYS = 21        # findings of one mode more than this far apart = separate episodes
_ONGOING_DAYS = 28            # an episode ending within this of as_of reads as "ongoing"


def _d(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


def weekly_series(m, as_of):
    """Weekly CTL (end-of-week) + summed weekly TSS + end-of-week form (TSB), up to as_of.
    The trend instrument's spine, plus the topline numbers the hover scrubber reads."""
    ao = pd.Timestamp(as_of)
    ctl = m.weekly_ctl().dropna()
    tss = m.weekly_tss()
    tsb = m.tsb.resample("W").last()
    out = []
    for wk, c in ctl.items():
        if wk > ao + pd.Timedelta(days=6):
            continue
        tv = tsb.get(wk)
        out.append({"date": wk.strftime("%Y-%m-%d"),
                    "ctl": round(float(c), 1),
                    "tss": int(round(float(tss.get(wk, 0.0) or 0.0))),
                    "tsb": None if tv is None or pd.isna(tv) else round(float(tv), 1),
                    "block": None})
    return out


def _attach_blocks(series, plan_weeks):
    """Label each weekly point with its training block when the plan covers it (season is often
    future, so this is frequently empty — by design: 'if it exists')."""
    if not plan_weeks:
        return
    by_monday = {w["week_start"]: w.get("block") for w in plan_weeks}
    for pt in series:
        # the series week ends Sunday; its Monday (the plan's week_start key) is six days back
        monday = (dt.date.fromisoformat(pt["date"]) - dt.timedelta(days=6)).isoformat()
        pt["block"] = by_monday.get(monday) or by_monday.get(pt["date"])


def _episodes(findings):
    """Cluster a mode's confirmed findings into time-separated episodes; keep each episode's
    span + the evidence of its last finding (the matured read)."""
    fs = sorted(findings, key=lambda f: f["window_start"])
    eps, cur = [], None
    for f in fs:
        ws, we = _d(f["window_start"]), _d(f["window_end"])
        if cur and (ws - cur["end"]).days <= _EPISODE_GAP_DAYS:
            cur["end"] = max(cur["end"], we)
            cur["ev"] = f["evidence"]
        else:
            if cur:
                eps.append(cur)
            cur = {"start": ws, "end": we, "ev": f["evidence"]}
    if cur:
        eps.append(cur)
    return eps


def _pct(ratio):
    return int(round((ratio - 1.0) * 100))


def _template(mode, ev):
    """Plain-language (title, read, plan-hint) for a mode from its evidence. No jargon. Numbers
    are woven in only when the evidence actually carries them — never a bare '~0'."""
    g = ev.get
    if mode == "gap_unravel":
        drop = round(float(g("ctl_decline_over_window", 0) or 0))
        peak = round(float(g("ctl_peak_before", 0) or 0))
        detail = (f"You'd built to a fitness peak (~{peak}), then the thread broke — usually a gap "
                  f"off the bike — and ~{drop} points of that fitness drained away. "
                  if peak > 0 and drop > 0 else
                  "You'd been building, then the thread broke — usually a gap off the bike — and "
                  "fitness started draining away. ")
        return ("Fitness leak after a peak",
                detail + "Fitness lost this way takes roughly twice as long to win back as it "
                "did to lose.",
                "Why the plan rebuilds gradually instead of chasing the old peak.")
    if mode == "under_load":
        floor = round(float(g("floor", 0) or 0))
        recent = round(float(g("recent_peak_ctl", 0) or 0))
        detail = (f"Your weekly load sat under the base you've shown you can hold (~{floor}), and "
                  f"fitness drifted to ~{recent}. " if floor > 0 else
                  "Your weekly load sat under the base you've shown you can hold. ")
        return ("Training below your sustainable base",
                detail + "That's under-stimulating — consistency, not big days, is what rebuilds "
                "it.",
                "The plan steps load up toward your floor, week by week.")
    if mode == "overtraining":
        return ("Dug into a fatigue hole",
                "Your form sat deep in the red for a stretch — fatigue was outrunning recovery. "
                "More load isn't the answer here; genuine easy days are.",
                "The plan protects recovery before adding stress.")
    if mode == "monotony":
        mono = round(float(g("monotony", 0) or 0), 1)
        detail = (f"Your training got monotonous (monotony ~{mono}) — " if mono > 0 else
                  "Your training got monotonous — ")
        return ("Too much of the same",
                detail + "most days landing in the same middle zone. Making hard days truly hard "
                "and easy days truly easy lowers the strain for the same total work.",
                "The plan spreads intensity instead of greying it together.")
    if mode == "fragile_ftp":
        dec = round(float(g("decoupling_pct", 0) or 0), 1)
        detail = (f"On your longer rides your heart rate drifted ~{dec}% above what your power "
                  "alone would predict — " if dec > 0 else
                  "On your longer rides your heart rate drifted up off your power — ")
        return ("Endurance fraying on long rides",
                detail + "a sign the aerobic engine fatigues late. More steady endurance time "
                "firms this up.",
                "The plan keeps long aerobic rides in the mix.")
    if mode == "injury_spike":
        acwr = float(g("acwr", 1.0) or 1.0)
        detail = (f"In one week you piled on about {_pct(acwr)}% more than your recent normal — "
                  if acwr > 1.0 else "In one week you piled on far more load than your recent "
                  "normal — ")
        return ("A sharp load spike",
                detail + "the kind of jump that tends to precede setbacks. Ramping in beats "
                "leaping.",
                "Why the plan caps how fast you add load.")
    return (mode.replace("_", " "), "A flagged training pattern.", None)


def _direction(end, as_of):
    days = (_d(as_of) - end).days
    if days <= _ONGOING_DAYS:
        return "ongoing"
    if days <= 120:
        return "recently resolved"
    return "earlier this year"


def _failure_insights(findings, m, as_of, top_n):
    """One representative (most-recent) episode per active mode, ranked by action priority then
    recency, capped to top_n."""
    by_mode = {}
    for f in findings:
        if f["severity"] != "confirmed":
            continue
        if pd.Timestamp(f["window_end"]) > pd.Timestamp(as_of):
            continue
        by_mode.setdefault(f["mode_id"], []).append(f)

    cands = []
    for mode, fs in by_mode.items():
        eps = _episodes(fs)
        if not eps:
            continue
        ep = max(eps, key=lambda e: e["end"])          # most recent episode of this mode
        cands.append((mode, ep))
    # rank: highest action priority first, then most recent
    cands.sort(key=lambda me: (DETECTORS.priority.get(me[0], 99), -me[1]["end"].toordinal()))

    out = []
    for mode, ep in cands[:top_n]:
        tone, mood = _TONE.get(mode, ("hold", "calm"))
        title, read, plan = _template(mode, ep["ev"])
        out.append({
            "id": mode, "mode_id": mode,
            "zone_start": ep["start"].isoformat(), "zone_end": ep["end"].isoformat(),
            "anchor_date": ep["end"].isoformat(),
            "color": tone, "mood": mood, "strength": False,
            "title": title, "read": read,
            "direction": _direction(ep["end"], as_of), "plan": plan,
        })
    return out


def _now_insight(m, as_of):
    """Always-present read of the current state — Wattson tells you what 'now' means."""
    ao = pd.Timestamp(as_of)
    ctl = m.daily.loc[m.daily.index <= ao, "ctl"].dropna()
    if ctl.empty:
        return None
    ctl_now = float(ctl.iloc[-1])
    tsb_now = float(m.tsb.asof(ao)) if not m.tsb.dropna().empty else 0.0
    recent = ctl[ctl.index > ao - pd.Timedelta(days=28)]
    chg = float(recent.iloc[-1] - recent.iloc[0]) if len(recent) >= 2 else 0.0

    thr = m.ctl_percentile_threshold(m.profile.detraining_pctile, as_of=True).asof(ao)
    below = (thr is not None) and (not pd.isna(thr)) and (ctl_now < float(thr))

    if below and tsb_now > 0:
        title = "Fresh on paper, light on fitness"
        read = ("Your form reads fresh only because there's so little fatigue — not because "
                "you're race-ready. The ceiling right now is your low fitness, not your "
                "freshness, so don't let feeling good tempt a big week.")
        mood = "calm"
    elif below:
        title = "Fitness is below your normal range"
        read = ("Your fitness is sitting under where it usually lives for you. Nothing's wrong — "
                "but it's a rebuild, and rebuilds reward steady consistency over hero weeks.")
        mood = "calm"
    elif chg > 1:
        title = "Building, and holding it"
        read = ("Fitness is trending up and you're absorbing the load. This is the good kind of "
                "stress — keep the ramp honest and it'll keep paying off.")
        mood = "approving"
    else:
        title = "Holding steady"
        read = ("Fitness is roughly flat — you're maintaining. Fine for now; when you want to "
                "build again, a gentle, consistent ramp is the lever.")
        mood = "calm"

    dirn = "trending up" if chg > 1 else "sliding" if chg < -1 else "holding"
    return {"id": "now", "mode_id": "now", "zone_start": None, "zone_end": None,
            "anchor_date": ctl.index[-1].strftime("%Y-%m-%d"), "color": "gold", "mood": mood,
            "strength": False, "title": title, "read": read, "direction": dirn, "plan": None}


def _strength_insight(m, as_of, safe_ramp):
    """The athlete's cleanest sustained build — surface what WORKS, not only what's wrong.
    A window whose CTL gain was largely held (not given straight back). None if history is thin."""
    wk = m.weekly_ctl().dropna()
    wk = wk[wk.index <= pd.Timestamp(as_of)]
    if len(wk) < 16:
        return None
    vals, idx = wk.values, wk.index
    best = None
    span = 10                                          # ~10-week build window
    for i in range(len(vals) - span):
        j = i + span
        gain = vals[j] - vals[i]
        if gain < 5:
            continue
        future = vals[j:min(len(vals), j + 4)]         # held over the next ~month?
        if future.min() < vals[i] + 0.6 * gain:
            continue
        if best is None or gain > best["gain"]:
            best = {"gain": gain, "i": i, "j": j}
    if not best:
        return None
    g = round(float(best["gain"]))
    return {"id": "build", "mode_id": "proven_build",
            "zone_start": idx[best["i"]].strftime("%Y-%m-%d"),
            "zone_end": idx[best["j"]].strftime("%Y-%m-%d"),
            "anchor_date": idx[best["j"]].strftime("%Y-%m-%d"),
            "color": "green", "mood": "approving", "strength": True,
            "title": "Your proven safe build",
            "read": (f"Your cleanest stretch — about +{g} fitness over {span} weeks that you "
                     "actually held onto, no crash after. This is the build your body has shown "
                     "it can absorb, and it's the ramp the plan trusts."),
            "direction": "reference",
            "plan": f"Anchors your safe ramp of ~{round(safe_ramp, 1)} fitness/week."}


def build_trend(m, findings, as_of, top_failures=3, plan_weeks=None):
    """Assemble the full trend-view payload for `as_of`. `plan_weeks` (optional) lets the hover
    scrubber show the training block a week belongs to, where the plan covers it."""
    as_of = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    safe_ramp = m.personal_sustainable_ramp()
    if safe_ramp is None:
        safe_ramp = float(m.profile.ramp_rate_cap)

    insights = _failure_insights(findings, m, as_of, top_failures)
    now = _now_insight(m, as_of)
    if now:
        insights.append(now)
    strength = _strength_insight(m, as_of, safe_ramp)
    if strength:
        insights.append(strength)

    series = weekly_series(m, as_of)
    _attach_blocks(series, plan_weeks)
    return {
        "as_of": as_of,
        "date_min": series[0]["date"] if series else as_of,
        "safe_ramp": round(float(safe_ramp), 1),
        "series": series,
        "insights": insights,
    }
