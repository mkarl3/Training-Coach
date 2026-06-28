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


_RULE_LABEL = "COACH WATTSON'S TAKE"       # historical/strength: his voice on what the trend taught
_PLAN_LABEL = "WHAT YOUR PLAN IS DOING"    # the now-insight: the live prescription


def _template(mode, ev, meta):
    """For a mode + its evidence: (title, observation, lesson, rule-it-created). Plain language,
    no jargon. The 'rule' connects the diagnosis to the actual guardrail it informs (THE ONE
    RULE: the trend shapes deterministic plan constants — Wattson just names which one)."""
    g = ev.get
    ratio = (meta or {}).get("safe_acute_ratio")
    jump_pct = f"about {_pct(ratio)}%" if ratio else "too far"
    if mode == "gap_unravel":
        drop = round(float(g("ctl_decline_over_window", 0) or 0))
        peak = round(float(g("ctl_peak_before", 0) or 0))
        obs = (f"You'd built to a fitness peak (~{peak}), then the thread broke — usually a gap "
               f"off the bike — and ~{drop} points of that fitness drained away."
               if peak > 0 and drop > 0 else
               "You'd been building, then the thread broke — usually a gap off the bike — and "
               "fitness started draining away.")
        return ("Fitness leak after a peak", obs,
                "Fitness lost this way takes roughly twice as long to win back as it took to "
                "lose, so the goal is to rebuild steadily, not chase the old peak.",
                f"Here's my read: you grabbed fitness in a leap, then lost the thread and watched "
                f"it drain right back out. I'm not letting that happen to you twice — it's exactly "
                f"why I keep a lid on your weekly jumps at {jump_pct} over your recent normal.")
    if mode == "under_load":
        floor = round(float(g("floor", 0) or 0))
        recent = round(float(g("recent_peak_ctl", 0) or 0))
        obs = (f"Your weekly load sat under the base you've shown you can hold (~{floor}), and "
               f"fitness drifted to ~{recent}." if floor > 0 else
               "Your weekly load sat under the base you've shown you can hold.")
        return ("Training below your sustainable base", obs,
                "Under-stimulating — steady consistency rebuilds this, not the occasional big day.",
                "My take: you've been training under what you can handle, and the fitness quietly "
                "slipped away. So I'm walking your weekly load back up toward your base — steady, "
                "a step at a time, no rush.")
    if mode == "overtraining":
        return ("Dug into a fatigue hole",
                "Your form sat deep in the red for a stretch — fatigue was outrunning recovery.",
                "More load is the wrong lever here; genuine easy days are what dig you out.",
                "Straight talk: you were burying yourself and recovery couldn't keep up. I guard "
                "your easy days before I ever pile on more stress — that's how we climb out.")
    if mode == "monotony":
        mono = round(float(g("monotony", 0) or 0), 1)
        obs = (f"Your training got monotonous (monotony ~{mono}) — most days landing in the same "
               "middle zone." if mono > 0 else
               "Your training got monotonous — most days landing in the same middle zone.")
        return ("Too much of the same", obs,
                "One-flavour training raises the strain for the same total work.",
                "Here's the thing — it all looked the same, and that grinds you down for no extra "
                "payoff. I'll keep your hard days truly hard and your easy days truly easy, so "
                "every session earns its place.")
    if mode == "fragile_ftp":
        dec = round(float(g("decoupling_pct", 0) or 0), 1)
        obs = (f"On your longer rides your heart rate drifted ~{dec}% above what your power alone "
               "would predict." if dec > 0 else
               "On your longer rides your heart rate drifted up off your power.")
        return ("Endurance fraying on long rides", obs,
                "A durability signal — the aerobic engine fatiguing late, not a fitness problem.",
                "What I see: your engine frays a little late on the long ones. Nothing's broken — "
                "we just bank more steady aerobic time and firm it right up.")
    if mode == "injury_spike":
        acwr = float(g("acwr", 1.0) or 1.0)
        obs = (f"In one week you piled on about {_pct(acwr)}% more than your recent normal."
               if acwr > 1.0 else "In one week you piled on far more load than your recent normal.")
        return ("A sharp load spike", obs,
                "Big single-week jumps are the kind of thing that tends to precede setbacks.",
                f"My take: too much, too fast — the kind of jump that gets people hurt. I keep a "
                f"firm lid on it for you, no more than {jump_pct} over your recent normal in a "
                "week.")
    return (mode.replace("_", " "), "A flagged training pattern.", "", "")


def _direction(end, as_of):
    days = (_d(as_of) - end).days
    if days <= _ONGOING_DAYS:
        return "ongoing"
    if days <= 120:
        return "recently resolved"
    return "earlier this year"


def _failure_insights(findings, m, as_of, top_n, meta):
    """One representative (most-recent) episode per active mode, ranked by action priority then
    recency, capped to top_n. Each carries observation -> lesson -> the rule it created."""
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
    cands.sort(key=lambda me: (DETECTORS.priority.get(me[0], 99), -me[1]["end"].toordinal()))

    out = []
    for mode, ep in cands[:top_n]:
        tone, mood = _TONE.get(mode, ("hold", "calm"))
        title, obs, mean, act = _template(mode, ep["ev"], meta)
        out.append({
            "id": mode, "mode_id": mode,
            "zone_start": ep["start"].isoformat(), "zone_end": ep["end"].isoformat(),
            "anchor_date": ep["end"].isoformat(),
            "color": tone, "mood": mood, "strength": False,
            "title": title, "obs": obs, "mean": mean, "act": act, "act_label": _RULE_LABEL,
            "direction": _direction(ep["end"], as_of), "proj": None, "cta": False,
        })
    return out


def _now_insight(m, as_of, plan, proj_text):
    """Always-present read of the current state, ending in the LIVE prescription pulled from the
    plan (real week-1 numbers) plus the forward projection and a 'see this week' CTA."""
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
        title, mood = "Fresh on paper, light on fitness", "calm"
        obs = ("Your fitness is below your normal range, and your form only reads fresh because "
               "there's so little fatigue.")
        mean = ("The ceiling right now is your low fitness, not your freshness — chasing that "
                "green form with a big week is exactly how a crash starts.")
    elif below:
        title, mood = "Fitness is below your normal range", "calm"
        obs = "Your fitness is sitting under where it usually lives for you."
        mean = "It's a rebuild — and rebuilds reward steady consistency over hero weeks."
    elif chg > 1:
        title, mood = "Building, and holding it", "approving"
        obs = "Fitness is trending up and you're absorbing the load."
        mean = "This is the good kind of stress — keep the ramp honest and it keeps paying off."
    else:
        title, mood = "Holding steady", "calm"
        obs = "Fitness is roughly flat — you're maintaining."
        mean = "Fine for now; when you want to build, a gentle, consistent ramp is the lever."

    act = _prescription(plan)
    dirn = "trending up" if chg > 1 else "sliding" if chg < -1 else "holding"
    return {"id": "now", "mode_id": "now", "zone_start": None, "zone_end": None,
            "anchor_date": ctl.index[-1].strftime("%Y-%m-%d"), "color": "gold", "mood": mood,
            "strength": False, "title": title, "obs": obs, "mean": mean, "act": act,
            "act_label": _PLAN_LABEL, "direction": dirn, "proj": proj_text, "cta": bool(plan)}


def _prescription(plan):
    """The live week-1 prescription, in plain words, from the generator's own numbers."""
    if not plan or not plan.get("weeks"):
        return ("Your rebuild is a steady, consistent ramp — no hero weeks. Open the plan to see "
                "this week's target.")
    w0, meta = plan["weeks"][0], plan.get("meta", {})
    tss = w0.get("weekly_tss_target")
    cap = w0.get("single_ride_tss_cap")
    ramp = meta.get("sustainable_ramp") or meta.get("ramp_cap")
    recent = meta.get("recent_weekly_tss")
    bits = []
    if tss:
        bits.append(f"opens at {tss} TSS"
                    + (f" — a safe step from your recent ~{recent}" if recent else ""))
    if cap:
        bits.append(f"caps single rides at {cap}")
    if ramp:
        bits.append(f"won't ramp faster than {round(float(ramp), 1)} fitness/week")
    if not bits:
        return "Open the plan to see this week's target."
    return "Next week " + ", ".join(bits) + ". Your job is consistency, not hero days."


def _strength_insight(m, as_of, safe_ramp):
    """The athlete's cleanest sustained build — what WORKS, and the ramp it anchors."""
    wk = m.weekly_ctl().dropna()
    wk = wk[wk.index <= pd.Timestamp(as_of)]
    if len(wk) < 16:
        return None
    vals, idx = wk.values, wk.index
    best = None
    span = 10
    for i in range(len(vals) - span):
        j = i + span
        gain = vals[j] - vals[i]
        if gain < 5:
            continue
        future = vals[j:min(len(vals), j + 4)]
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
            "obs": f"Your cleanest stretch — about +{g} fitness over {span} weeks that you "
                   "actually held onto, with no crash afterward.",
            "mean": "This is the ramp your body has shown it can absorb and keep.",
            "act": f"This one I like: you built clean and made it stick. That's the ramp I trust "
                   f"for you — about {round(safe_ramp, 1)} fitness a week — and I won't push you "
                   "past what you've already proven you can hold.",
            "act_label": _RULE_LABEL, "direction": "reference", "proj": None, "cta": False}


def _projection(plan):
    """Deterministic forward fitness line = the plan's own per-week CTL targets (THE ONE RULE:
    the generator computes these; we just plot them). Returns points + the peak it reaches."""
    if not plan or not plan.get("weeks"):
        return None
    pts = [{"date": w["week_end"], "ctl": round(float(w["ctl_target"]), 1)}
           for w in plan["weeks"] if w.get("ctl_target") is not None]
    if not pts:
        return None
    peak = max(pts, key=lambda p: p["ctl"])
    return {"points": pts, "target_ctl": peak["ctl"], "target_date": peak["date"]}


def _proj_text(projection):
    if not projection:
        return None
    d = dt.date.fromisoformat(projection["target_date"])
    return (f"Hold this plan and your fitness climbs back to about {round(projection['target_ctl'])} "
            f"by {_MONTHS[d.month - 1]} {d.year}.")


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]


def _directive(plan, below, chg):
    """This week's one-line marching order, with the real week-1 target broken out so the UI can
    emphasise the number."""
    if plan and plan.get("weeks") and plan["weeks"][0].get("weekly_tss_target"):
        tss = plan["weeks"][0]["weekly_tss_target"]
        if below:
            return {"pre": "This week we start the rebuild — ", "tss": tss,
                    "post": ", nice and steady. No hero days."}
        if chg > 1:
            return {"pre": "This week we keep building — ", "tss": tss,
                    "post": ", right on your safe ramp."}
        return {"pre": "This week we hold the line — ", "tss": tss,
                "post": ". Consistency over heroics."}
    return {"pre": "Keep it steady and consistent this week.", "tss": None, "post": ""}


def _hero(m, as_of, plan, status):
    """The dashboard hero brief: Wattson's one-line read of right now + this week's directive +
    glanceable vitals. Same deterministic signals as the now-insight, distilled to a glance."""
    ao = pd.Timestamp(as_of)
    ctl = m.daily.loc[m.daily.index <= ao, "ctl"].dropna()
    if ctl.empty:
        return None
    ctl_now = float(ctl.iloc[-1])
    tsb = m.tsb.dropna()
    tsb_now = float(tsb.asof(ao)) if not tsb.empty else 0.0
    recent = ctl[ctl.index > ao - pd.Timedelta(days=28)]
    chg = float(recent.iloc[-1] - recent.iloc[0]) if len(recent) >= 2 else 0.0
    thr = m.ctl_percentile_threshold(m.profile.detraining_pctile, as_of=True).asof(ao)
    below = (thr is not None) and (not pd.isna(thr)) and (ctl_now < float(thr))

    if below and tsb_now > 0:
        headline, mood = "You're fresh, but light on fitness right now.", "calm"
    elif below:
        headline, mood = "Fitness is down — time to rebuild.", "calm"
    elif chg > 1:
        headline, mood = "Fitness is climbing, and you're absorbing it.", "approving"
    else:
        headline, mood = "Holding steady — fitness banked and maintained.", "calm"
    if status == "alert":
        mood = "alarmed"
    elif status == "watch" and mood == "approving":
        mood = "calm"          # something's on the watch list — read steady, don't beam

    fdir = "rising" if chg > 1 else "sliding" if chg < -1 else "holding"
    form_lab = "fresh" if tsb_now > 5 else "run down" if tsb_now < -15 else "neutral"
    accent = {"green": "good", "alert": "alarm"}.get(status, "watch")
    return {
        "mood": mood, "status": status or "watch", "accent": accent,
        "headline": headline, "directive": _directive(plan, below, chg),
        "vitals": {"fitness": {"value": round(ctl_now), "dir": fdir},
                   "form": {"value": round(tsb_now), "label": form_lab}},
    }


# Per-system PD reads — shared by the "Your systems" panel (/api/systems) and the dashboard
# narrative so the two never disagree. (col, display unit). TTE is stored in seconds, shown in min.
_SYS_DEFS = (("mftp_w", "W"), ("pvo2max_w", "W"), ("pmax_w", "W"), ("tte_sec", "min"))


def systems_read(m, as_of):
    """Current value + recent direction for each modeled system, as of `as_of`. Direction = recent
    28-day mean vs the prior 28–84-day mean, with a ±2% dead-band (rising/falling/flat). Returns a
    dict keyed by column, each {value, unit, dir, delta_pct, spark}. Deterministic; THE ONE RULE."""
    ao = pd.Timestamp(as_of)
    daily = m.daily
    out = {}
    for col, unit in _SYS_DEFS:
        if col not in daily.columns:
            continue
        s = pd.to_numeric(daily[col], errors="coerce")
        s = s[s.index <= ao].dropna()
        if s.empty:
            continue
        cur = float(s.iloc[-1])
        recent = s[s.index > ao - pd.Timedelta(days=28)].mean()
        prior = s[(s.index <= ao - pd.Timedelta(days=28)) & (s.index > ao - pd.Timedelta(days=84))].mean()
        chg = (recent - prior) / prior * 100 if (prior and pd.notna(prior) and prior > 0) else 0.0
        direction = "rising" if chg > 2 else "falling" if chg < -2 else "flat"
        value = round(cur / 60, 1) if unit == "min" else round(cur)
        sw = s.resample("W").last().dropna().tail(40)
        # Spark points carry the SAME unit/precision as the headline value (minutes for TTE, whole
        # watts otherwise) so the hover readout and detail axis never disagree with the big number.
        spark = [round(float(v) / 60, 1) if unit == "min" else round(float(v)) for v in sw]
        spark_weeks = [d.date().isoformat() for d in sw.index]   # week-end date per spark point (hover readout)
        out[col] = {"value": value, "unit": unit, "dir": direction,
                    "delta_pct": round(chg, 1), "spark": spark, "spark_weeks": spark_weeks}
    return out


def build_trend(m, findings, as_of, top_failures=3, plan=None, status=None):
    """Assemble the full trend-view payload for `as_of`. `plan` (optional) supplies the training
    blocks (hover scrubber), the live prescription (now-insight), and the forward projection."""
    as_of = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    meta = (plan or {}).get("meta", {})
    plan_weeks = (plan or {}).get("weeks")
    safe_ramp = m.personal_sustainable_ramp()
    if safe_ramp is None:
        safe_ramp = float(m.profile.ramp_rate_cap)

    projection = _projection(plan)
    insights = _failure_insights(findings, m, as_of, top_failures, meta)
    now = _now_insight(m, as_of, plan, _proj_text(projection))
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
        "hero": _hero(m, as_of, plan, status),
        "series": series,
        "projection": projection,
        "insights": insights,
    }
