"""Weekly briefing (Slice 4.5 — the weekly check-in workflow).

The deterministic summary the coach opens the weekly check-in with: the week that just closed
(planned vs actual + did they hit it), where fitness/fatigue/form are trending, the board
status, what's prescribed next, and any recurring subjective themes. CODE computes every
number here; the coach narrates it and never recomputes it — same boundary as the calendar.

Pure w.r.t. its inputs: the Metrics facade (PMC + actual TSS), the generated plan (planned-vs-
actual already lives on each week), the watchman status string, and the recurring themes list.
"""
import datetime as dt

import pandas as pd

from wko_metrics.config import DETECTORS


def _asof(series, d):
    v = series.asof(pd.Timestamp(d))
    return None if pd.isna(v) else round(float(v), 1)


def _dir(delta, eps=0.5):
    return "flat" if abs(delta) < eps else ("up" if delta > 0 else "down")


def _pmc(series, today):
    """now, and the 7- and 28-day change, for one PMC series."""
    now = _asof(series, today.isoformat())
    d7 = _asof(series, (today - dt.timedelta(days=7)).isoformat())
    d28 = _asof(series, (today - dt.timedelta(days=28)).isoformat())
    out = {"now": now, "delta_7d": None if (now is None or d7 is None) else round(now - d7, 1),
           "delta_28d": None if (now is None or d28 is None) else round(now - d28, 1)}
    out["dir_7d"] = None if out["delta_7d"] is None else _dir(out["delta_7d"])
    return out


def _week_tss(daily, start, end):
    seg = daily.loc[start.isoformat():end.isoformat(), "tss_sum"].dropna()
    return round(float(seg.sum())) if len(seg) else 0


def weekly_briefing(m, plan, status, themes, as_of):
    """Return the structured weekly briefing (plain data). `plan` may be None (no season yet)."""
    today = dt.date.fromisoformat(as_of)
    daily = m.daily

    # --- the week that just closed: trailing 7 days ending at the data date ---
    wk_start = today - dt.timedelta(days=6)
    prev_start, prev_end = wk_start - dt.timedelta(days=7), wk_start - dt.timedelta(days=1)
    actual = _week_tss(daily, wk_start, today)
    prior = _week_tss(daily, prev_start, prev_end)

    # --- planned-vs-actual + what's next, IF a plan exists and is in season ---
    planned_tss = compliance = None
    closed_block = next_week = None
    if plan and "weeks" in plan:
        elapsed = [w for w in plan["weeks"] if w["week_end"] <= as_of]
        if elapsed:
            cw = elapsed[-1]
            closed_block = {"week": cw["week"], "block": cw["block"], "focus": cw["focus"]}
            planned_tss = cw["weekly_tss_target"]
            # use the plan's own actual if the closed plan-week aligns, else the trailing week
            a = cw["actual_tss"] if cw["actual_tss"] is not None else actual
            actual = a
            compliance = None if not planned_tss else round(100 * a / planned_tss)
        upcoming = [w for w in plan["weeks"] if w["week_start"] > as_of] or \
                   [w for w in plan["weeks"] if w["status"] == "current"]
        if upcoming:
            nw = upcoming[0]
            next_week = {"week": nw["week"], "week_start": nw["week_start"], "block": nw["block"],
                         "focus": nw["focus"], "weekly_tss_target": nw["weekly_tss_target"],
                         "single_ride_tss_cap": nw["single_ride_tss_cap"],
                         "est_hours": nw["est_hours"], "is_recovery": nw["is_recovery"],
                         "intensity_capped": nw.get("intensity_capped", False),
                         "long_ride_hours": nw["long_ride_hours"],
                         "distribution": nw["prescribed_distribution"],
                         "field_test": nw["field_test"]}

    return {
        "as_of": as_of,
        "week_reviewed": {"start": wk_start.isoformat(), "end": today.isoformat(),
                          "actual_tss": actual, "prior_week_tss": prior,
                          "planned_tss": planned_tss, "compliance_pct": compliance,
                          "block": closed_block},
        "pmc": {"ctl": _pmc(m.ctl, today), "atl": _pmc(m.atl, today), "tsb": _pmc(m.tsb, today)},
        "status": status,
        "next_week": next_week,
        "themes": themes or [],
        "in_season": next_week is not None or planned_tss is not None,
    }


def briefing_text(b):
    """A compact narration seed for the coach (it expands on this; it never re-derives numbers)."""
    wr, pmc = b["week_reviewed"], b["pmc"]
    lines = [f"Weekly check-in, data through {b['as_of']}. Board: {b['status']}."]
    if wr["planned_tss"] is not None:
        lines.append(f"Week just closed ({wr['block']['block'] if wr['block'] else '—'}): "
                     f"planned {wr['planned_tss']} TSS, did {wr['actual_tss']} "
                     f"({wr['compliance_pct']}% of plan).")
    else:
        lines.append(f"Last 7 days: {wr['actual_tss']} TSS (prior week {wr['prior_week_tss']}).")
    lines.append(f"Fitness CTL {pmc['ctl']['now']} ({pmc['ctl']['delta_7d']:+}/7d), "
                 f"fatigue ATL {pmc['atl']['now']}, form TSB {pmc['tsb']['now']}."
                 if pmc['ctl']['now'] is not None else "PMC not available.")
    if b["next_week"]:
        nw = b["next_week"]
        tag = " (recovery)" if nw["is_recovery"] else (" (easy/capped)" if nw["intensity_capped"] else "")
        lines.append(f"Next up — wk{nw['week']} {nw['block']}{tag}: {nw['weekly_tss_target']} TSS, "
                     f"single-ride cap {nw['single_ride_tss_cap']}, ~{nw['est_hours']}h"
                     f"{', FIELD TEST' if nw['field_test'] else ''}.")
    if b["themes"]:
        lines.append("Recurring in check-ins: "
                     + ", ".join(f"{t['label']} ×{t['checkins']}" for t in b["themes"]) + ".")
    return "\n".join(lines)


# --- merged dashboard card (hero + phase fused into one Wattson read) ---
_VERDICT_LABEL = {
    "ADVANCE": "READY TO ADVANCE", "HOLD": "HOLD", "NEEDS_BENCHMARK": "NEEDS A BENCHMARK",
    "PROCEED_WITH_DEBT": "PROCEED · RACE CLOCK", "BACK_OFF": "BACK OFF",
    "NOT_STARTED": "NEXT UP", "ON_TRACK": "ON TRACK", "IN_PROGRESS": "IN PROGRESS",
    "CALENDAR": "TIMED TO RACE",
}


def _gate_visual(prog):
    """The gate-aware progress visual spec for the metric row. Self-contained: the frontend draws
    a week-track (time/consistency gate), a banded gauge (scalar metric gate), a benchmark prompt
    (stale metric), or a race note (calendar) — whichever the current block actually gates on."""
    kind = prog.get("transition_kind")
    gate = prog.get("gate") or {}
    val = gate.get("value")
    if kind == "calendar":
        return {"kind": "calendar", "next_block": prog.get("next_block")}
    if prog.get("verdict") == "NEEDS_BENCHMARK":
        return {"kind": "benchmark", "need": prog.get("this_week_test"),
                "next_block": prog.get("next_block")}
    if isinstance(val, (int, float)):
        return {"kind": "gauge", "value": val, "lo": 81, "hi": 85, "axis_min": 70, "axis_max": 100,
                "metric": gate.get("metric", "gate"), "confidence": gate.get("confidence"),
                "next_block": prog.get("next_block")}
    return {"kind": "weeks", "elapsed": prog.get("week_in_block") or 0,
            "total": prog.get("weeks_in_block") or 1, "next_block": prog.get("next_block"),
            "weeks": prog.get("block_weeks") or [],          # per-week ride-slot detail
            "min_ride_days": prog.get("min_ride_days") or 4,  # icons per week
            "ramp": prog.get("ctl_change_28d"), "ramp_ok": (prog.get("ctl_change_28d") or 0) >= 0}


# --- watchman concern line (so an alarmed/amber Wattson actually SAYS what tripped) ---
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_day(iso):
    if not iso:
        return "recently"
    d = dt.date.fromisoformat(iso[:10])
    return f"{_MON[d.month - 1]} {d.day}"


# Confirmed (red) tripwire -> imperative: name the trigger, give the move.
_ALERT_LINE = {
    "injury_spike": lambda ev, when: (
        f"Heads up — your training load spiked around {when} (ACWR {ev.get('acwr')}, acute load well "
        f"over your recent base). Ride easy the next day or two and let it settle before adding more."),
    "gap_unravel": lambda ev, when: (
        f"You've been off the bike since {when} and fitness is starting to leak. Get a steady ride "
        f"in now, before the base unravels."),
    "monotony": lambda ev, when: (
        f"Your training's gone one-note (monotony {ev.get('monotony')}). Break it up — one genuinely "
        f"easy day and one harder, not all the same."),
}
# Watch (amber) -> softer "I'm watching X" context, still concrete. (evidence, when).
_WATCH_LINE = {
    "injury_spike": lambda ev, when: (
        f"I'm watching the load spike on {when} — that effort ran your acute load to about "
        f"{ev.get('acwr')}× your recent base. Not alarming at the fitness you're carrying, but "
        f"don't stack another big day straight on top of it."),
    "gap_unravel": lambda ev, when: (
        f"I'm watching a gap in your riding around {when} — get back on this week and it's a non-issue."),
    "under_load": lambda ev, when: (
        "I'm watching your load — it's been sitting under your sustainable base; the plan pulls it back up."),
    "monotony": lambda ev, when: (
        "I'm watching your variety — the last stretch leans repetitive."),
    "overtraining": lambda ev, when: (
        "I'm watching your fatigue — form's been deep in the red while load keeps climbing."),
}
_ALERT_FALLBACK = "Heads up — something acute just tripped in your numbers. Ease off until it clears."


def _concern_line(watch):
    """One Wattson-voice line naming the active alert/watch, or None on a green board. Pure: it
    reads the already-selected watchman result, computes nothing (THE ONE RULE)."""
    if not watch:
        return None
    status = watch.get("status")
    trips = watch.get("tripwires") or []
    if status == "alert":
        firm = [t for t in trips if not t.get("provisional")]
        if firm:
            t = firm[0]                                   # already priority-sorted in select()
            f = _ALERT_LINE.get(t["mode_id"])
            if f:
                return f(t.get("evidence") or {}, _fmt_day(t.get("window_end")))
        return _ALERT_FALLBACK
    if status == "watch":
        # highest-priority active concern across provisional trips, watch-rollup, and trend zones
        cands = [(DETECTORS.priority.get(t["mode_id"], 99), t["mode_id"], t.get("window_end"),
                  t.get("evidence") or {}) for t in trips]
        cands += [(DETECTORS.priority.get(w["mode_id"], 99), w["mode_id"], w.get("latest"),
                   w.get("evidence") or {}) for w in (watch.get("watch_rollup") or [])]
        cands += [(a.get("priority", 99), a["mode_id"], a.get("zone_end"), a.get("evidence") or {})
                  for a in (watch.get("trend_annotations") or [])]
        if not cands:
            return None
        _, mode, when, ev = min(cands, key=lambda c: c[0])
        f = _WATCH_LINE.get(mode)
        return f(ev, _fmt_day(when)) if f else None
    return None


# Which modeled systems Wattson reads against each block — straight from the canonical blocks'
# target_metric (config.py): Base 3 = "mFTP & TTE", Build 1 = "VO2/Pmax & mFTP", Build 2 = "Pmax",
# Peak = season-best PD (top-end). Prep/Base 1-2 are aerobic-base (EF/frequency) — no PD focus.
# A system off the block's focus list still surfaces if it moved notably (>= _SYS_NOTABLE_PCT).
_BLOCK_SYSTEMS = {
    "Prep": (), "Base 1": (), "Base 2": (),
    "Base 3": ("mftp_w", "tte_sec"),
    "Build 1": ("pvo2max_w", "pmax_w", "mftp_w"),
    "Build 2": ("pmax_w",),
    "Peak": ("pmax_w", "pvo2max_w"),
    "Race": (),
}
_SYS_NOTABLE_PCT = 5.0       # off-focus systems are mentioned only on a move at least this big
_SYS_MAX_LINES = 2          # keep the read tight — at most this many systems per card

# Grounded clauses (lowercase; assembled into one sentence). `fix` is appended for a block-relevant
# system that's sliding — names the work that brings it back (Wattson voice: direct + actionable).
# `stale` is used INSTEAD of the direction clause when the data behind a system is old: it states the
# value, names the missing effort, and explicitly tells the athlete not to read the direction as real.
_SYS_COPY = {
    "mftp_w":   {"rising": "your threshold is climbing — mFTP up to {v} W",
                 "falling": "your threshold's eased back to {v} W",
                 "flat": "your threshold's holding at {v} W",
                 "fix": " — the duration work will lift it",
                 "stale": "your threshold reads {v} W, but I haven't seen a hard sustained effort from "
                          "you in {ago} — read that loosely, not as a real move"},
    "pvo2max_w": {"rising": "your aerobic power is responding — pVO2max at {v} W",
                  "falling": "your aerobic power's slipped to {v} W",
                  "flat": "your aerobic power's steady at {v} W",
                  "fix": " — the VO2 work needs to land",
                  "stale": "your aerobic power reads {v} W, but it's been {ago} since a real VO2 effort, "
                           "so don't read much into the number"},
    "pmax_w":   {"rising": "your top-end's sharpening — Pmax up to {v} W",
                 "falling": "your top-end's gone soft — Pmax down to {v} W",
                 "flat": "your top-end's holding at {v} W",
                 "fix": " — time for some sprints",
                 "stale": "your top-end reads {v} W, but I haven't seen a full sprint in {ago} — that's "
                          "stale data, not a real drop"},
    "tte_sec":  {"rising": "your TTE is stretching out to {v} min",
                 "falling": "your TTE's slipped to {v} min",
                 "flat": "your TTE's steady at {v} min",
                 "fix": " — get some longer threshold blocks in",
                 "stale": "your TTE reads {v} min, but it's been {ago} since a long threshold effort, so "
                          "take it with a grain of salt"},
}


def _ago(days):
    """Human gap for the staleness hedge: '5 weeks', 'a week', 'a while' (unknown)."""
    if not days:
        return "a while"
    wk = round(days / 7)
    return "a week" if wk <= 1 else f"{wk} weeks"


def _sys_clause(col, s, relevant):
    copy = _SYS_COPY[col]
    if s.get("confidence") == "stale":                    # old data → hedge, never assert a direction
        return copy["stale"].format(v=s["value"], ago=_ago(s.get("days_since")))
    c = copy[s["dir"]].format(v=s["value"])
    if relevant and s["dir"] == "falling":
        c += copy.get("fix", "")
    return c


def _join_clauses(picks, systems):
    """Assemble (col, relevant) picks into one capitalized sentence, or None if empty."""
    if not picks:
        return None
    clauses = [_sys_clause(c, systems[c], r) for c, r in picks]
    txt = clauses[0]
    for c in clauses[1:]:
        txt += ", and " + c
    return txt[0].upper() + txt[1:] + "."


def _systems_lines(block, systems):
    """Read the systems as two SEPARATE sentences, so each lands where it belongs in the narrative:
      • `relevant` — the block's focus systems (any direction). These are evidence for the gate, so
        they read alongside the plan/block paragraph.
      • `notable`  — an off-focus system that ROSE notably (a real, positive surprise). This is a
        by-the-way about current form, so it reads with the where-you-stand brief, not the plan.
    An off-focus DECLINE is the expected cost of training something else (e.g. Pmax fading in Prep),
    so it stays silent. A notable RISE on STALE data is not a real surprise (the model is just
    extrapolating), so it's suppressed too. Either sentence may be None."""
    if not systems:
        return {"relevant": None, "notable": None}
    relevant = _BLOCK_SYSTEMS.get(block, ())
    rel = sorted((c for c in relevant if c in systems),
                 key=lambda c: -abs(systems[c]["delta_pct"]))[:_SYS_MAX_LINES]
    notable = sorted((c for c, s in systems.items()
                      if c not in relevant and s["dir"] == "rising"
                      and s["delta_pct"] >= _SYS_NOTABLE_PCT and s.get("confidence") != "stale"),
                     key=lambda c: -systems[c]["delta_pct"])[:1]   # one aside, kept tight
    return {"relevant": _join_clauses([(c, True) for c in rel], systems),
            "notable": _join_clauses([(c, False) for c in notable], systems)}


def relevant_systems(block):
    """The modeled systems that matter for `block` (its focus). Exposed so the app layer can decide
    which aging systems are worth prescribing a refresh effort for, without duplicating the map."""
    return _BLOCK_SYSTEMS.get(block, ())


def _refresh_copy(t, ago):
    """The prescription sentence. A `peak` (all-out) effort has no target to hit — just beat the PB. A
    `model` stretch is a forward target range ('the top end's in you'). No stretch → 'confirm it'."""
    if t.get("stretch_kind") == "peak":                   # sprints are all-out — no watt target, beat the PB
        pb = f" — your PB is {t['stretch_w']} W, go beat it." if t.get("stretch_w") else " and let's see where it's at."
        return (f"I haven't seen a max {t['effort']} from you in {ago}. Tack a few all-out efforts onto "
                f"the end of a ride this week{pb}")
    lead = f"I haven't seen a solid {t['effort']} from you in {ago}. Give me a {t['label']} this week"
    if t.get("stretch_w") and t.get("stretch_kind") == "model":
        return f"{lead} — aim between {t['floor_w']} and {t['stretch_w']} W. I think the top end's in you."
    return f"{lead} — you've held {t['floor_w']} W there before, let's confirm it."


def refresh_prescription(systems, targets):
    """The 'go test this' prescription for the block-relevant system that's gone quiet, as a structured
    dict (system/effort/label/floor_w/stretch_w/stretch_kind/days_since/weeks/sentence) or None.
    `targets` is already limited by the caller to block-relevant systems; we prompt the most-overdue
    aging/stale one. Single source for the check-in + the calendar's this-week focus."""
    due = [(c, t) for c, t in (targets or {}).items()
           if systems.get(c, {}).get("confidence") in ("aging", "stale")]
    if not due:
        return None
    col, t = max(due, key=lambda ct: systems[ct[0]].get("days_since") or 0)
    ds = systems[col].get("days_since")
    return {"system": col, "effort": t["effort"], "label": t["label"], "floor_w": t["floor_w"],
            "stretch_w": t.get("stretch_w"), "stretch_kind": t.get("stretch_kind"),
            "days_since": ds, "weeks": (round(ds / 7) if ds else None),
            "sentence": _refresh_copy(t, _ago(ds))}


def _refresh_sentence(systems, targets):
    p = refresh_prescription(systems, targets)
    return p["sentence"] if p else None


def coach_card(hero, prog, watch=None, systems=None):
    """Compose the merged dashboard card: Wattson's deterministic narrative (the active concern +
    the hero read + this week's directive + the phase gate, folded into one voice), the glanceable
    vitals, and a gate-aware progress-visual spec. Pure — it arranges grounded numbers/strings,
    invents nothing (THE ONE RULE), so the UI never has to synthesize coaching copy. `watch` is the
    Slice-2 selection so the narrative can lead with whatever tripped the board."""
    if not hero:
        return {"narrative": ["Load some training data and I'll read where you stand."],
                "vitals": None, "gate_visual": {"kind": "none"}, "mood": "calm",
                "status": "awaiting", "verdict": None}
    d = hero.get("directive") or {}
    concern = _concern_line(watch)
    block = prog["block"] if (prog and prog.get("state") == "ok") else None
    sys_lines = _systems_lines(block, systems)
    # The where-you-stand read: concern + fitness/form headline + any off-focus system that's risen
    # (a form by-the-way belongs here, with current state — not wedged into the plan).
    n = ([concern] if concern else []) + [hero["headline"]]
    if sys_lines["notable"]:
        n.append(sys_lines["notable"])
    now_count = len(n)            # paragraph 1 = the concern + the current-state read; plan follows
    ok = bool(prog and prog.get("state") == "ok")

    if ok:
        nb = prog.get("next_block") or "the next block"
        focus = prog.get("focus")
        watching = prog.get("watching")
        w, wk = prog.get("week_in_block"), prog.get("weeks_in_block")
        kind = prog.get("transition_kind")
        gate = prog.get("gate") or {}
        verdict = prog["verdict"]
        val = gate.get("value")

        if prog.get("started"):
            n.append(f"This is week {w} of {wk} in {block}"
                     + (f", and the focus is {focus}." if focus else "."))
        else:
            n.append(f"{block} is next up" + (f" — the focus is {focus}." if focus else "."))

        if sys_lines["relevant"]:                         # block-focus systems = evidence for the gate
            n.append(sys_lines["relevant"])

        if d.get("tss"):
            n.append(f"{d['pre']}{d['tss']} TSS{d['post']}")
        elif d.get("pre"):
            n.append(d["pre"])

        if kind == "calendar":
            n.append("Peak and taper are timed back from your race, not a metric — we just need "
                     "your form rising and the top-end sharp on the day.")
        elif verdict == "NEEDS_BENCHMARK":
            n.append(f"I can't read {gate.get('name', 'this')} cleanly yet — {prog.get('this_week_test')}.")
        elif isinstance(val, (int, float)):
            band = gate.get("target", "the ready band")
            if verdict == "ADVANCE":
                n.append(f"Your {gate.get('metric', 'gate')} is at {val}% — into the {band} zone. "
                         f"Hold it flat a couple of weeks and we move to {nb}.")
            else:
                n.append(f"Your {gate.get('metric', 'gate')} is at {val}% — I want it in the {band} "
                         f"zone before we add intensity. Keep doing the extensive work and it climbs.")
        else:                                             # time / consistency gate (Prep, sub-steps)
            mrd = gate.get("min_ride_days") or prog.get("min_ride_days") or 4
            lead = f"I'm watching your {watching} — keep it pointed up. " if watching else ""
            n.append(f"{lead}String together {wk} steady weeks — ride at least {mrd} days a week "
                     "(no hero days; just show up).")
            if not prog.get("min_weeks_met"):
                n.append(f"We don't jump to {nb} before week {prog.get('min_weeks')}; the base "
                         "needs the weeks to stick.")

        br = prog.get("branches") or []
        if br and verdict != "NEEDS_BENCHMARK":
            cost = br[0].get("calendar_cost", "no")
            n.append(f"If {br[0]['outcome']}, {br[0]['action']}"
                     + (f" — costs you {cost}." if cost and cost != "none" else " — at no cost."))
        if gate.get("confidence") == "fresh":
            n.append("Your numbers are fresh, so I can read all of this clean.")
        gate_visual = _gate_visual(prog)
        verdict_out = verdict
    else:
        n.append("No season plan loaded yet — set one up and I'll start gating your phases and "
                 "calling the moves.")
        gate_visual = {"kind": "none"}
        verdict_out = None

    # Paragraph groups: the now-read (concern + where you stand) vs the plan (block/directive/gate).
    # The polish layer turns each group into one tight paragraph; the UI renders them separately.
    paragraphs = [" ".join(n[:now_count])]
    if len(n) > now_count:
        paragraphs.append(" ".join(n[now_count:]))

    return {
        "mood": hero["mood"], "status": hero["status"],
        "block": prog.get("block") if ok else None,
        "next_block": prog.get("next_block") if ok else None,
        "verdict": verdict_out, "verdict_label": _VERDICT_LABEL.get(verdict_out),
        "week_in_block": prog.get("week_in_block") if ok else None,
        "weeks_in_block": prog.get("weeks_in_block") if ok else None,
        "narrative": n,
        "narrative_paragraphs": paragraphs,
        "vitals": hero["vitals"],
        "this_week_tss": d.get("tss"),
        "gate_visual": gate_visual,
    }
