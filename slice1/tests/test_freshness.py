"""System data-freshness / confidence: days since the last effort that actually informs each system,
tiered fresh/aging/stale. The guardrail that stops Wattson reading a 'drop' off stale data."""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sources import metrics   # noqa: E402

ASOF = "2026-06-27"


def _ride(date, mmp, device_watts=True):
    return {"date": date, "np": 200, "device_watts": device_watts, "mmp": {k: float(v) for k, v in mmp.items()}}


def _days_ago(n):
    return (dt.date.fromisoformat(ASOF) - dt.timedelta(days=n)).isoformat()


def test_recent_max_sprint_makes_pmax_fresh():
    rides = [_ride(_days_ago(2), {"5": 900, "300": 300, "1200": 250}),     # fresh sprint today-ish
             _ride(_days_ago(40), {"5": 900})]                              # the rolling best is matched recently
    fr = metrics.systems_freshness(rides, ASOF)
    assert fr["pmax_w"]["confidence"] == "fresh"
    assert fr["pmax_w"]["days_since"] <= metrics.FRESH_DAYS


def test_old_only_sprint_makes_pmax_stale():
    # The only sprint near the rolling best is 80 days old → Pmax is stale even though the value exists.
    rides = [_ride(_days_ago(80), {"5": 900}),
             _ride(_days_ago(3), {"300": 300, "1200": 250})]               # recent rides, but no sprint
    fr = metrics.systems_freshness(rides, ASOF)
    assert fr["pmax_w"]["confidence"] == "stale"
    assert fr["pmax_w"]["days_since"] >= metrics.AGING_DAYS


def test_aging_tier_between_thresholds():
    rides = [_ride(_days_ago(30), {"5": 900})]
    fr = metrics.systems_freshness(rides, ASOF)
    assert fr["pmax_w"]["confidence"] == "aging"


def test_estimated_power_does_not_count_as_informing():
    # A device_watts=False ride can't inform the curve, so a recent estimated sprint stays stale.
    rides = [_ride(_days_ago(80), {"5": 900}),
             _ride(_days_ago(1), {"5": 900}, device_watts=False)]
    fr = metrics.systems_freshness(rides, ASOF)
    assert fr["pmax_w"]["confidence"] == "stale"


def test_no_data_is_confidence_none():
    fr = metrics.systems_freshness([], ASOF)
    assert all(v["confidence"] == "none" for v in fr.values())


def test_refresh_target_pmax_benchmarks_against_alltime_pb():
    # Pmax is all-out: floor = recent 90d best (600); the PB to beat = all-time best (700).
    rides = [_ride(_days_ago(10), {"5": 600}), _ride(_days_ago(300), {"5": 700})]
    t = metrics.refresh_target(rides, ASOF, "pmax_w")
    assert t["floor_w"] == 600 and t["stretch_w"] == 700 and t["stretch_kind"] == "peak"
    assert t["label"] and t["effort"]


def test_refresh_target_pmax_pb_shown_even_when_recent_is_best():
    # No 'hollow stretch' suppression for sprints — you can always be told to beat your PB.
    rides = [_ride(_days_ago(10), {"5": 700}), _ride(_days_ago(300), {"5": 650})]
    t = metrics.refresh_target(rides, ASOF, "pmax_w")
    assert t["floor_w"] == 700 and t["stretch_w"] == 700   # PB == recent, still offered


def test_refresh_target_none_without_data():
    assert metrics.refresh_target([], ASOF, "pmax_w") is None
