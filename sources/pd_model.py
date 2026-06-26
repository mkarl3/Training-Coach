"""Power-Duration curve fit — Om3CP (3-parameter Critical Power + a log-linear decay past a
breakpoint), the OmPD family from Puchowicz/Baker/Clarke (J Sports Sci 2020). Fit to a 90-day
max-mean-power envelope it yields a Critical Power (≈ modeled FTP) that tracks WKO's mFTP markedly
better than the old 2-point CP — validated r≈0.76 vs 0.66 against the athlete's WKO5 history.

Scope (validated 2026-06-26, see backlog):
  • CP (this module) → mFTP. Trust it for the trend.
  • Pmax, pVO2max come from OBSERVED bests (5 s, 5 min), NOT the fit — the fitted Pmax param is
    unstable (it blows up by ~600 W).
  • TTE and FRC are NOT produced here: they could not be reproduced from Strava MMP by ANY method
    (curve-crossing, the Om3CP breakpoint, or supervised regression onto WKO's own numbers). Don't
    resurrect them off this curve without revisiting that finding.

scipy is used only where it earns its keep: one bounded least-squares fit per rolling window.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

_FIT_MIN, _FIT_MAX, _MIN_POINTS = 1, 7200, 7        # need a decent spread of the curve to fit
_P0 = [200.0, 15000.0, 800.0, 2400.0, 10.0]         # CP, W', Pmax, CPTTF(breakpoint s), A(decay)
_BOUNDS = ([60, 2000, 400, 600, 0], [400, 40000, 1800, 5400, 60])


def _om3cp(t, cp, wprime, pmax, cpttf, a):
    """3-param CP with a log-linear decline of CP for t > CPTTF (continuous: ln(1)=0 at the knee)."""
    base = wprime / (t + wprime / (pmax - cp)) + cp
    return base - np.where(t > cpttf, a * np.log(t / cpttf), 0.0)


def fit_cp(mmp: dict) -> float | None:
    """Modeled Critical Power (≈ mFTP) from a max-mean-power envelope {duration_s: watts}.
    None when the curve has too few points to fit or the fit lands out of physiological range."""
    pts = sorted((int(k), v) for k, v in mmp.items() if v and _FIT_MIN <= int(k) <= _FIT_MAX)
    if len(pts) < _MIN_POINTS:
        return None
    t = np.array([p[0] for p in pts], float)
    p = np.array([p[1] for p in pts], float)
    try:
        popt, _ = curve_fit(_om3cp, t, p, p0=_P0, maxfev=10000, bounds=_BOUNDS)
    except Exception:
        return None
    cp = float(popt[0])
    return round(cp, 1) if 60 < cp < 400 else None
