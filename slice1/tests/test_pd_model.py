"""Om3CP power-duration fit (mFTP) + the estimated-power exclusion from the PD curve."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sources import metrics, pd_model   # noqa: E402

WINDOWS = [1, 5, 15, 30, 60, 120, 180, 300, 600, 720, 900, 1200, 1800, 2700, 3600, 5400, 7200]


def _synthetic_curve(cp, w, pmax, cpttf, a):
    """A noiseless Om3CP curve sampled at the real MMP durations → {dur(str): watts}."""
    import numpy as np
    return {str(t): float(pd_model._om3cp(np.array([t], float), cp, w, pmax, cpttf, a)[0])
            for t in WINDOWS}


def test_fit_cp_free_recovers_known_cp():
    mmp = _synthetic_curve(cp=210, w=16000, pmax=950, cpttf=2400, a=8)
    cp = pd_model.fit_cp_free(mmp)
    assert cp is not None and abs(cp - 210) < 5        # free fit recovers the planted CP


def test_fit_cp_pinned_is_plausible_and_lower():
    # production fit pins Pmax to the 5 s value (≠ the curve's true t→0 Pmax), so it reads LOWER —
    # by design; metrics._series anchors the level back with the free-vs-pinned offset.
    mmp = _synthetic_curve(cp=210, w=16000, pmax=950, cpttf=2400, a=8)
    pin = pd_model.fit_cp(mmp); free = pd_model.fit_cp_free(mmp)
    assert pin is not None and 60 < pin < 400
    assert pin < free                                   # pinning shifts CP down (the offset closes it)


def test_fit_cp_none_when_too_few_points():
    assert pd_model.fit_cp({"180": 250, "720": 210}) is None   # < min points + no 5 s anchor
    assert pd_model.fit_cp({}) is None
    assert pd_model.fit_cp_free({}) is None


def test_estimated_power_excluded_from_curve():
    """device_watts False (Strava-estimated) rides must not enter the MMP envelope or Pmax."""
    by = {"2024-03-01": [
        {"date": "2024-03-01", "device_watts": True,  "mmp": {"5": 600, "300": 250}},
        {"date": "2024-03-01", "device_watts": False, "mmp": {"5": 1200, "300": 400}},  # estimated junk
    ]}
    env = metrics._rolling_envelope(by, 90, "2024-03-01")
    assert env["300"] == 250 and env["5"] == 600                # estimated values excluded
    assert metrics._rolling_best(by, "5", 90, "2024-03-01") == 600   # Pmax source excludes estimated


def test_real_power_rides_still_counted():
    by = {"2024-03-01": [{"date": "2024-03-01", "device_watts": True, "mmp": {"5": 700, "300": 260}}]}
    assert metrics._rolling_best(by, "5", 90, "2024-03-01") == 700
