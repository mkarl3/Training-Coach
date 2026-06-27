"""Weekly-briefing tests (Slice 4.5 weekly check-in). Deterministic summary the coach opens
the check-in with — verifies it composes planned-vs-actual + PMC + next-week + themes, and
degrades gracefully when there's no season yet. Numbers come from code, never the model."""
import datetime as dt

from wko_metrics import DEFAULT_PROFILE
from plan import generator, review


def _season(as_of, start_offset_weeks, race_weeks_out=16, hours=7.0):
    start = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=start_offset_weeks)).isoformat()
    a = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=race_weeks_out)).isoformat()
    return ({"start_date": start, "weekly_hours_budget": hours},
            [{"name": "A", "event_date": a, "priority": "A", "event_type": "gran_fondo"}])


def test_briefing_without_a_plan_degrades_gracefully(m, as_of):
    b = review.weekly_briefing(m, None, "green", [], as_of)
    assert b["in_season"] is False and b["next_week"] is None
    assert isinstance(b["week_reviewed"]["actual_tss"], int)        # still summarizes actual training
    assert set(b["pmc"]) == {"ctl", "atl", "tsb"}
    assert b["week_reviewed"]["planned_tss"] is None
    assert "Board: green" in review.briefing_text(b)


def test_briefing_in_season_has_planned_vs_actual_and_next(m, as_of):
    # season started 8 weeks ago -> closed weeks carry planned-vs-actual; later weeks are 'next'
    season, events = _season(as_of, start_offset_weeks=-8)
    plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
    b = review.weekly_briefing(m, plan, "green", [], as_of)
    assert b["in_season"] is True
    wr = b["week_reviewed"]
    assert wr["planned_tss"] is not None and wr["compliance_pct"] is not None
    assert b["next_week"] and b["next_week"]["weekly_tss_target"] >= 0
    txt = review.briefing_text(b)
    assert "planned" in txt and "Next up" in txt


def test_briefing_carries_themes(m, as_of):
    themes = [{"category": "sleep", "label": "sleep", "checkins": 3, "quotes": ["slept badly"]}]
    b = review.weekly_briefing(m, None, "amber", themes, as_of)
    assert b["themes"] == themes
    assert "sleep ×3" in review.briefing_text(b)


def test_pmc_directions_are_signed(m, as_of):
    b = review.weekly_briefing(m, None, "green", [], as_of)
    ctl = b["pmc"]["ctl"]
    if ctl["delta_7d"] is not None:
        assert ctl["dir_7d"] in ("up", "down", "flat")


_SYS = {
    "pmax_w": {"value": 584, "unit": "W", "dir": "falling", "delta_pct": -10.3},
    "tte_sec": {"value": 19.7, "unit": "min", "dir": "rising", "delta_pct": 19.0},
    "mftp_w": {"value": 185, "unit": "W", "dir": "falling", "delta_pct": -3.2},
}


def test_systems_sentence_suppresses_offfocus_decline_but_shows_notable_rise():
    # Prep has no PD focus -> the falling Pmax/mFTP are the expected cost of base work (suppressed),
    # but TTE's notable rise is a real surprise and surfaces — as a `notable` aside (with the
    # where-you-stand read), NOT as block-relevant evidence.
    prep = review._systems_lines("Prep", _SYS)
    assert prep["relevant"] is None
    assert "Pmax" not in prep["notable"] and "TTE" in prep["notable"]


def test_systems_sentence_speaks_block_focus_with_actionable_fix():
    # Base 3 focus = mFTP & TTE -> both spoken as `relevant`; the sliding (focus) mFTP gets a tail.
    b3 = review._systems_lines("Base 3", _SYS)["relevant"]
    assert "TTE" in b3 and "185 W" in b3 and "duration work will lift it" in b3
    assert "Pmax" not in b3                         # off-focus + falling -> still suppressed


_QUIET = {
    "pmax_w": {"value": 584, "unit": "W", "dir": "falling", "delta_pct": -10.3},
    "tte_sec": {"value": 19.7, "unit": "min", "dir": "flat", "delta_pct": 1.0},
    "mftp_w": {"value": 185, "unit": "W", "dir": "falling", "delta_pct": -3.2},
}


_STALE = {  # Build 1 focuses Pmax; here Pmax is "falling" but the data is stale (no recent sprint)
    "pmax_w": {"value": 584, "unit": "W", "dir": "falling", "delta_pct": -10.3, "confidence": "stale", "days_since": 90},
    "mftp_w": {"value": 185, "unit": "W", "dir": "rising", "delta_pct": 4.0, "confidence": "fresh", "days_since": 1},
}


def test_stale_system_hedges_instead_of_asserting_a_decline():
    # Build 1 reads Pmax — but it's stale, so it must NOT be spoken as "gone soft"; it hedges and names
    # the missing effort + the staleness (THE guardrail: don't read a drop off old data).
    b1 = review._systems_lines("Build 1", _STALE)["relevant"]
    assert "gone soft" not in b1
    assert "stale data" in b1 and "full sprint" in b1 and "13 weeks" in b1   # 90d -> ~13 wk


def test_stale_notable_rise_is_suppressed():
    # An off-focus RISE on stale data isn't a real surprise -> not surfaced as a notable aside.
    stale_rise = {"pmax_w": {"value": 600, "unit": "W", "dir": "rising", "delta_pct": 12.0,
                             "confidence": "stale", "days_since": 70}}
    assert review._systems_lines("Prep", stale_rise)["notable"] is None


def test_refresh_prescription_pmax_is_beat_your_pb_no_target():
    # A sprint is all-out — no watt target to 'aim' for; just the PB to beat.
    systems = {"pmax_w": {"value": 584, "confidence": "stale", "days_since": 90}}
    targets = {"pmax_w": {"label": "few all-out sprints", "effort": "sprint", "floor_w": 584,
                          "stretch_w": 872, "stretch_kind": "peak"}}
    p = review.refresh_prescription(systems, targets)
    assert p["system"] == "pmax_w" and p["weeks"] == 13
    s = p["sentence"]
    assert "max sprint" in s and "all-out efforts" in s and "PB is 872 W, go beat it" in s and "13 weeks" in s
    assert "aim between" not in s and "584 W lately" not in s   # no 'hit this target' framing for a sprint


def test_refresh_prescription_model_stretch_is_forward():
    systems = {"mftp_w": {"value": 185, "confidence": "aging", "days_since": 28}}
    targets = {"mftp_w": {"label": "20-minute effort", "effort": "threshold effort", "floor_w": 200,
                          "stretch_w": 215, "stretch_kind": "model"}}
    s = review.refresh_prescription(systems, targets)["sentence"]
    assert "aim between 200 and 215 W" in s and "top end's in you" in s


def test_refresh_prescription_confirm_when_no_stretch():
    systems = {"mftp_w": {"value": 185, "confidence": "aging", "days_since": 30}}
    targets = {"mftp_w": {"label": "20-minute effort", "effort": "threshold effort", "floor_w": 210,
                          "stretch_w": None, "stretch_kind": None}}
    s = review._refresh_sentence(systems, targets)
    assert "210 W" in s and "let's confirm it" in s and "872" not in s


def test_refresh_prescription_silent_when_fresh():
    systems = {"pmax_w": {"value": 584, "confidence": "fresh", "days_since": 3}}
    targets = {"pmax_w": {"label": "few all-out sprints", "effort": "sprint", "floor_w": 584,
                          "stretch_w": 872, "stretch_kind": "peak"}}
    assert review.refresh_prescription(systems, targets) is None
    assert review._refresh_sentence({}, {}) is None


def test_relevant_systems_accessor_matches_block_map():
    assert "pmax_w" in review.relevant_systems("Build 1")
    assert review.relevant_systems("Prep") == ()


def test_systems_sentence_none_when_nothing_to_say():
    none = review._systems_lines("Base 3", None)
    assert none["relevant"] is None and none["notable"] is None
    # Race/taper: no focus systems, and the only movers are off-focus declines -> stays silent
    race = review._systems_lines("Race", _QUIET)
    assert race["relevant"] is None and race["notable"] is None
