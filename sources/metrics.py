"""Metrics engine — turns Strava-derived ride summaries into the daily series the app consumes
(TSS / CTL / ATL / TSB + the power-duration estimates), with NO WKO5 input. Fully self-consistent:
a rolling, smoothed Critical Power IS the FTP used for TSS, so the whole pipeline stands on raw
power alone. Validated against WKO5 (see validate.py): CTL r≈0.97, CP↔mFTP r≈0.95.

Stage 1 scope = the validated core (load + PD + CP/W′/Pmax). Stream/HR/wellness-dependent fields
(EF, Pw:HR decoupling, power-zone TiZ, HRV/sleep/RHR/weight) are deferred → emitted as None for now
(noted per field); they get filled when the pull retains streams + a wellness source is added.
"""
from __future__ import annotations

import datetime as dt

CTL_TC, ATL_TC = 42.0, 7.0
CP_WINDOW_DAYS = 90          # trailing window for rolling power bests feeding CP
CP_SMOOTH_TC = 21.0          # EWMA on the daily CP series → stable enough for plateau detection
W_SHORT, W_LONG = "180", "720"   # 3-min & 12-min bests for the 2-point CP/W′ model


def _drange(a: str, b: str):
    d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def _ewma(prev, x, tc):
    return x if prev is None else prev + (x - prev) / tc


def rides_by_date(summaries: list[dict]) -> dict[str, list[dict]]:
    by = {}
    for s in summaries:
        if s.get("np"):
            by.setdefault(s["date"], []).append(s)
    return by


def _rolling_best(by_date, win_key, days, asof):
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=days)).isoformat()
    best = None
    for d, rides in by_date.items():
        if lo <= d <= asof:
            for r in rides:
                v = (r.get("mmp") or {}).get(win_key)
                if v and (best is None or v > best):
                    best = v
    return best


def _cp_wprime(p_short, p_long):
    """2-point Critical Power model from the 3-min & 12-min bests. CP ≈ mFTP, W′ ≈ FRC."""
    if not p_short or not p_long or p_long >= p_short:
        return None, None
    cp = (p_long * 720 - p_short * 180) / (720 - 180)
    wprime = (p_short - cp) * 180                      # joules
    return cp, wprime


def build_daily(summaries: list[dict]) -> list[dict]:
    """Daily rows shaped for the app's `daily` table, computed purely from ride summaries."""
    by = rides_by_date(summaries)
    if not by:
        return []
    start, end = min(by), max(by)

    # 1) rolling-90d Critical Power = the FTP we'll use. The rolling best is already slow-moving;
    #    heavy EWMA on top LAGS a declining trend and wrecks the correlation (raw 90d r≈0.95 vs
    #    over-smoothed 0.45 on Mike's detrain). So use the raw rolling CP, carried over ride-less
    #    days. (A light plateau-smoothing layer for the Slice-5 gates can sit downstream later.)
    cp_smooth, wprime_at, pmax_at = {}, {}, {}
    last_cp = last_wp = None
    for d in _drange(start, end):
        cp, wp = _cp_wprime(_rolling_best(by, W_SHORT, CP_WINDOW_DAYS, d),
                            _rolling_best(by, W_LONG, CP_WINDOW_DAYS, d))
        if cp:
            last_cp, last_wp = cp, wp
        cp_smooth[d] = last_cp
        wprime_at[d] = last_wp
        pmax_at[d] = _rolling_best(by, "5", CP_WINDOW_DAYS, d)

    # 2) daily TSS using that day's smoothed CP as FTP (self-consistent), then CTL/ATL/TSB
    ftp_fallback = next((v for v in cp_smooth.values() if v), 180.0)
    ctl = atl = None
    rows = []
    for d in _drange(start, end):
        ftp = cp_smooth.get(d) or ftp_fallback
        rides = by.get(d, [])
        tss = work = dur = 0.0
        for r in rides:
            if_ = r["np"] / ftp
            tss += (r["duration_s"] / 3600) * if_ ** 2 * 100
            dur += r["duration_s"]
            work += (r.get("avg") or r["np"]) * r["duration_s"] / 1000.0   # kJ ≈ avg W × s / 1000
        ctl = _ewma(ctl, tss, CTL_TC)
        atl = _ewma(atl, tss, ATL_TC)
        cp = cp_smooth.get(d)
        rows.append({
            "date": d, "year": int(d[:4]), "is_projected": 0,
            "has_ride": 1 if rides else 0, "num_workouts": len(rides),
            "tss_sum": round(tss, 1), "duration_sec": int(dur) or None,
            "work_kj": round(work) or None,
            "atl": round(atl, 1), "ctl": round(ctl, 1), "tsb": round(ctl - atl, 1),
            "mftp_w": round(cp) if cp else None,                      # CP stands in for mFTP
            "frc_kj": round(wprime_at[d] / 1000, 1) if wprime_at[d] else None,  # W′ → FRC
            "pmax_w": round(pmax_at[d]) if pmax_at[d] else None,
            "tte_sec": None,        # TODO: model TTE from CP/W′ (weak proxy; left null for now)
            # stream/HR/wellness-dependent — deferred (Stage: rich metrics):
            "if_daily": None, "ef": None, "decoupling_pct": None,
            "weight_lb": None, "fat_pct": None, "sickness": None,
            "hrv_7d_avg_ms": None, "hrv_daily_ms": None, "rhr_bpm": None,
        })
    return rows


if __name__ == "__main__":          # Stage-1 verify: engine output, end-to-end, vs WKO5
    import json, os, sqlite3
    HERE = os.path.dirname(__file__)
    summ = list(json.load(open(os.path.join(HERE, ".strava_summaries.json"))).values())
    rows = build_daily(summ)
    print(f"built {len(rows)} daily rows  {rows[0]['date']} .. {rows[-1]['date']}")
    last = rows[-1]
    print("latest:", {k: last[k] for k in ("date", "tss_sum", "ctl", "atl", "tsb", "mftp_w", "frc_kj", "pmax_w")})

    db = sqlite3.connect(os.path.join(HERE, "..", "slice0", "wko.db"))
    wko = {r[0]: r[1:] for r in db.execute(
        "SELECT date,ctl,mftp_w FROM daily WHERE is_projected=0")}

    def pear(p):
        n = len(p)
        mx = sum(a for a, _ in p) / n; my = sum(b for _, b in p) / n
        cov = sum((a - mx) * (b - my) for a, b in p)
        vx = sum((a - mx) ** 2 for a, _ in p) ** .5; vy = sum((b - my) ** 2 for _, b in p) ** .5
        return cov / (vx * vy) if vx and vy else None

    cpair = [(r["ctl"], wko[r["date"]][0]) for r in rows if r["date"] in wko and wko[r["date"]][0] is not None]
    fpair = [(r["mftp_w"], wko[r["date"]][1]) for r in rows if r["date"] in wko and r["mftp_w"] and wko[r["date"]][1]]
    print(f"END-TO-END (our CP as FTP, no WKO5 input):  CTL r={pear(cpair):.3f}  mFTP r={pear(fpair):.3f}")
