"""Store tests for the Slice 4.5 transient modifiers + adjustment audit trail with undo.
Pure SQLite, no LLM — verifies the persistence the propose/confirm/undo API rides on."""
from plan import store as ps


def _conn():
    c = ps.connect(":memory:")
    ps.create_season(c, "S", "2026-06-01", 7.0, "2026-06-01T00:00:00")
    return c, ps.active_season(c)["id"]


def test_general_goal_persists_and_validates():
    c = ps.connect(":memory:")
    sid = ps.create_season(c, "S", "2026-06-01", 7.0, "t", general_goal="durability")
    assert ps.active_season(c)["general_goal"] == "durability"
    ps.update_season(c, sid, general_goal="balanced")
    assert ps.active_season(c)["general_goal"] == "balanced"
    # the four allowed strings + None are accepted; anything else is rejected (validated in app)
    for g in ("durability", "sustained_threshold", "anaerobic", "balanced", None):
        ps.update_season(c, sid, general_goal=g)
    for bad in ("threshold", "endurance", "sprint", ""):
        try:
            ps.update_season(c, sid, general_goal=bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    try:
        ps.create_season(c, "S2", "2026-06-01", 7.0, "t", general_goal="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_season_without_general_goal_defaults_null():
    c = ps.connect(":memory:")
    ps.create_season(c, "S", "2026-06-01", 7.0, "t")
    assert ps.active_season(c)["general_goal"] is None


def test_readiness_modifier_round_trip_and_isolation():
    c = ps.connect(":memory:")
    ps.create_season(c, "S", "2026-06-01", 7.0, "t")
    sid = ps.active_season(c)["id"]
    ps.add_modifier(c, sid, "readiness", "2026-06-08", "2026-06-18", "t", hours=0.3, reason="fried")
    assert ps.active_readiness(c, sid) == [{"start_date": "2026-06-08", "end_date": "2026-06-18",
                                            "factor": 0.3, "reason": "fried"}]
    av, ic = ps.active_modifiers(c, sid)               # readiness must NOT leak into the other lists
    assert av == [] and ic == []


def test_active_modifiers_shape_for_generator():
    c, sid = _conn()
    ps.add_modifier(c, sid, "availability", "2026-06-08", "2026-06-14", "t", hours=12.0, reason="free")
    ps.add_modifier(c, sid, "intensity_cap", "2026-06-15", "2026-06-28", "t", reason="knee")
    availability, intensity_caps = ps.active_modifiers(c, sid)
    assert availability == [{"start_date": "2026-06-08", "end_date": "2026-06-14",
                             "hours": 12.0, "reason": "free"}]
    assert intensity_caps == [{"start_date": "2026-06-15", "end_date": "2026-06-28", "reason": "knee"}]


def test_modifier_kind_validated():
    c, sid = _conn()
    try:
        ps.add_modifier(c, sid, "bogus", "2026-06-08", "2026-06-14", "t")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_adjustment_audit_and_undo_round_trip():
    c, sid = _conn()
    # apply an intensity-cap modifier and log the adjustment that created it
    rid = ps.add_modifier(c, sid, "intensity_cap", "2026-06-15", "2026-06-28", "t", reason="knee")
    aid = ps.log_adjustment(c, sid, "hard_capacity_change", "knee: easy 2 wks",
                            {"target": "intensity_cap"}, {"table": "plan_modifier", "id": rid},
                            "2026-06-13T00:00:00")
    assert len(ps.active_modifiers(c, sid)[1]) == 1
    hist = ps.adjustments_for(c, sid)
    assert hist[0]["id"] == aid and hist[0]["active"] and hist[0]["summary"] == "knee: easy 2 wks"

    # undo: deactivates the adjustment AND the modifier it created -> generator sees nothing
    assert ps.undo_adjustment(c, aid) == aid
    assert ps.active_modifiers(c, sid)[1] == []
    assert ps.adjustments_for(c, sid, active_only=True) == []
    assert ps.adjustments_for(c, sid)[0]["active"] is False     # still in history
    # second undo is a no-op
    assert ps.undo_adjustment(c, aid) is None


def test_undo_time_loss_deletes_unavailable():
    c, sid = _conn()
    uid = ps.add_unavailable(c, sid, "2026-07-01", "2026-07-07", "2026-06-13T00:00:00", reason="flu")
    aid = ps.log_adjustment(c, sid, "hard_time_loss", "flu: out a week",
                            {"target": "unavailable"}, {"table": "unavailable_period", "id": uid},
                            "2026-06-13T00:00:00")
    assert len(ps.unavailable_for(c, sid)) == 1
    ps.undo_adjustment(c, aid)
    assert ps.unavailable_for(c, sid) == []
