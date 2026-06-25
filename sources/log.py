"""Training-log month view — per-day ride cards (colored by dominant zone) + weekly TSS & Fitness
(CTL) actual-vs-plan. Built from the Strava cache + the live actual daily series + the plan. The
per-ride compute reuses the metrics engine so TSS/IF/zones match the dashboard exactly.
"""
from __future__ import annotations

import calendar
import datetime as dt

from .metrics import _ride_tss, _accumulate_tiz, _ftp_asof

_PR_WINDOWS = [("300", "5-min"), ("1200", "20-min")]


def _dominant(tiz):
    return (tiz.index(max(tiz)) + 1) if sum(tiz) else None      # 1-based zone, None if no power


def _pr_map(rides):
    """Per-ride: which of {5-min, 20-min} bests are a 90-day high (the ★ flag)."""
    out = {}
    for s in rides:
        d = dt.date.fromisoformat(s["date"])
        lo = (d - dt.timedelta(days=90)).isoformat()
        wins = []
        for key, label in _PR_WINDOWS:
            v = (s.get("mmp") or {}).get(key)
            if not v:
                continue
            best = max(((o.get("mmp") or {}).get(key) or 0)
                       for o in rides if lo <= o["date"] <= s["date"])
            if v >= best:
                wins.append(label)
        out[s["id"]] = wins
    return out


def ride_card(s, ftp, pr):
    tss, if_ = _ride_tss(s, ftp)
    tiz = [0, 0, 0, 0, 0, 0]
    _accumulate_tiz(tiz, s.get("phist"), ftp)
    hr = s.get("avg_hr")
    sport = s.get("sport") or "Ride"
    return {
        "id": s["id"], "name": s.get("name") or sport, "sport": sport,
        "indoor": "virtual" in sport.lower(),              # badge; route renders off `polyline`
        "duration_s": s["duration_s"], "distance_mi": s.get("distance_mi"), "elev_ft": s.get("elev_ft"),
        "tss": round(tss), "if": round(if_, 2), "np": round(s["np"]),
        "ef": round(s["np"] / hr, 2) if hr else None, "decoupling": s.get("decoupling"),
        "dominant_zone": _dominant(tiz), "tiz": tiz,
        "polyline": s.get("polyline"),
        "mmp": {k: (s.get("mmp") or {}).get(k) for k in ("5", "60", "300", "1200")},
        "pr": pr.get(s["id"], []),
    }


def build_month(summaries, daily_actual, plan, ftp, year, month):
    """daily_actual: {date: {'ctl':, 'tss_sum':}} (authoritative actuals). plan: the generated plan
    (or None). `ftp` may be a single float OR a dated history (list of {date, ftp}) — each ride is
    scored with the FTP in effect on its date. Returns calendar weeks (Mon-start) covering
    `year`-`month`, each with day cards + weekly TSS/CTL actual-vs-plan."""
    rides = [s for s in summaries if s.get("np")]
    hist = sorted(ftp, key=lambda e: e["date"]) if isinstance(ftp, list) else None
    ftp_for = (lambda d: _ftp_asof(hist, d, 200)) if hist else (lambda d: ftp or 200)
    pr = _pr_map(rides)
    by_date = {}
    for s in rides:
        by_date.setdefault(s["date"], []).append(s)
    plan_by_mon = {w["week_start"]: w for w in (plan or {}).get("weeks", [])}

    cal = calendar.Calendar(firstweekday=0)               # Monday
    weeks_out = []
    for week in cal.monthdatescalendar(year, month):       # list of 7 date objs, Mon..Sun
        days = []
        for d in week:
            iso = d.isoformat()
            cards = [ride_card(s, ftp_for(iso), pr) for s in by_date.get(iso, [])]
            tiz = [0, 0, 0, 0, 0, 0]
            for c in cards:
                for i in range(6):
                    tiz[i] += c["tiz"][i]
            day_act = daily_actual.get(iso, {})
            days.append({
                "date": iso, "dom": d.day, "in_month": d.month == month,
                "rides": cards, "tss": round(day_act.get("tss_sum") or sum(c["tss"] for c in cards)),
                "dominant_zone": _dominant(tiz), "is_rest": not cards,
            })
        mon = week[0].isoformat()
        # actual weekly TSS from authoritative daily; CTL = last in-data day of the week
        wk_dates = [x["date"] for x in days]
        tss_act = round(sum((daily_actual.get(x, {}).get("tss_sum") or 0) for x in wk_dates))
        ctls = [daily_actual[x]["ctl"] for x in wk_dates if x in daily_actual and daily_actual[x].get("ctl") is not None]
        pw = plan_by_mon.get(mon)
        weeks_out.append({
            "week_start": mon, "days": days,
            "tss_actual": tss_act, "tss_plan": pw["weekly_tss_target"] if pw else None,
            "ctl_actual": round(ctls[-1]) if ctls else None,
            "ctl_plan": round(pw["ctl_target"]) if pw and pw.get("ctl_target") else None,
        })
    return {"year": year, "month": month, "weeks": weeks_out}
