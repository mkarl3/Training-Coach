"""Power-Duration curve fit — Om3CP (3-parameter Critical Power + a log-linear decay past a
breakpoint), the OmPD family from Puchowicz/Baker/Clarke (J Sports Sci 2020). Fit to a 90-day
max-mean-power envelope it yields a Critical Power (≈ modeled FTP).

Two estimators, validated against the athlete's WKO5 history (2026-06-26):
  • fit_cp        — the PRODUCTION mFTP shape: Pmax pinned to the observed 5 s best (kills the
    fit wobble — the free Pmax param is unstable) AND the 5–30 min threshold region up-weighted
    (mFTP lives there). r≈0.78 vs WKO, ~6 W, jitter 2.6 (matches WKO's 2.6). It reads ~20 W LOW
    in absolute terms — the caller anchors it (see metrics._series, self-derived offset).
  • fit_cp_free   — the unconstrained 5-param fit. Jittery but ~unbiased in LEVEL, so it's used
    only as the SCALE anchor for fit_cp's offset (never shown directly).

Pmax/pVO2max come from OBSERVED bests, not the fit. TTE/FRC are NOT produced — they could not be
reproduced from Strava MMP by any method (see backlog). scipy: one bounded least-squares per fit.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

_FIT_MIN, _FIT_MAX, _MIN_POINTS = 1, 7200, 7
_THRESH_LO, _THRESH_HI, _THRESH_W = 300, 1800, 3.0     # up-weight 5–30 min (where mFTP lives)


def _om3cp(t, cp, wprime, pmax, cpttf, a):
    """3-param CP with a log-linear decline of CP for t > CPTTF (continuous: ln(1)=0 at the knee)."""
    base = wprime / (t + wprime / (pmax - cp)) + cp
    return base - np.where(t > cpttf, a * np.log(t / cpttf), 0.0)


def _fit(mmp: dict, pin_pmax: bool, weighted: bool):
    pts = sorted((int(k), v) for k, v in mmp.items() if v and _FIT_MIN <= int(k) <= _FIT_MAX)
    if len(pts) < _MIN_POINTS or (pin_pmax and "5" not in mmp):
        return None
    t = np.array([p[0] for p in pts], float)
    p = np.array([p[1] for p in pts], float)
    sigma = np.array([(1.0 / _THRESH_W if _THRESH_LO <= tt <= _THRESH_HI else 1.0) for tt in t]) \
        if weighted else None
    try:
        if pin_pmax:
            pm = mmp["5"]
            popt, _ = curve_fit(lambda tt, cp, w, cpttf, a: _om3cp(tt, cp, w, pm, cpttf, a),
                                t, p, p0=[200, 15000, 2400, 10], maxfev=10000,
                                bounds=([60, 2000, 600, 0], [400, 40000, 5400, 60]),
                                sigma=sigma, absolute_sigma=False)
        else:
            popt, _ = curve_fit(_om3cp, t, p, p0=[200, 15000, 800, 2400, 10], maxfev=10000,
                                bounds=([60, 2000, 400, 600, 0], [400, 40000, 1800, 5400, 60]),
                                sigma=sigma, absolute_sigma=False)
        cp = float(popt[0])
    except Exception:
        return None
    return round(cp, 1) if 60 < cp < 400 else None


def fit_cp(mmp: dict) -> float | None:
    """Production mFTP SHAPE — Pmax-pinned + threshold-weighted Om3CP. Stable, WKO-tracking; reads
    ~20 W low, so the caller applies a self-derived level offset. None if too few points."""
    return _fit(mmp, pin_pmax=True, weighted=True)


def fit_cp_free(mmp: dict) -> float | None:
    """Unconstrained 5-param fit — used only as the LEVEL anchor for fit_cp's offset (jittery, but
    ~unbiased in level vs WKO). Not shown directly."""
    return _fit(mmp, pin_pmax=False, weighted=False)
