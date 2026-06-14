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
