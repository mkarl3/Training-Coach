"""Plan-skeleton generator tests — the structure is deterministic, traceable, and
constrained by the athlete's failure modes. (Tuned to one athlete; structure not numbers
is what's asserted.)"""
import dataclasses
import datetime as dt

import pytest

from wko_metrics import DEFAULT_PROFILE
from plan import generator
from plan.config import DEFAULT_CALENDAR


def season_at(as_of, weeks_out=15, hours=7.0, etype="gran_fondo"):
    a = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=weeks_out)).isoformat()
    return ({"start_date": as_of, "weekly_hours_budget": hours},
            [{"name": "A", "event_date": a, "priority": "A", "event_type": etype}])


def test_deterministic(m, as_of):
    season, events = season_at(as_of)
    p1 = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    p2 = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    assert p1 == p2                                   # same inputs -> same plan, exactly


def test_phases_run_backward_and_end_at_race_week(m, as_of):
    season, events = season_at(as_of, weeks_out=16)
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    phases = [w["family"] for w in plan["weeks"]]
    # order base -> build -> peak -> taper, contiguous
    order = {"base": 0, "build": 1, "peak": 2, "taper": 3}
    ranks = [order[p] for p in phases]
    assert ranks == sorted(ranks)
    assert phases[-1] == "taper"                      # the plan ends tapering into the race
    # last week contains the A-race date
    a_date = dt.date.fromisoformat(events[0]["event_date"])
    last = plan["weeks"][-1]
    assert last["week_start"] <= a_date.isoformat() <= last["week_end"]


def test_every_week_is_traceable(m, as_of):
    season, events = season_at(as_of)
    for w in generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)["weeks"]:
        assert w["rationale"]                          # a rule set every week
        assert abs(w["ctl_target"] - (w["ctl_start"] + w["planned_ramp"])) < 0.11  # tie out (to rounding)
        assert w["weekly_tss_target"] >= 0
        assert isinstance(w["constraints_fired"], list)


def test_ramp_cap_is_derived_and_never_exceeded(m, as_of):
    # The ramp ceiling is DERIVED from the athlete's demonstrated ramp (headroom above it), not
    # the profile's 7.0 default; no build week may exceed it.
    season, events = season_at(as_of, hours=20.0)      # remove the time budget as the binder
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    cap = plan["meta"]["ramp_cap"]
    assert cap == round(1.5 * plan["meta"]["sustainable_ramp"], 1)   # derived, not 7.0
    assert cap < DEFAULT_PROFILE.ramp_rate_cap                       # well under the stale default
    builds = [w for w in plan["weeks"] if w["family"] in ("base", "build") and not w["is_recovery"]]
    assert builds and all(w["planned_ramp"] <= cap + 1e-9 for w in builds)


def test_masters_get_more_frequent_shallower_recovery(m, as_of):
    season, events = season_at(as_of, weeks_out=16, hours=20.0)
    open_p = dataclasses.replace(DEFAULT_PROFILE, birth_year=2000)   # ~26, open
    mast_p = dataclasses.replace(DEFAULT_PROFILE, birth_year=1980)   # ~46, masters
    o = generator.generate_plan(m, open_p, season, events, [], as_of)
    ms = generator.generate_plan(m, mast_p, season, events, [], as_of)
    assert ms["meta"]["masters"] and not o["meta"]["masters"]
    rec_o = sum(w["is_recovery"] for w in o["weeks"])
    rec_m = sum(w["is_recovery"] for w in ms["weeks"])
    assert rec_m >= rec_o                              # masters recover more often
    # masters troughs are shallower (smaller CTL dip)
    dip_o = min((w["planned_ramp"] for w in o["weeks"] if w["is_recovery"]), default=0)
    dip_m = min((w["planned_ramp"] for w in ms["weeks"] if w["is_recovery"]), default=0)
    assert dip_m > dip_o                               # -1.2 (masters) > -2.0 (open)


def test_time_budget_binds_the_ramp(m, as_of):
    season_tight, events = season_at(as_of, hours=4.0)
    season_loose, _ = season_at(as_of, hours=20.0)
    tight = generator.generate_plan(m, DEFAULT_PROFILE, season_tight, events, [], as_of)
    loose = generator.generate_plan(m, DEFAULT_PROFILE, season_loose, events, [], as_of)
    assert tight["meta"]["peak_ctl_achieved"] < loose["meta"]["peak_ctl_achieved"]
    assert any("time budget" in c for w in tight["weeks"] for c in w["constraints_fired"])


def test_unavailable_week_forced_to_recovery(m, as_of):
    season, events = season_at(as_of)
    ua_start = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=3)).isoformat()
    ua_end = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=3, days=6)).isoformat()
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events,
                                   [{"start_date": ua_start, "end_date": ua_end, "reason": "trip"}], as_of)
    hit = [w for w in plan["weeks"] if any("unavailable" in c for c in w["constraints_fired"])]
    assert hit and all(w["is_recovery"] and w["planned_ramp"] <= 0 for w in hit)


def test_durability_event_prioritizes_long_rides(m, as_of):
    season, gf = season_at(as_of, etype="gran_fondo")     # durability
    _, tt = season_at(as_of, etype="time_trial")          # not durability
    gf_plan = generator.generate_plan(m, DEFAULT_PROFILE, season, gf, [], as_of)
    tt_plan = generator.generate_plan(m, DEFAULT_PROFILE, season, tt, [], as_of)
    assert any(w["long_ride_hours"] for w in gf_plan["weeks"])
    assert not any(w["long_ride_hours"] for w in tt_plan["weeks"])


def test_no_event_returns_error(m, as_of):
    season, _ = season_at(as_of)
    assert "error" in generator.generate_plan(m, DEFAULT_PROFILE, season, [], [], as_of)


def _bound_week(plan):
    """An upcoming week whose load is actually pinned by the time budget (so relaxing hours
    can move it). For a low-CTL athlete this is a tighter-budget mid-plan week, not week 1."""
    return next(w for w in plan["weeks"]
                if w["status"] == "upcoming"
                and any("time budget" in c for c in w["constraints_fired"]))


def test_availability_up_relaxes_budget_but_guardrails_still_bind(m, as_of):
    # A 20h opportunity on an otherwise budget-bound week lets the ramp rise — but only to the
    # ramp/target ceiling, NOT proportional to the extra hours.
    season, events = season_at(as_of, weeks_out=16, hours=4.0)
    base = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    wb = _bound_week(base)
    av = [{"start_date": wb["week_start"], "end_date": wb["week_end"], "hours": 20.0, "reason": "family away"}]
    up = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of, availability=av)
    ub = [w for w in up["weeks"] if w["week_start"] == wb["week_start"]][0]
    assert ub["weekly_tss_target"] > wb["weekly_tss_target"]          # opportunity used
    assert ub["planned_ramp"] <= DEFAULT_PROFILE.ramp_rate_cap + 1e-9  # but capped by the guardrail
    assert any("availability override" in c for c in ub["constraints_fired"])


def test_availability_down_tightens(m, as_of):
    season, events = season_at(as_of, weeks_out=16, hours=12.0)
    base = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    w2 = base["weeks"][1]
    av = [{"start_date": w2["week_start"], "end_date": w2["week_end"], "hours": 3.0, "reason": "busy"}]
    down = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of, availability=av)
    assert down["weeks"][1]["weekly_tss_target"] < w2["weekly_tss_target"]


def test_intensity_cap_holds_easy_and_aerobic(m, as_of):
    season, events = season_at(as_of, weeks_out=16, hours=12.0)
    w = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)["weeks"][2]
    cap = [{"start_date": w["week_start"], "end_date": w["week_end"], "reason": "knee"}]
    capped = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of,
                                     intensity_caps=cap)["weeks"][2]
    assert capped["intensity_capped"] and capped["planned_ramp"] <= 0          # tightened: hold/ease
    assert capped["prescribed_distribution"] == "aerobic only — intensity capped"
    assert not capped["field_test"]                                            # don't test while easy
    assert any("intensity cap" in c for c in capped["constraints_fired"])


def test_diff_reports_changed_weeks_and_headline(m, as_of):
    season, events = season_at(as_of, weeks_out=16, hours=4.0)
    old = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    wb = _bound_week(old)
    av = [{"start_date": wb["week_start"], "end_date": wb["week_end"], "hours": 20.0, "reason": "free"}]
    new = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of, availability=av)
    d = generator.diff_plans(old, new)
    assert d["n_changed"] >= 1
    hit = [c for c in d["weeks_changed"] if c["week_start"] == wb["week_start"]][0]
    assert "weekly_tss_target" in hit["deltas"]
    assert set(d["summary"]) == {"weeks", "peak_ctl_achieved", "target_peak_ctl", "target_reached"}


def test_unchanged_inputs_yield_empty_diff(m, as_of):
    season, events = season_at(as_of, weeks_out=16)
    p = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    assert generator.diff_plans(p, p)["n_changed"] == 0


def test_blocks_follow_the_matrix_and_are_base_heavy(m, as_of):
    season, events = season_at(as_of, weeks_out=20)
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    fam = plan["meta"]["family_weeks"]
    assert fam["base"] >= fam["build"]                 # matrix is base-heavy
    assert fam["taper"] == 1 and fam["peak"] >= 1       # always ends peak -> race/taper
    blocks = [w["block"] for w in plan["weeks"]]
    assert blocks[0] == "Prep" and blocks[-1] == "Race"
    # field test marks the last week of each non-taper block, never the taper
    assert any(w["field_test"] for w in plan["weeks"])
    assert not any(w["field_test"] and w["family"] == "taper" for w in plan["weeks"])


def test_week_starts_on_drives_alignment(m, as_of):
    season, events = season_at(as_of)
    mon_p = dataclasses.replace(DEFAULT_PROFILE, week_starts_on="monday")
    sun_p = dataclasses.replace(DEFAULT_PROFILE, week_starts_on="sunday")
    mon = generator.generate_plan(m, mon_p, season, events, [], as_of)
    sun = generator.generate_plan(m, sun_p, season, events, [], as_of)
    assert dt.date.fromisoformat(mon["weeks"][0]["week_start"]).weekday() == 0   # Monday
    assert dt.date.fromisoformat(sun["weeks"][0]["week_start"]).weekday() == 6   # Sunday


def test_single_ride_cap_is_half_the_6wk_rolling_avg(m, as_of):
    # 50% rule = half the 6-WEEK ROLLING AVERAGE weekly TSS, not half this one planned week.
    weeks = generator.generate_plan(m, DEFAULT_PROFILE, season_at(as_of, weeks_out=20)[0],
                                    season_at(as_of, weeks_out=20)[1], [], as_of)["weeks"]
    i = 8                                              # deep enough that the trailing 6 are all plan weeks
    trailing6 = [w["weekly_tss_target"] for w in weeks[i - 5:i + 1]]
    assert weeks[i]["single_ride_tss_cap"] == round(0.5 * (sum(trailing6) / len(trailing6)))


def test_acute_load_cap_ramps_in_from_recent_baseline(m, as_of):
    # Week 1 must not jump to the full CTL-maintenance+ramp target; it's capped to a demonstrated-
    # safe step over recent actual load. (Loose hours so the ACUTE cap, not the budget, binds.)
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season_at(as_of, weeks_out=20, hours=20.0)[0],
                                   season_at(as_of, weeks_out=20, hours=20.0)[1], [], as_of)
    M = plan["meta"]
    assert M["sustainable_ramp"] is not None and M["safe_acute_ratio"] >= 1.0 and M["recent_weekly_tss"]
    w1 = plan["weeks"][0]
    ctl_target_tss = 7 * w1["ctl_start"] + 45.5 * M["base_ramp"]      # the un-capped CTL target
    assert w1["weekly_tss_target"] < ctl_target_tss                  # it was held below the raw target
    assert w1["weekly_tss_target"] <= round(M["safe_acute_ratio"] * M["recent_weekly_tss"]) + 1
    assert any("acute-load cap" in c for c in w1["constraints_fired"])


def test_ramp_seeds_from_demonstrated_sustainable_ramp(m, as_of):
    season, events = season_at(as_of, weeks_out=16)
    M = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)["meta"]
    assert M["ramp_source"] == "history"                 # this athlete has enough history
    assert M["sustainable_ramp"] == M["base_ramp"]        # base target IS the demonstrated ramp
    assert M["base_ramp"] >= M["build_ramp"]              # periodization shape preserved
    assert M["base_ramp"] <= DEFAULT_PROFILE.ramp_rate_cap


def test_ramp_falls_back_to_default_when_history_thin(m, as_of):
    import unittest.mock as mock
    season, events = season_at(as_of, weeks_out=16)
    with mock.patch.object(type(m), "personal_sustainable_ramp", return_value=None):
        M = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)["meta"]
    assert M["ramp_source"] == "default" and M["sustainable_ramp"] is None
    assert M["base_ramp"] == DEFAULT_CALENDAR.ramp_base    # generic method default
    assert M["build_ramp"] == DEFAULT_CALENDAR.ramp_build


def test_monotony_guardrail_gates_on_the_fingerprint(m, as_of):
    # The hard/easy-separation prescription tightens ONLY when this athlete's gray-zone
    # tendency crosses the profile thresholds — not as a blanket rule.
    season, events = season_at(as_of, weeks_out=16)
    prone = dataclasses.replace(DEFAULT_PROFILE, monotony_band_frac=0.0, tiz_concentration_watch=0.0)
    clean = dataclasses.replace(DEFAULT_PROFILE, monotony_band_frac=1.1, tiz_concentration_watch=2.0)
    p = generator.generate_plan(m, prone, season, events, [], as_of)
    c = generator.generate_plan(m, clean, season, events, [], as_of)
    assert p["meta"]["monotony_guard"]["prone"] and not c["meta"]["monotony_guard"]["prone"]
    assert "STRICT polarized" in p["meta"]["distribution_rx"]
    assert "STRICT polarized" not in c["meta"]["distribution_rx"]
    # fires on training weeks, never on recovery or taper
    fired = [w for w in p["weeks"] if any("monotony guardrail" in x for x in w["constraints_fired"])]
    assert fired and all(not w["is_recovery"] and w["family"] != "taper" for w in fired)
    assert not any("monotony guardrail" in x for w in c["weeks"] for x in w["constraints_fired"])


def test_elapsed_weeks_carry_actuals(m, as_of):
    # season starting before the data date -> early weeks are elapsed and show real TSS/CTL.
    start = (dt.date.fromisoformat(as_of) - dt.timedelta(weeks=8)).isoformat()
    a = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=8)).isoformat()
    season = {"start_date": start, "weekly_hours_budget": 7.0}
    events = [{"name": "A", "event_date": a, "priority": "A", "event_type": "gran_fondo"}]
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    statuses = {w["status"] for w in plan["weeks"]}
    assert "elapsed" in statuses and "upcoming" in statuses
    elapsed = [w for w in plan["weeks"] if w["status"] == "elapsed"]
    assert elapsed and all(w["actual_tss"] is not None for w in elapsed)
    assert all(w["actual_tss"] is None for w in plan["weeks"] if w["status"] == "upcoming")
