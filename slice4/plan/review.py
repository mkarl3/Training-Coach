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
