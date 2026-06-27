"""Power-Duration curve fit — Om3CP (3-parameter Critical Power + a log-linear decay past a
breakpoint), the OmPD family from Puchowicz/Baker/Clarke (J Sports Sci 2020). Fit to a 90-day
max-mean-power envelope it yields a Critical Power (≈ modeled FTP).

Estimators, validated against the athlete's WKO5 history (2026-06-26):
  • fit          — the PRODUCTION fit (Pmax pinned to the observed 5 s best — kills the fit wobble
    from the unstable free Pmax param — AND the 5–30 min threshold region up-weighted). Returns
    BOTH from one fit: CP (≈mFTP shape, r≈0.78 / ~6 W / jitter 2.6 vs WKO; reads ~20 W low → caller
    applies a self-derived level offset) and pVO2max = modeled power at 5 min (validated as the WKO
    power-at-VO2max match; the gate's fractional-utilization comes out 83% ≈ WKO's 84%).
  • fit_cp_free   — the unconstrained 5-param fit. Jittery but ~unbiased in LEVEL, so it's used
    only as the SCALE anchor for fit()'s CP offset (never shown directly).

Pmax comes from the OBSERVED 5 s best, not the fit. TTE/FRC are NOT produced — they could not be
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


_PVO2_DURATION = 300        # modeled power at 5 min = pVO2max (validated best WKO match for the gate)


def _fit_params(mmp: dict, pin_pmax: bool, weighted: bool):
    """Fit Om3CP, returning the full param tuple (cp, w, pmax, cpttf, a) or None."""
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
            return (float(popt[0]), float(popt[1]), float(pm), float(popt[2]), float(popt[3]))
        popt, _ = curve_fit(_om3cp, t, p, p0=[200, 15000, 800, 2400, 10], maxfev=10000,
                            bounds=([60, 2000, 400, 600, 0], [400, 40000, 1800, 5400, 60]),
                            sigma=sigma, absolute_sigma=False)
        return tuple(float(x) for x in popt)
    except Exception:
        return None


def fit(mmp: dict) -> dict | None:
    """Production fit — Pmax-pinned + threshold-weighted Om3CP. Returns BOTH modeled metrics from one
    fit: {'cp': ≈mFTP shape (reads ~20 W low, caller applies the self-derived level offset),
    'pvo2max': modeled power at 5 min (validated as the WKO power-at-VO2max match)}. None if too few
    points / out of range."""
    pr = _fit_params(mmp, pin_pmax=True, weighted=True)
    if pr is None or not (60 < pr[0] < 400):
        return None
    return {"cp": round(pr[0], 1), "pvo2max": round(float(_om3cp(_PVO2_DURATION, *pr)), 1)}


def predict(mmp: dict, t_seconds: float) -> float | None:
    """Modeled power (W) at `t_seconds` from the production (Pmax-pinned + threshold-weighted) Om3CP
    fit — used to set a forward 'stretch' target at a duration the athlete hasn't ridden recently
    (the model infers it from their other current efforts). None if the curve won't fit."""
    pr = _fit_params(mmp, pin_pmax=True, weighted=True)
    if pr is None or not (60 < pr[0] < 400):
        return None
    return float(_om3cp(np.array([float(t_seconds)]), *pr)[0])


def fit_cp_free(mmp: dict) -> float | None:
    """Unconstrained 5-param fit — used only as the LEVEL anchor for fit()'s CP offset (jittery, but
    ~unbiased in level vs WKO). Not shown directly."""
    pr = _fit_params(mmp, pin_pmax=False, weighted=False)
    return round(pr[0], 1) if pr is not None and 60 < pr[0] < 400 else None
