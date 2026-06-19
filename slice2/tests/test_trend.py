"""Trend-view assembly tests (dashboard PMC redesign). Verifies the deterministic payload that
the integrated chart + Wattson reading strip ride on: a weekly series, a safe-ramp scalar, and a
capped, ranked, plain-language insight set. Built on the shared real-data fixtures (conftest)."""
import pandas as pd

from watchman import build_trend
from watchman.trend import weekly_series

JARGON = ("ACWR", "acute:chronic", "CTL", "ATL", "TSB")     # never leak into Wattson's prose


def _as_of(m):
    return m.daily.index.max().strftime("%Y-%m-%d")


def test_payload_shape(m, findings):
    t = build_trend(m, findings, _as_of(m))
    assert set(t) == {"as_of", "date_min", "safe_ramp", "series", "projection", "insights"}
    assert isinstance(t["safe_ramp"], float) and t["safe_ramp"] > 0
    assert t["series"] and t["date_min"] == t["series"][0]["date"]
    assert t["projection"] is None                          # no plan passed -> no projection


def test_series_is_weekly_ascending_with_ctl_and_tss(m, findings):
    s = build_trend(m, findings, _as_of(m))["series"]
    dates = [r["date"] for r in s]
    assert dates == sorted(dates)                            # ascending
    for r in s:
        assert isinstance(r["ctl"], float) and isinstance(r["tss"], int)
    # ~weekly spacing: consecutive gaps are 7 days
    gaps = {(pd.Timestamp(b["date"]) - pd.Timestamp(a["date"])).days for a, b in zip(s, s[1:])}
    assert gaps == {7}


def test_series_points_carry_form_and_block_key(m, findings):
    s = build_trend(m, findings, _as_of(m))["series"]
    for r in s:
        assert "tsb" in r and (r["tsb"] is None or isinstance(r["tsb"], float))
        assert "block" in r and r["block"] is None        # no plan_weeks passed -> always None


def test_blocks_attach_when_plan_covers_a_week(m, findings):
    # synthesize a plan covering the last two series weeks (plan week_start = series Sunday - 6d)
    s0 = build_trend(m, findings, _as_of(m))["series"]
    import datetime as dt
    mondays = [(dt.date.fromisoformat(s0[-1]["date"]) - dt.timedelta(days=6)).isoformat(),
               (dt.date.fromisoformat(s0[-2]["date"]) - dt.timedelta(days=6)).isoformat()]
    plan_weeks = [{"week_start": mondays[0], "block": "Build 2"},
                  {"week_start": mondays[1], "block": "Build 2"}]
    s = build_trend(m, findings, _as_of(m), plan={"weeks": plan_weeks})["series"]
    assert s[-1]["block"] == "Build 2" and s[-2]["block"] == "Build 2"
    assert s[0]["block"] is None                           # uncovered weeks stay None


def test_projection_and_prescription_from_plan(m, findings):
    plan = {"meta": {"sustainable_ramp": 2.5, "recent_weekly_tss": 108, "safe_acute_ratio": 1.72},
            "weeks": [{"week_start": "2026-06-22", "week_end": "2026-06-28", "block": "Prep",
                       "weekly_tss_target": 185, "single_ride_tss_cap": 61, "ctl_target": 20.2},
                      {"week_start": "2026-06-29", "week_end": "2026-07-05", "block": "Prep",
                       "weekly_tss_target": 190, "single_ride_tss_cap": 63, "ctl_target": 24.0}]}
    t = build_trend(m, findings, _as_of(m), plan=plan)
    proj = t["projection"]
    assert proj and len(proj["points"]) == 2 and proj["target_ctl"] == 24.0
    now = next(i for i in t["insights"] if i["id"] == "now")
    assert "185" in now["act"] and "61" in now["act"]       # real prescription numbers
    assert now["cta"] is True and now["proj"]               # CTA + projection line present


def test_series_does_not_exceed_as_of(m, findings):
    as_of = m.daily.index.min() + pd.Timedelta(days=400)     # a mid-history cutoff
    t = build_trend(m, findings, as_of.strftime("%Y-%m-%d"))
    assert pd.Timestamp(t["series"][-1]["date"]) <= as_of + pd.Timedelta(days=6)


def test_now_insight_always_present(m, findings):
    t = build_trend(m, findings, _as_of(m))
    now = [i for i in t["insights"] if i["id"] == "now"]
    assert len(now) == 1 and now[0]["zone_start"] is None
    assert now[0]["obs"] and now[0]["mean"] and now[0]["act"]
    assert now[0]["act_label"] == "WHAT YOUR PLAN IS DOING"


def test_failures_capped_and_ranked(m, findings):
    t = build_trend(m, findings, _as_of(m), top_failures=2)
    fails = [i for i in t["insights"] if not i["strength"] and i["id"] != "now"]
    assert len(fails) <= 2
    # each failure carries a zone with start <= end and an anchor inside it
    for f in fails:
        assert f["zone_start"] <= f["zone_end"]
        assert f["zone_start"] <= f["anchor_date"] <= f["zone_end"]


def test_insights_have_clean_prose_no_jargon_no_bare_zeros(m, findings):
    for i in build_trend(m, findings, _as_of(m))["insights"]:
        assert i["title"] and len(i["obs"]) > 15 and i["mean"] and i["act"]
        prose = " ".join([i["obs"], i["mean"], i["act"]])
        assert "~0" not in prose and "None" not in prose
        for j in JARGON:
            assert j not in prose, f"{i['id']} leaked jargon {j!r}"


def test_every_insight_has_a_mood_and_known_color(m, findings):
    for i in build_trend(m, findings, _as_of(m))["insights"]:
        assert i["mood"] in ("alarmed", "approving", "calm")
        assert i["color"] in ("hot", "lose", "hold", "green", "gold")


def test_deterministic(m, findings):
    a = build_trend(m, findings, _as_of(m))
    b = build_trend(m, findings, _as_of(m))
    assert a == b


def test_weekly_series_helper_skips_future_weeks(m):
    cutoff = (m.daily.index.min() + pd.Timedelta(days=200)).strftime("%Y-%m-%d")
    s = weekly_series(m, cutoff)
    assert s and all(pd.Timestamp(r["date"]) <= pd.Timestamp(cutoff) + pd.Timedelta(days=6) for r in s)
