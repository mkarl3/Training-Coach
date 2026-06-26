"""Metrics engine — turns Strava-derived ride summaries into the daily + per-workout rows the app
consumes (TSS / CTL / ATL / TSB + the power-duration estimates), with NO WKO5 input. TSS uses the
athlete's dated set-FTP history (see _ftp_resolver); the modeled mFTP comes from an Om3CP power-
duration fit (see pd_model). Validated vs WKO5: mFTP r≈0.75, Pmax r≈0.95 (observed 5 s), CTL r≈0.97
once warm. TTE/FRC are NOT emitted — not reproducible from Strava MMP (see backlog).

Stage 1 scope = the validated core (load + PD + CP/W′/Pmax). Stream/HR/wellness-dependent fields
(EF, Pw:HR decoupling, power-zone TiZ, TTE model, HRV/sleep/RHR/weight) are deferred → emitted as
None for now; they fill in once the pull retains streams + a wellness source is added.

Two findings baked in: (1) heavy smoothing of CP LAGS a declining trend and wrecks correlation —
use the raw rolling-90d best (it's already slow-moving); (2) CTL (42d) + the 90d CP window need
RUNWAY, so a real pull seeds from FULL history (the first ~6 weeks of any window are cold-start).
"""
from __future__ import annotations

import datetime as dt

from . import pd_model

CTL_TC, ATL_TC = 42.0, 7.0
CP_WINDOW_DAYS = 90
W_SHORT, W_LONG = "180", "720"          # 3-min & 12-min bests for the 2-point CP/W′ model


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
                if r.get("device_watts") is False:        # estimated power → out of the PD curve
                    continue
                v = (r.get("mmp") or {}).get(win_key)
                if v and (best is None or v > best):
                    best = v
    return best


def _rolling_envelope(by_date, days, asof):
    """The 90-day max-mean-power envelope {duration_s(str): watts} — the curve Om3CP fits. Excludes
    estimated-power rides (Strava device_watts False), whose power is unreliable for max efforts."""
    lo = (dt.date.fromisoformat(asof) - dt.timedelta(days=days)).isoformat()
    env = {}
    for d, rides in by_date.items():
        if lo <= d <= asof:
            for r in rides:
                if r.get("device_watts") is False:
                    continue
                for k, v in (r.get("mmp") or {}).items():
                    if v and (k not in env or v > env[k]):
                        env[k] = v
    return env


def _cp_wprime(p_short, p_long):
    """2-point Critical Power from the 3-min & 12-min bests. CP ≈ mFTP, W′ ≈ FRC."""
    if not p_short or not p_long or p_long >= p_short:
        return None, None
    cp = (p_long * 720 - p_short * 180) / (720 - 180)
    return cp, (p_short - cp) * 180          # CP (W), W′ (J)


def _series(summaries):
    """Shared pass: per-date modeled CP (Om3CP fit of the 90-day curve, ≈ mFTP) + legacy 2-pt W'
    + observed Pmax, carried over ride-less days. CP is refit only when a new ride enters the window
    (perf — CP is slow-moving), then held until the next ride.
    Returns (by_date, start, end, cp_at, wprime_at, pmax_at, ftp_fallback)."""
    by = rides_by_date(summaries)
    if not by:
        return {}, None, None, {}, {}, {}, 180.0
    start, end = min(by), max(by)
    cp_at, wprime_at, pmax_at = {}, {}, {}
    last_cp = last_wp = None
    for d in _drange(start, end):
        if d in by:                                       # new data in the window → refit
            env = _rolling_envelope(by, CP_WINDOW_DAYS, d)
            cp = pd_model.fit_cp(env)
            _, wp = _cp_wprime(env.get(W_SHORT), env.get(W_LONG))   # legacy W' (low-confidence FRC)
            if cp:
                last_cp = cp
            if wp:
                last_wp = wp
        cp_at[d], wprime_at[d] = last_cp, last_wp
        pmax_at[d] = _rolling_best(by, "5", CP_WINDOW_DAYS, d)
    ftp_fallback = next((v for v in cp_at.values() if v), 180.0)
    return by, start, end, cp_at, wprime_at, pmax_at, ftp_fallback


def _ride_tss(ride, ftp):
    if_ = ride["np"] / ftp
    return (ride["duration_s"] / 3600) * if_ ** 2 * 100, if_


def _ftp_asof(hist, d, fallback):
    """The set FTP effective on date `d`: the latest entry with date <= d; if d precedes all
    entries, the earliest entry (back-fill); `fallback` when the history is empty."""
    val = None
    for e in hist:                                    # hist sorted ascending by date
        if e["date"] <= d:
            val = e["ftp"]
        else:
            break
    if val is None and hist:
        val = hist[0]["ftp"]
    return val or fallback


def _ftp_resolver(load_ftp, cp_at, fb):
    """A date -> set-FTP function. `load_ftp` may be a dated history (list of {date, ftp}) for the
    time-varying TSS, a single float (one FTP across all of history), or None/empty (self-consistent
    CP fallback, carried over ride-less days)."""
    if isinstance(load_ftp, list) and load_ftp:
        hist = sorted(load_ftp, key=lambda e: e["date"])
        return lambda d: _ftp_asof(hist, d, cp_at.get(d) or fb)
    if isinstance(load_ftp, (int, float)) and load_ftp:
        return lambda d: load_ftp
    return lambda d: cp_at.get(d) or fb


# Classic 6-zone power model as fractions of FTP (Coggan boundaries), mapped to tiz_pwr_z1..z6.
_ZONE_FRAC = [0.0, 0.55, 0.75, 0.90, 1.05, 1.20, 1e9]


def _accumulate_tiz(secs, phist, ftp):
    """Add a ride's power histogram ({watt_bin: seconds}) into the 6 zone-second buckets."""
    for b, sec in (phist or {}).items():
        w = int(b) + 5                                    # 10 W bin midpoint
        frac = w / ftp
        for zi in range(6):
            if _ZONE_FRAC[zi] <= frac < _ZONE_FRAC[zi + 1]:
                secs[zi] += sec
                break


def build_daily(summaries: list[dict], load_ftp: float | None = None) -> list[dict]:
    """Daily rows shaped for the app's `daily` table, computed purely from ride summaries.

    load_ftp = the athlete's THRESHOLD/set FTP used for TSS & IF (WKO5's "bikeFTP"). This is a
    DIFFERENT number from the modeled CP/mFTP used by the gates: TSS ∝ 1/FTP², so dividing by the
    lower modeled CP (~182) instead of the set threshold (~208) inflates every TSS ~30%. When
    load_ftp is None we fall back to CP (self-consistent but hot). mftp_w stays = CP for the gates.

    load_ftp may also be a dated HISTORY (list of {date, ftp}); then each ride is scored with the
    set FTP that was in effect on its date — see _ftp_resolver."""
    by, start, end, cp_at, wprime_at, pmax_at, fb = _series(summaries)
    if not by:
        return []
    resolve = _ftp_resolver(load_ftp, cp_at, fb)
    ctl = atl = None
    rows = []
    for d in _drange(start, end):
        ftp = resolve(d)
        rides = by.get(d, [])
        tss = work = dur = 0.0
        tiz = [0, 0, 0, 0, 0, 0]
        ifs = []
        for r in rides:
            t, if_ = _ride_tss(r, ftp)
            tss += t
            dur += r["duration_s"]
            work += (r.get("avg") or r["np"]) * r["duration_s"] / 1000.0
            ifs.append(if_)
            _accumulate_tiz(tiz, r.get("phist"), ftp)
        ctl = _ewma(ctl, tss, CTL_TC)
        atl = _ewma(atl, tss, ATL_TC)
        cp = cp_at.get(d)
        row = {
            "date": d, "year": int(d[:4]), "is_projected": 0,
            "has_ride": 1 if rides else 0, "num_workouts": len(rides),
            "tss_sum": round(tss, 1), "duration_sec": int(dur) or 0,
            "work_kj": round(work) or None,
            "if_daily": round(sum(ifs) / len(ifs), 3) if ifs else None,   # display-only
            "atl": round(atl, 1), "ctl": round(ctl, 1), "tsb": round(ctl - atl, 1),
            "mftp_w": round(cp) if cp else None,
            "frc_kj": round(wprime_at[d] / 1000, 1) if wprime_at[d] else None,
            "pmax_w": round(pmax_at[d]) if pmax_at[d] else None,
            "tte_sec": None,
        }
        for zi in range(6):                               # tiz_pwr_z1_sec .. z6_sec
            row[f"tiz_pwr_z{zi + 1}_sec"] = int(tiz[zi]) if rides else None
        rows.append(row)
    return rows


def build_workouts(summaries: list[dict], load_ftp: float | None = None) -> list[dict]:
    """Per-ride rows shaped for the app's `workout` table (TSS/IF/NP + PD points), FTP-consistent
    with build_daily (load_ftp = the athlete's set threshold FTP for TSS/IF). EF / decoupling /
    VI / TIS / HR fields deferred → None."""
    by, start, end, cp_at, _wp, _pm, fb = _series(summaries)
    resolve = _ftp_resolver(load_ftp, cp_at, fb)
    rows = []
    for d in sorted(by):
        ftp = resolve(d)
        for r in by[d]:
            tss, if_ = _ride_tss(r, ftp)
            mmp = r.get("mmp") or {}
            sport = (r.get("sport") or "Ride")
            avg_hr = r.get("avg_hr")
            rows.append({
                "date": d, "started_at": r.get("start") or f"{d}T00:00:00",
                "activity_type": sport, "is_cycling": 1 if "ride" in sport.lower() else 0,
                "duration_sec": r["duration_s"],
                "tss": round(tss, 1), "work_kj": round((r.get("avg") or r["np"]) * r["duration_s"] / 1000.0),
                "np_w": round(r["np"], 1), "if_": round(if_, 3),
                "p5s_w": mmp.get("5"), "p1min_w": mmp.get("60"), "p5min_w": mmp.get("300"),
                "p10min_w": None, "p20min_w": mmp.get("1200"), "p1hr_w": None,
                "avg_hr_bpm": avg_hr,
                "ef": round(r["np"] / avg_hr, 2) if avg_hr else None,    # NP/HR efficiency factor
                "vi": None, "pwhr_pct": r.get("decoupling"),            # Pw:HR aerobic decoupling %
                "anaerobic_tis": None, "aerobic_tis": None,
                "source_file": "strava",
            })
    return rows


if __name__ == "__main__":          # Stage-1 verify: engine output, end-to-end, vs WKO5
    import json, os, sqlite3
    HERE = os.path.dirname(__file__)
    summ = list(json.load(open(os.path.join(HERE, ".strava_summaries.json"))).values())
    rows = build_daily(summ)
    wos = build_workouts(summ)
    print(f"built {len(rows)} daily rows + {len(wos)} workout rows  {rows[0]['date']} .. {rows[-1]['date']}")
    last = rows[-1]
    print("latest daily:", {k: last[k] for k in ("date", "tss_sum", "ctl", "atl", "tsb", "mftp_w", "frc_kj", "pmax_w")})

    db = sqlite3.connect(os.path.join(HERE, "..", "slice0", "wko.db"))
    wko = {r[0]: r[1:] for r in db.execute("SELECT date,ctl,mftp_w FROM daily WHERE is_projected=0")}

    def pear(p):
        n = len(p)
        if n < 3: return None
        mx = sum(a for a, _ in p) / n; my = sum(b for _, b in p) / n
        cov = sum((a - mx) * (b - my) for a, b in p)
        vx = sum((a - mx) ** 2 for a, _ in p) ** .5; vy = sum((b - my) ** 2 for _, b in p) ** .5
        return cov / (vx * vy) if vx and vy else None

    cpair = [(r["ctl"], wko[r["date"]][0]) for r in rows[60:] if r["date"] in wko and wko[r["date"]][0] is not None]
    fpair = [(r["mftp_w"], wko[r["date"]][1]) for r in rows if r["date"] in wko and r["mftp_w"] and wko[r["date"]][1]]
    print(f"END-TO-END (warm, no WKO5):  CTL r={pear(cpair):.3f}  mFTP r={pear(fpair):.3f}")
