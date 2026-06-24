"""Pull ~6 months of rides from Strava and reduce each to a compact metric summary (NP + the
max-mean-power points), caching to .strava_summaries.json so re-runs are instant and a rate-limit
hiccup never loses progress. We DON'T keep raw streams — just the per-ride numbers the engine
needs. FTP is applied later (at compute time) so it can be tuned without re-pulling.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error

from .strava_client import list_activities, get_streams

CACHE = os.path.join(os.path.dirname(__file__), ".strava_summaries.json")
WINDOWS = [5, 60, 180, 300, 720, 1200]                    # seconds: 5s,1m,3m,5m,12m,20m
DAYS_BACK = 182


def _cumsum(xs):
    cs = [0.0]
    for x in xs:
        cs.append(cs[-1] + (x or 0))
    return cs


def normalized_power(watts):
    if len(watts) < 30:
        return None
    cs = _cumsum(watts)
    roll = [(cs[i + 30] - cs[i]) / 30 for i in range(len(watts) - 29)]
    return (sum(r ** 4 for r in roll) / len(roll)) ** 0.25


def mmp(watts, k):
    if len(watts) < k:
        return None
    cs = _cumsum(watts)
    return max((cs[i + k] - cs[i]) / k for i in range(len(watts) - k + 1))


def _r1(v):
    """Round to 1dp, but pass through None — mmp/NP return None for rides shorter than the window
    (or <30s), and that must stay None, not crash."""
    return round(v, 1) if v is not None else None


def summarize(act_summary, watts):
    np_ = normalized_power(watts) if watts else None
    return {
        "id": str(act_summary["id"]),
        "date": (act_summary.get("start_date_local") or act_summary["start_date"])[:10],
        "sport": act_summary.get("sport_type") or act_summary.get("type"),
        "duration_s": int(act_summary.get("moving_time") or act_summary.get("elapsed_time") or 0),
        "np": _r1(np_),
        "avg": act_summary.get("average_watts"),
        "mmp": {str(k): _r1(mmp(watts, k) if watts else None) for k in WINDOWS},
    }


def load_cache() -> dict:
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    return {}


def latest_cached_epoch(cache) -> int | None:
    if not cache:
        return None
    mx = max(s["date"] for s in cache.values())
    return int(dt.datetime.fromisoformat(mx + "T00:00:00").timestamp())


def pull(full=False, after=None, days_back=None) -> dict:
    """Fetch rides → compact summaries, cached + resumable. Default = INCREMENTAL (only rides newer
    than the latest cached day) — fast, the daily-button case. full=True (or empty cache) walks the
    whole history; that's many calls, so it's paced and resumes after a rate-limit. Returns a
    summary dict (never raises on 429 — sets rate_limited so the caller can say "click again")."""
    cache = load_cache()
    if after is None:
        if days_back is not None:
            after = int(time.time()) - days_back * 86400
        elif not full and cache:
            after = latest_cached_epoch(cache)            # incremental
        # else (full, or empty cache): after stays None -> all history
    page, fetched, skipped, rate_limited = 1, 0, 0, False
    try:
        while True:
            acts = list_activities(per_page=50, page=page, after=after)
            if not acts:
                break
            for a in acts:
                sid = str(a["id"])
                if sid in cache:
                    skipped += 1
                    continue
                try:
                    streams = get_streams(a["id"], keys=("time", "watts"))
                    watts = streams.get("watts") or []
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        raise                             # bubble to the outer handler
                    watts = []                            # non-rate-limit (e.g. no streams) → skip power
                cache[sid] = summarize(a, watts)
                fetched += 1
                with open(CACHE, "w") as f:               # persist after each ride (resumable)
                    json.dump(cache, f)
                time.sleep(0.3)                           # pace under 200 req / 15 min
            page += 1
    except urllib.error.HTTPError as e:
        if e.code != 429:
            raise
        rate_limited = True                               # stop gracefully; cache holds progress

    return {"fetched": fetched, "skipped": skipped, "total": len(cache),
            "rides_with_power": sum(1 for s in cache.values() if s.get("np")),
            "rate_limited": rate_limited,
            "date_min": min((s["date"] for s in cache.values()), default=None),
            "date_max": max((s["date"] for s in cache.values()), default=None)}


if __name__ == "__main__":
    import sys
    res = pull(full=("--full" in sys.argv))
    print(res)
