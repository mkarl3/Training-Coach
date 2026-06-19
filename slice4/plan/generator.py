"""Deterministic plan-skeleton generator (Slice 4, step 2 — the core).

BASELINE STRUCTURE = the project's Periodization Matrix (Friel periods + WKO development
sequencing), scaled to the weeks available. On top of that baseline, this athlete's failure
modes (from the profile) act as guardrails and their real availability (from the season)
binds the load. Pure + deterministic: same inputs -> same plan, every week traceable to the
rule that set it.

THE BOUNDARY: this is code. The LLM coach explains and triggers recompute; it never writes
these numbers.

Inputs are plain data (DB-agnostic, testable):
  season: {"start_date","weekly_hours_budget"}
  events / unavailable: lists of dicts
Reads the Metrics facade for current/historical CTL + the demonstrated floor + actual TSS;
the profile for the ramp cap, masters flag, and week-start preference.
"""
import datetime as dt

import pandas as pd

from .config import DEFAULT_CALENDAR


def _week_start(d, week_starts_on="monday"):
    """Align a date to the start of its week (Monday, or Sunday if the athlete prefers)."""
    if week_starts_on == "sunday":
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return d - dt.timedelta(days=d.weekday())


def _overlaps(ws, we, periods):
    for p in periods:
        ps = dt.date.fromisoformat(p["start_date"])
        pe = dt.date.fromisoformat(p["end_date"])
        if ws <= pe and ps <= we:
            return p
    return None


def pick_a_race(events, today):
    """The next A-priority event on/after today; fall back to the next event of any priority."""
    fut = [e for e in events if dt.date.fromisoformat(e["event_date"]) >= today]
    a = [e for e in fut if e["priority"] == "A"]
    pool = a or fut
    return min(pool, key=lambda e: e["event_date"]) if pool else None


def fit_blocks(n_weeks, cfg):
    """Scale the canonical matrix blocks to n_weeks, preserving the Friel sequence and the
    matrix's base-heavy proportions. Returns a per-week list of (block, is_last_week_of_block)."""
    race_w = cfg.race_weeks if n_weeks >= 3 else (1 if n_weeks >= 2 else 0)
    peak_w = cfg.peak_weeks if (n_weeks - race_w) >= 8 else (1 if (n_weeks - race_w) >= 4 else 0)
    R = max(0, n_weeks - race_w - peak_w)

    bb = [b for b in cfg.canonical_blocks if b[1] in ("base", "build")]   # Prep .. Build 2
    tot = sum(b[2] for b in bb)
    raw = [b[2] * R / tot for b in bb] if tot else [0] * len(bb)
    alloc = [int(x) for x in raw]
    for i in sorted(range(len(bb)), key=lambda i: raw[i] - alloc[i], reverse=True)[: R - sum(alloc)]:
        alloc[i] += 1

    peak_block = next(b for b in cfg.canonical_blocks if b[1] == "peak")
    race_block = next(b for b in cfg.canonical_blocks if b[1] == "taper")

    seq = []
    for b, a in zip(bb, alloc):
        seq += [(b, k == a - 1) for k in range(a)]
    seq += [(peak_block, k == peak_w - 1) for k in range(peak_w)]
    seq += [(race_block, k == race_w - 1) for k in range(race_w)]
    return seq[:n_weeks]


def diff_plans(old, new):
    """What a proposed input change WOULD do — computed by comparing two generated plans, never
    by hand-editing numbers. Returns changed weeks (keyed by week_start) + a headline summary.
    The propose step shows this; nothing is applied until the athlete confirms."""
    if not old or "error" in old:
        return {"error_old": old.get("error") if old else "no prior plan"}
    if "error" in new:
        return {"error_new": new["error"]}
    ow = {w["week_start"]: w for w in old["weeks"]}
    nw = {w["week_start"]: w for w in new["weeks"]}
    fields = ("weekly_tss_target", "ctl_target", "planned_ramp", "is_recovery",
              "intensity_capped", "prescribed_distribution")
    changed = []
    for ws in sorted(set(ow) | set(nw)):
        a, b = ow.get(ws), nw.get(ws)
        if a is None:
            changed.append({"week_start": ws, "added": True, "block": b["block"]})
            continue
        if b is None:
            changed.append({"week_start": ws, "removed": True, "block": a["block"]})
            continue
        deltas = {f: [a.get(f), b.get(f)] for f in fields if a.get(f) != b.get(f)}
        if deltas:
            changed.append({"week_start": ws, "week": b["week"], "block": b["block"], "deltas": deltas})
    om, nm = old["meta"], new["meta"]
    return {
        "weeks_changed": changed,
        "n_changed": len(changed),
        "summary": {
            "weeks": [om["weeks"], nm["weeks"]],
            "peak_ctl_achieved": [om["peak_ctl_achieved"], nm["peak_ctl_achieved"]],
            "target_peak_ctl": [om["target_peak_ctl"], nm["target_peak_ctl"]],
            "target_reached": [om["target_reached"], nm["target_reached"]],
        },
    }


def generate_plan(m, profile, season, events, unavailable, as_of, cfg=DEFAULT_CALENDAR,
                  availability=None, intensity_caps=None, readiness=None):
    """Return {"meta": {...}, "weeks": [...]} or {"error": ...}. The plan spans the whole
    season (start -> A-race); weeks already elapsed carry ACTUAL TSS/CTL for planned-vs-actual.

    Transient diary-driven modifiers (Slice 4.5), each a list of {start_date,end_date,...}:
      availability   per-week hours overrides {hours, reason} — relax/tighten the time budget
                     for the overlapping week (an opportunity UP just hands the binding role to
                     the ramp/ACWR/target guardrails; it does NOT relax them).
      intensity_caps {reason} windows that hold the week easy (ramp <= 0, aerobic only) — the
                     'keep it easy' of a re-entry or an ongoing limiter. Caps can only TIGHTEN.
    """
    availability = availability or []
    intensity_caps = intensity_caps or []
    readiness = readiness or []                       # subjective (check-in) readiness ease windows
    today = dt.date.fromisoformat(as_of)
    wstart = profile.week_starts_on
    a_race = pick_a_race(events, today)
    if a_race is None:
        return {"error": "no goal event on or after the current data date"}
    a_date = dt.date.fromisoformat(a_race["event_date"])

    plan_start = _week_start(dt.date.fromisoformat(season["start_date"]), wstart)
    race_week = _week_start(a_date, wstart)
    if race_week < plan_start:
        return {"error": "A-race falls before the season start"}
    weeks = []
    w = plan_start
    while w <= race_week:
        weeks.append(w)
        w += dt.timedelta(days=7)
    N = len(weeks)
    seq = fit_blocks(N, cfg)

    # --- anchors (nothing re-derived): planned trajectory starts from CTL at season start ---
    anchor_ctl = float(m.ctl.asof(pd.Timestamp(plan_start.isoformat())))
    floor = float(m.personal_ctl_floor().iloc[-1])
    target_peak_ctl = max(floor, anchor_ctl + 3.0)
    masters = profile.is_masters(a_date.year)
    budget_h = season["weekly_hours_budget"]
    label, plan_if, distribution, long_priority = cfg.emphasis.get(
        a_race["event_type"], cfg.default_emphasis)
    if2 = plan_if * plan_if

    # --- monotony guardrail: gate hard/easy separation on THIS athlete's gray-zone tendency ---
    # The monotony fingerprint's distribution legs (detectors.py): time in the gray IF band and
    # TiZ narrowing. We read them as-of the plan date against the SAME profile thresholds the
    # detector uses, so the plan only tightens separation when this athlete actually trends
    # gray-zone — not as a blanket prescription.
    ts = pd.Timestamp(as_of)
    gb = m.gray_zone_if_fraction().asof(ts)
    tc = m.tiz_power_concentration().asof(ts)
    gray_band = None if pd.isna(gb) else round(float(gb), 2)
    tiz_conc = None if pd.isna(tc) else round(float(tc), 2)
    band_cap, conc_cap = profile.monotony_band_frac, profile.tiz_concentration_watch
    band_hot = gray_band is not None and gray_band >= band_cap
    conc_hot = tiz_conc is not None and tiz_conc >= conc_cap
    monotony_prone = band_hot or conc_hot
    if monotony_prone:
        why = []
        if band_hot:
            why.append(f"gray-band {gray_band:.0%}>={band_cap:.0%}")
        if conc_hot:
            why.append(f"TiZ concentration {tiz_conc}>={conc_cap}")
        mono_note = ("monotony guardrail (" + ", ".join(why) + "): enforce hard/easy separation "
                     "— easy days capped at Z2, quality concentrated; no gray-zone filler")
        distribution = "STRICT polarized (monotony guard) — " + distribution
    rec_every = cfg.rec_every_masters if masters else cfg.rec_every_open
    trough = cfg.recovery_dip * (cfg.masters_trough_factor if masters else 1.0)
    ramp_coef = 0.5 * 7 + cfg.pmc_decay_days                  # weekly_tss = 7*ctl + ramp_coef*ramp
    daily = m.daily

    # --- ramp magnitude from the athlete's DEMONSTRATED-SAFE ramp, not a generic number ---
    # Anchor the base target to what this athlete has actually absorbed-and-kept; scale build
    # down by the method's base:build ratio so the periodization shape (base > build) holds.
    # Fall back to the config defaults when history can't demonstrate a sustainable ramp.
    psr = m.personal_sustainable_ramp()
    ramp_source = "history" if psr is not None else "default"
    base_ramp = psr if psr is not None else cfg.ramp_base
    build_ramp = (round(base_ramp * cfg.ramp_build / cfg.ramp_base, 1)
                  if psr is not None else cfg.ramp_build)
    family_ramp = {"base": base_ramp, "build": build_ramp, "peak": cfg.ramp_peak}

    # ramp CEILING derived from the athlete's demonstrated ramp (headroom above their sustainable
    # target), NOT a generic default; falls back to the profile cap only if history is thin.
    ramp_cap = round(1.5 * psr, 1) if psr is not None else profile.ramp_rate_cap

    # acute-load guardrail: the athlete's demonstrated-safe weekly JUMP over their recent baseline.
    # Bounds how fast prescribed load can rise off a gap / under-training — the place a CTL-slope
    # cap can't see the spike. Derived from summed actual TSS; conservative default if history thin.
    safe_ratio = m.personal_safe_acute_ratio() or 1.3

    # READINESS (tighten-only): how much of that safe jump to actually allow right now. Two inputs,
    # take the more conservative — neither can raise the demonstrated ceiling, only ease below it:
    #   subjective — what the athlete reported at check-in ("feeling fried"), a windowed ease that
    #                decays (read per-week from `readiness`);
    #   objective  — a form (TSB) backstop that catches fatigue they didn't mention. Applies to the
    #                near-term weeks only (current fatigue is a now-thing).
    obj_readiness = m.readiness_from_form(as_of)

    # recent-load baselines from SUMMED ACTUAL weekly TSS before plan start (drop empty weeks).
    # load_hist drives the acute cap (recent ~4-wk avg) AND the 50% single-ride rule (rolling
    # ~6-wk avg). Prescribed weeks append as the plan builds, so both caps roll forward.
    seed = []
    for k in range(6, 0, -1):
        ws = plan_start - dt.timedelta(days=7 * k)
        s = daily.loc[ws.isoformat():(ws + dt.timedelta(days=6)).isoformat(), "tss_sum"].dropna().sum()
        if s > 0:
            seed.append(round(float(s)))
    load_hist = list(seed)

    rows = []
    ctl = anchor_ctl
    bb_week = 0
    for i, (mon, (block, is_last)) in enumerate(zip(weeks, seq)):
        we = mon + dt.timedelta(days=6)
        bname, family, _nom, focus, target_metric, advance_when = block
        fired, rationale = [], [f"{bname} ({focus}) — nominal "]

        # 1. ramp by block family (taper proportional)
        if family == "taper":
            ramp = -round(cfg.taper_frac * ctl, 1)
            rationale[0] += f"taper -{cfg.taper_frac:.0%}/wk ({ramp:+.1f} CTL)"
        else:
            ramp = family_ramp[family]
            src = (" (your demonstrated sustainable ramp)" if ramp_source == "history"
                   and family in ("base", "build") else
                   " (method default — history too thin)" if family in ("base", "build") else "")
            rationale[0] += f"{ramp:+.1f} CTL/wk{src}"

        # 2. recovery troughs (built-in recovery this athlete habitually skips)
        is_recovery = False
        if family in ("base", "build"):
            bb_week += 1
            if bb_week % rec_every == 0:
                is_recovery, ramp = True, -trough
                fired.append(f"recovery week (every {rec_every}{' masters' if masters else ''}, "
                             f"trough {ramp:+.1f})")

        # 3. ramp cap — spike-then-crash guardrail
        if ramp > ramp_cap:
            fired.append(f"ramp_cap {ramp:+.1f}->{ramp_cap:+.1f} CTL/wk")
            ramp = ramp_cap
        # 4. don't overshoot target during base/build
        if family in ("base", "build") and ctl + ramp > target_peak_ctl:
            ramp = max(0.0, target_peak_ctl - ctl)
            fired.append(f"target reached (cap to {target_peak_ctl:.0f})")
        # 5. known-unavailable -> forced recovery
        ua = _overlaps(mon, we, unavailable)
        if ua:
            is_recovery, ramp = True, min(ramp, -trough)
            fired.append(f"unavailable ({ua.get('reason') or 'blocked'}) -> recovery")
        # 5b. intensity cap (re-entry / ongoing limiter "keep it easy") -> hold, aerobic only
        icap = _overlaps(mon, we, intensity_caps)
        intensity_capped = bool(icap)
        if icap:
            ramp = min(ramp, 0.0)                          # tighten only: hold CTL, don't build
            fired.append(f"intensity cap ({icap.get('reason') or 'easy'}) -> aerobic only, hold CTL")

        target = ctl + ramp
        weekly_tss = 7 * ctl + ramp_coef * ramp           # CTL-derived target load for this ramp
        # 6. caps — the most restrictive of (acute-load step, time budget) re-derives the ramp.
        #    ACUTE: don't pile on more than a demonstrated-safe step over the recent baseline — this
        #    catches the re-entry spike a CTL-slope cap can't see. TIME: real available hours.
        #    A per-week availability override (diary) swaps the season budget for that week.
        av = _overlaps(mon, we, availability)
        week_hours = av["hours"] if av else budget_h
        budget_cap = week_hours * if2 * 100.0
        chronic = (sum(load_hist[-4:]) / len(load_hist[-4:])) if load_hist else 0.0
        # how much of the demonstrated-safe jump to allow this week — the more conservative of the
        # athlete's report and their form, both <= 1 (ease only). Objective backstop only near-term.
        rd = _overlaps(mon, we, readiness)
        subj_rd = rd["factor"] if rd else 1.0
        obj_rd = obj_readiness if 0 <= (mon - today).days < 21 else 1.0
        eff_rd = min(subj_rd, obj_rd)
        eff_ratio = 1.0 + (safe_ratio - 1.0) * eff_rd     # eff_rd<1 pulls the allowed jump toward 1.0 (hold)
        acute_cap = (eff_ratio * chronic) if chronic >= profile.acwr_min_chronic_load else float("inf")
        eff_cap = min(budget_cap, acute_cap)
        if weekly_tss > eff_cap and not ua:
            new_ramp = (eff_cap - 7 * ctl) / ramp_coef
            if acute_cap <= budget_cap:
                ease = ""
                if eff_rd < 1.0:
                    why = (rd.get("reason") or "you're feeling run-down") if subj_rd <= obj_rd else \
                          "your form is run-down right now"
                    ease = f" — eased ({why})"
                fired.append(f"acute-load cap -> {eff_cap:.0f} TSS: a safe step up from your recent "
                             f"~{chronic:.0f}/wk{ease}")
            elif round(ramp, 1) - round(new_ramp, 1) >= 0.1:
                fired.append(f"time budget ({week_hours:.1f} h/wk) -> {eff_cap:.0f} TSS")
            ramp, target, weekly_tss = new_ramp, ctl + new_ramp, eff_cap
        if av:
            fired.append(f"availability override {week_hours:.1f} h ({av.get('reason') or 'this week'}) "
                         f"— guardrails still bind the usable load")

        est_hours = weekly_tss / (if2 * 100.0)
        long_ride = (cfg.long_ride_hours.get(family) if long_priority and family in ("base", "build", "peak")
                     else None)
        weekly_tss_target = round(weekly_tss)
        # 50% rule (TrainerRoad dataset analysis): no single ride above half your 6-WEEK ROLLING
        # AVERAGE weekly TSS — relative to your established load, not this one planned week.
        load_hist.append(weekly_tss_target)
        six_wk_avg = sum(load_hist[-6:]) / len(load_hist[-6:])
        single_ride_cap = round(cfg.single_ride_cap_frac * six_wk_avg)
        # monotony guardrail fires on training weeks (where distribution is steerable)
        if monotony_prone and not is_recovery and family != "taper":
            fired.append(mono_note)

        # --- planned vs actual: elapsed weeks carry actuals from the facade ---
        status = "upcoming"
        actual_tss = actual_ctl = None
        if mon <= today:
            status = "elapsed" if we <= today else "current"
            seg = daily.loc[mon.isoformat():min(we, today).isoformat(), "tss_sum"].dropna()
            actual_tss = round(float(seg.sum())) if len(seg) else 0
            ac = m.ctl.asof(pd.Timestamp(min(we, today).isoformat()))
            actual_ctl = None if pd.isna(ac) else round(float(ac), 1)

        rows.append({
            "week": i + 1, "week_start": mon.isoformat(), "week_end": we.isoformat(),
            "block": bname, "family": family, "focus": focus,
            "target_metric": target_metric, "advance_when": advance_when,
            "field_test": bool(is_last and family != "taper" and not intensity_capped),
            "is_recovery": bool(is_recovery),
            "intensity_capped": intensity_capped,
            "status": status,
            "ctl_start": round(ctl, 1), "ctl_target": round(target, 1),
            "planned_ramp": round(ramp, 1),
            "weekly_tss_target": weekly_tss_target,
            "single_ride_tss_cap": single_ride_cap,
            "est_hours": round(est_hours, 1),
            "actual_tss": actual_tss, "actual_ctl": actual_ctl,
            "emphasis": label,
            "prescribed_distribution": "aerobic only — intensity capped" if intensity_capped else distribution,
            "long_ride_hours": long_ride,
            "rationale": "; ".join(rationale),
            "constraints_fired": fired,
        })
        ctl = target

    peak_achieved = round(max((r["ctl_target"] for r in rows), default=anchor_ctl), 1)
    block_weeks = {}
    for r in rows:
        block_weeks[r["block"]] = block_weeks.get(r["block"], 0) + 1
    return {
        "meta": {
            "a_race": {"name": a_race["name"], "date": a_race["event_date"],
                       "type": a_race["event_type"], "emphasis": label},
            "plan_start": plan_start.isoformat(), "weeks": N,
            "week_starts_on": wstart,
            "anchor_ctl": round(anchor_ctl, 1),
            "target_peak_ctl": round(target_peak_ctl, 1),
            "peak_ctl_achieved": peak_achieved,
            "target_reached": peak_achieved >= round(target_peak_ctl, 1) - 0.5,
            "personal_floor": round(floor, 1),
            "masters": masters, "ramp_cap": ramp_cap, "weekly_hours_budget": budget_h,
            "sustainable_ramp": psr, "ramp_source": ramp_source,
            "base_ramp": base_ramp, "build_ramp": build_ramp,
            "safe_acute_ratio": safe_ratio,
            "recent_weekly_tss": round(sum(seed[-4:]) / len(seed[-4:])) if seed else None,
            "readiness": {"objective_form": obj_readiness, "subjective_windows": len(readiness)},
            "block_weeks": block_weeks,
            "family_weeks": {f: sum(1 for r in rows if r["family"] == f)
                             for f in ("base", "build", "peak", "taper")},
            "distribution_rx": distribution,
            "monotony_guard": {
                "prone": monotony_prone,
                "gray_band_frac": gray_band, "gray_band_cap": band_cap,
                "tiz_concentration": tiz_conc, "tiz_concentration_cap": conc_cap,
            },
            "modifiers": {"availability": availability, "intensity_caps": intensity_caps},
        },
        "weeks": rows,
    }
