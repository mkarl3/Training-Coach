"""Slice 5 phase-progression verdict logic (pure). A stubbed Metrics returns controlled
fractional-utilization / staleness / CTL-change so each gate branch is exercised deterministically.
The engine ADVISES only — it never recomputes a plan number."""
from plan import progression as prog


class FakeM:
    def __init__(self, fu=None, stale=None, chg=0.0):
        self._fu, self._stale, self._chg = fu, stale or {}, chg

    def fractional_utilization(self, as_of=None, **k):
        return self._fu

    def band_staleness(self, as_of=None, **k):
        return self._stale

    def ctl_change(self, as_of=None, **k):
        return self._chg


def wk(week, block, fam, status="upcoming", tss=200, actual=None):
    return {"week": week, "block": block, "family": fam, "status": status,
            "weekly_tss_target": tss, "actual_tss": actual}


def plan(weeks):
    return {"weeks": weeks, "meta": {}}


AO = "2026-06-14"
FU_READY = {"pct": 83.0, "mftp": 200, "vo2_power": 241, "vo2_date": "2026-06-01"}
FU_LOW = {"pct": 79.0, "mftp": 174, "vo2_power": 220, "vo2_date": "2026-06-01"}


def test_no_plan():
    assert prog.assess_progression(FakeM(), None, AO) == {"state": "no_plan"}


def test_future_plan_reads_not_started():
    p = plan([wk(1, "Prep", "base"), wk(2, "Prep", "base"), wk(3, "Prep", "base"), wk(4, "Base 1", "base")])
    r = prog.assess_progression(FakeM(chg=1.0), p, AO)
    assert r["transition_kind"] == "prep_to_base" and r["verdict"] == "NOT_STARTED"
    assert r["weeks_elapsed"] == 0


def _base3_to_build(fu, stale, cur_weeks=2):
    # Base 3 (2 wk, both current/elapsed so min met), then Build 1
    weeks = [wk(1, "Base 2", "base", "elapsed", actual=190)]
    for j in range(cur_weeks):
        weeks.append(wk(2 + j, "Base 3", "base", "current", actual=195))
    weeks.append(wk(2 + cur_weeks, "Build 1", "build"))
    return plan(weeks), FakeM(fu=fu, stale=stale)


def test_base_to_build_holds_below_80():
    p, m = _base3_to_build(FU_LOW, {"vo2": 8})
    r = prog.assess_progression(m, p, AO)
    assert r["transition_kind"] == "base_to_build" and r["verdict"] == "HOLD"
    assert r["gate"]["value"] == 79.0 and r["gate"]["confidence"] == "fresh"


def test_base_to_build_advances_in_band_when_min_met():
    p, m = _base3_to_build(FU_READY, {"vo2": 5})
    r = prog.assess_progression(m, p, AO)
    assert r["min_weeks_met"] and r["verdict"] == "ADVANCE" and r["this_week_test"]
    assert r["branches"] and r["branches"][0]["calendar_cost"] == "none"


def test_base_to_build_needs_benchmark_when_vo2_stale():
    p, m = _base3_to_build(FU_READY, {"vo2": 80})       # > STALE_DAYS
    r = prog.assess_progression(m, p, AO)
    assert r["verdict"] == "NEEDS_BENCHMARK"


def test_never_advance_early_when_min_not_met():
    # Base 3 nominal 4 wks (floor) but only 1 current -> min not met; ready gate must NOT advance
    weeks = [wk(1, "Base 3", "base", "current", actual=195)] + \
            [wk(j, "Base 3", "base") for j in range(2, 5)] + [wk(5, "Build 1", "build")]
    r = prog.assess_progression(FakeM(fu=FU_READY, stale={"vo2": 5}), plan(weeks), AO)
    assert not r["min_weeks_met"] and r["verdict"] == "ON_TRACK"        # held, not advanced


def test_peak_is_calendar_not_metric():
    weeks = [wk(1, "Peak", "peak", "current"), wk(2, "Race", "taper")]
    r = prog.assess_progression(FakeM(), plan(weeks), AO)
    assert r["transition_kind"] == "calendar" and r["verdict"] == "CALENDAR" and r["branches"] == []


def test_substep_is_soft_no_strong_verdict():
    weeks = [wk(1, "Base 1", "base", "current", actual=180), wk(2, "Base 2", "base")]
    r = prog.assess_progression(FakeM(chg=2.0), plan(weeks), AO)
    assert r["transition_kind"] == "substep" and r["verdict"] in ("ON_TRACK",)
