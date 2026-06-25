"""Slice 5 — phase-progression autoregulation (assessment engine, pure/deterministic).

Operationalizes the `advance_when` intent per training block: at a block boundary, has the phase
done its job? Emits a VERDICT + the contingency BRANCH so Wattson can narrate ahead of the week.
THE ONE RULE: this computes the gate; Wattson narrates; the athlete confirms; the generator
recomputes. See slice5_spec.md. Nothing here changes a plan number.

Validated against the WKO5/CTS knowledgebase. Every non-sourced threshold is marked TUNABLE.
"""
import datetime as dt

from wko_metrics.consistency import consecutive_miss_weeks, CONSISTENCY_CLEAN_MIN_RIDE_DAYS

# --- TUNABLE v1 defaults (NOT sourced — see slice5_spec.md §9) ---
FU_READY_PCT = 81.0          # SOURCED: fractional-utilization 81-85% band is the base->build gate
FU_STAY_PCT = 80.0           # SOURCED-ish: below ~80-81% keep doing extensive base
STALE_DAYS = 42              # TUNABLE: a band older than this is "stale" (re-feed cadence ~8wk)
AGING_DAYS = 14              # TUNABLE
COMPLIANCE_OK = 0.80         # TUNABLE: hit >=80% of planned TSS = "consistent"
BASE_MIN_WEEKS = 4           # adaptation-rate floor (SOURCED ranges); guards canonical nominal
BUILD_MIN_WEEKS = 3

_FAM_ORDER = ("base", "build", "peak", "taper")


def _blocks_in_order(weeks):
    """Distinct blocks in plan order with their family + week list."""
    out = []
    for w in weeks:
        if out and out[-1]["block"] == w["block"]:
            out[-1]["weeks"].append(w)
        else:
            out.append({"block": w["block"], "family": w["family"], "weeks": [w]})
    return out


def _current_idx(blocks):
    for i, b in enumerate(blocks):
        if any(w["status"] == "current" for w in b["weeks"]):
            return i, False
    for i, b in enumerate(blocks):
        if any(w["status"] == "upcoming" for w in b["weeks"]):
            return i, True                      # plan not started / future → first upcoming
    return 0, True


def _kind(block, fam, next_fam, next_block):
    if block == "Prep":
        return "prep_to_base"
    if fam in ("peak", "taper") or (next_block and next_block.lower().startswith("race")):
        return "calendar"
    if fam == "base" and next_fam == "build":
        return "base_to_build"
    if fam == "build" and next_fam in ("peak", "taper"):
        return "build_to_peak"
    return "substep"


def _compliance(weeks):
    rs = [w["actual_tss"] / w["weekly_tss_target"]
          for w in weeks if w.get("actual_tss") is not None and w.get("weekly_tss_target")]
    return round(sum(rs) / len(rs), 2) if rs else None


def _conf(days):
    if days is None:
        return "none"
    return "fresh" if days <= AGING_DAYS else "aging" if days <= STALE_DAYS else "stale"


def assess_progression(m, plan, as_of, profile=None):
    """Return the deterministic phase-progression assessment for `as_of`."""
    if not plan or not plan.get("weeks"):
        return {"state": "no_plan"}
    as_of = str(as_of)
    blocks = _blocks_in_order(plan["weeks"])
    i, future = _current_idx(blocks)
    cur = blocks[i]
    nxt = blocks[i + 1] if i + 1 < len(blocks) else None
    block, fam = cur["block"], cur["family"]
    next_block = nxt["block"] if nxt else None
    next_fam = nxt["family"] if nxt else None
    kind = _kind(block, fam, next_fam, next_block)

    nominal = len(cur["weeks"])
    floor = max(nominal, BASE_MIN_WEEKS if fam == "base" else BUILD_MIN_WEEKS if fam == "build" else 1)
    elapsed = sum(1 for w in cur["weeks"] if w["status"] in ("elapsed", "current"))
    min_met = elapsed >= min(nominal, floor)
    # block-onboarding context (straight from the plan — focus / what the block is building /
    # the trigger to move on): lets Wattson say "week N of Prep, here's the focus, here's what
    # I'm watching" instead of a bare verdict.
    cur_week = next((w for w in cur["weeks"] if w["status"] == "current"), cur["weeks"][0])
    week_in_block = max(1, elapsed)                  # "week 1 of N" once a block is live
    compliance = _compliance([w for b in blocks[:i + 1] for w in b["weeks"]])
    chg = m.ctl_change(as_of)                       # building?
    stale = m.band_staleness(as_of)

    # per-week ride-day detail for the current block (drives the gate visual's ride slots). Counted
    # from actual rides; a week is "complete" at CONSISTENCY_CLEAN_MIN_RIDE_DAYS ride days. Guarded
    # for date-less stub plans (unit tests) → empty.
    block_weeks = []
    if all(w.get("week_start") and w.get("week_end") for w in cur["weeks"]):
        for w in cur["weeks"]:
            rd = int(m.has_ride[(m.has_ride.index >= w["week_start"])
                                & (m.has_ride.index <= w["week_end"])].sum())
            st = "done" if w["status"] == "elapsed" else "now" if w["status"] == "current" else "future"
            block_weeks.append({"week": w["week"], "ride_days": rd, "status": st,
                                "complete": rd >= CONSISTENCY_CLEAN_MIN_RIDE_DAYS})

    gate, verdict, test, branches = _gate(m, as_of, kind, block, next_block, stale, chg, compliance)

    # never advance early when peak-anchored: a READY gate before min_weeks holds the schedule
    if verdict == "ADVANCE" and not min_met:
        verdict = "ON_TRACK"
    if future and verdict not in ("NEEDS_BENCHMARK",):
        verdict = "NOT_STARTED" if elapsed == 0 else verdict

    return {
        "state": "ok", "as_of": as_of, "block": block, "next_block": next_block,
        "transition_kind": kind, "family": fam,
        "weeks_in_block": nominal, "min_weeks": min(nominal, floor),
        "weeks_elapsed": elapsed, "week_in_block": week_in_block, "min_weeks_met": min_met,
        "started": not future, "focus": cur_week.get("focus"),
        "watching": cur_week.get("target_metric"), "advance_when": cur_week.get("advance_when"),
        "field_test_week": bool(cur_week.get("field_test")),
        "block_weeks": block_weeks, "min_ride_days": CONSISTENCY_CLEAN_MIN_RIDE_DAYS,
        "compliance": compliance, "ctl_change_28d": chg,
        "gate": gate, "verdict": verdict, "this_week_test": test, "branches": branches,
        "headline": _headline(verdict, block, next_block, gate, week_in_block, nominal, future),
    }


def _gate(m, as_of, kind, block, next_block, stale, chg, compliance):
    """Per-transition gate → (gate dict, verdict, this_week_test, branches)."""
    if kind == "calendar":
        g = {"name": "taper (calendar)", "metric": "race date",
             "note": "Peak/taper is timed backward from the race — not a metric gate. Metrics only "
                     "confirm form is rising and top-end is present."}
        return g, "CALENDAR", "arrive fresh on race day", []

    if kind == "base_to_build":
        fu = m.fractional_utilization(as_of)
        days = stale.get("vo2")
        conf = _conf(days)
        g = {"name": "fractional utilization", "metric": "mFTP / 5-min power",
             "target": f"{FU_READY_PCT:.0f}-85%", "value": (fu or {}).get("pct"),
             "detail": fu, "confidence": conf, "stale_days": days}
        if fu is None or conf == "stale":
            return g, "NEEDS_BENCHMARK", "a fresh 5-min max effort (your VO2 anchor is stale)", [
                {"outcome": "benchmark done & % in 81-85% flat", "action": "advance to Build",
                 "calendar_cost": "none"},
                {"outcome": "benchmark shows % < 80%", "action": "stay in base",
                 "calendar_cost": "eats build buffer / lowers peak"}]
        if fu["pct"] < FU_STAY_PCT:
            return g, "HOLD", "keep building FTP under your aerobic ceiling", [
                {"outcome": "% climbs into 81-85%", "action": "advance to Build", "calendar_cost": "none"},
                {"outcome": "% stalls low", "action": "extend base", "calendar_cost": "eats build buffer"}]
        # 80-85%+: ready-ish, pending plateau confirmation (needs the time series; v1 = confirm at gate)
        return g, "ADVANCE", "confirm the % has been flat ~2-3 wks, then advance", [
            {"outcome": "flat 2-3 wks in band", "action": "advance to Build", "calendar_cost": "none"},
            {"outcome": "still climbing", "action": "hold — you're still responding", "calendar_cost": "minor"}]

    if kind == "prep_to_base":
        # Prep is about ESTABLISHING THE RHYTHM — consistency = ride FREQUENCY (show up N days/wk),
        # NOT TSS-compliance (which one hero day can fake — "no hero days"). Plan-independent, so it
        # reads from week 1 with no plan-adherence data. Same definition as the Consistency Gauge.
        miss = consecutive_miss_weeks(m.has_ride, as_of, CONSISTENCY_CLEAN_MIN_RIDE_DAYS)
        consistent = miss == 0
        building = (chg or 0) > 0
        g = {"name": "consistency", "metric": f"ride {CONSISTENCY_CLEAN_MIN_RIDE_DAYS}+ days/wk",
             "min_ride_days": CONSISTENCY_CLEAN_MIN_RIDE_DAYS, "recent_miss_weeks": miss,
             "consistent": consistent, "ctl_change_28d": chg}
        if not consistent:
            return g, "HOLD", "show up and string together steady weeks before adding base volume", [
                {"outcome": f"you ride {CONSISTENCY_CLEAN_MIN_RIDE_DAYS}+ days/wk consistently",
                 "action": "advance to Base", "calendar_cost": "none"},
                {"outcome": "weeks stay spotty", "action": "hold Prep", "calendar_cost": "delays base"}]
        if building:
            return g, "ADVANCE", "the rhythm's there and fitness is turning up", [
                {"outcome": "rhythm holds", "action": "advance to Base", "calendar_cost": "none"}]
        return g, "ON_TRACK", "keep showing up — fitness follows the rhythm", []

    if kind == "build_to_peak":
        days = stale.get("medium")
        g = {"name": "anaerobic impulse spent", "metric": "anaerobic TIS impulse + fatigue",
             "confidence": _conf(days), "stale_days": days,
             "note": "FRC deliberately not gated (FTP<->FRC model artifact); read fatigue + falling "
                     "impulse."}
        if _conf(days) == "stale":
            return g, "NEEDS_BENCHMARK", "a fresh ~1-min max so I can read your anaerobic state", []
        return g, "IN_PROGRESS", "produce quality top-end; we peak when it stops climbing + you're cooked", []

    # substep — soft progress, no strong advise
    g = {"name": "absorption", "metric": "load held + not over-fatigued", "ctl_change_28d": chg}
    return g, "ON_TRACK", "absorb the load; we step up on schedule", []


def _headline(verdict, block, next_block, gate, week_in_block=1, weeks_in_block=1, future=False):
    nb = next_block or "the next block"
    wk = f"Week {week_in_block} of {weeks_in_block} in {block}"
    kick = wk + (" — let's get it rolling." if week_in_block <= 1 else " — keep stacking the work.")
    return {
        "ADVANCE": f"{block} has done its job — ready to move to {nb}.",
        "HOLD": f"Hold in {block} — the gate ({gate.get('name')}) isn't met yet.",
        "PROCEED_WITH_DEBT": f"Not fully ready, but the race clock says move to {nb}.",
        "NEEDS_BENCHMARK": f"Can't judge {block} yet — {gate.get('name')} needs a fresh effort.",
        "BACK_OFF": "Signs of over-reaching — back off before advancing.",
        "ON_TRACK": kick if not future else f"{block} is next up — here's what it's about.",
        "NOT_STARTED": f"{block} is next up — here's what it's about.",
        "CALENDAR": "Taper is timed to your race, not a metric.",
        "IN_PROGRESS": kick,
    }.get(verdict, f"{block}: {verdict}")
