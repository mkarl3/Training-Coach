"""Pull ~6 months of rides from Strava and reduce each to a compact metric summary (NP + the
max-mean-power points), caching to .strava_summaries.json so re-runs are instant and a rate-limit
hiccup never loses progress. We DON'T keep raw streams — just the per-ride numbers the engine
needs. FTP is applied later (at compute time) so it can be tuned without re-pulling.
"""
from __future__ import annotations

import json
import os
import time

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


def summarize(act_summary, watts):
    return {
        "id": str(act_summary["id"]),
        "date": (act_summary.get("start_date_local") or act_summary["start_date"])[:10],
        "sport": act_summary.get("sport_type") or act_summary.get("type"),
        "duration_s": int(act_summary.get("moving_time") or act_summary.get("elapsed_time") or 0),
        "np": round(normalized_power(watts), 1) if watts else None,
        "avg": act_summary.get("average_watts"),
        "mmp": {str(k): (round(mmp(watts, k), 1) if watts else None) for k in WINDOWS},
    }


def load_cache() -> dict:
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            return json.load(f)
    return {}


def pull(days_back=DAYS_BACK):
    cache = load_cache()
    after = int(time.time()) - days_back * 86400
    page, fetched, skipped = 1, 0, 0
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
            except Exception as e:
                watts = []
                print(f"  (no streams for {sid}: {e})")
            cache[sid] = summarize(a, watts)
            fetched += 1
            with open(CACHE, "w") as f:                   # persist after each ride (resumable)
                json.dump(cache, f)
            time.sleep(0.25)                              # pace under 200 req / 15 min
        page += 1
    print(f"done: {fetched} new, {skipped} cached, {len(cache)} total in {CACHE}")
    rides = [s for s in cache.values() if (s.get("mmp") or {}).get('300')]
    print(f"rides with power: {sum(1 for s in cache.values() if s['np'])}; "
          f"date range: {min(s['date'] for s in cache.values())} .. {max(s['date'] for s in cache.values())}")


if __name__ == "__main__":
    pull()
