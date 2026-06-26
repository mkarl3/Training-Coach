"""Pull rides from Strava and reduce each to a compact metric summary (NP + a full max-mean-power
curve + fatigued-state points), caching to .strava_summaries.json so re-runs are instant and a
rate-limit hiccup never loses progress.

We ALSO keep the raw per-second streams (per-ride files under .strava_streams/) so any future metric
— a different MMP duration, climbing power, a new durability cut — can be derived offline WITHOUT
re-pulling from Strava. The summary cache stays lean for runtime; the streams are read only when
(re)deriving features. FTP is applied later (at compute time) so it can be tuned without re-pulling.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error

from .strava_client import get_athlete_zones, get_streams, list_activities

HERE = os.path.dirname(__file__)
CACHE = os.path.join(HERE, ".strava_summaries.json")
STREAMS_DIR = os.path.join(HERE, ".strava_streams")        # raw per-ride streams (re-derivation source)
ZONES_CACHE = os.path.join(HERE, ".strava_zones.json")     # athlete HR/power zones (LTHR-equivalent)

# A full power-duration curve (seconds). The legacy 6 (5,60,180,300,720,1200) stay a SUBSET so the
# current metrics engine keeps finding its keys; the rest fill in the short + long ends for a real
# PD-model fit (TTE/stamina live past 20 min).
WINDOWS = [1, 5, 15, 30, 60, 120, 180, 300, 600, 720, 900, 1200, 1800, 2700, 3600, 5400, 7200]
# Durability: best power for these durations AFTER this much work — "5-min power after 2000 kJ".
FATIGUE_KJ = [1000, 2000, 3000]
FATIGUE_DURS = [60, 300, 1200]
# Streams we fetch (one call, any subset returned): power + the context that unlocks future metrics.
STREAM_KEYS = ("time", "watts", "heartrate", "cadence", "altitude",
               "velocity_smooth", "grade_smooth", "temp", "moving")
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


def fatigued_mmp(watts, kj, k):
    """Best k-second mean-max power in the part of the ride AFTER `kj` kJ of work has been done —
    the durability read (how the engine holds up deep into a ride). None if the ride never reaches
    that work or has too little left afterward. Assumes ~1 Hz (watt-seconds = joules)."""
    if not watts or len(watts) < k:
        return None
    cs = _cumsum(watts)
    target = kj * 1000.0
    start = next((i for i in range(len(cs)) if cs[i] >= target), None)
    if start is None or len(watts) - start < k:
        return None
    return mmp(watts[start:], k)


def _fatigued_block(watts):
    out = {}
    for kj in FATIGUE_KJ:
        pts = {str(k): _r1(fatigued_mmp(watts, kj, k)) for k in FATIGUE_DURS}
        pts = {k: v for k, v in pts.items() if v is not None}
        if pts:
            out[str(kj)] = pts
    return out


def power_histogram(watts, bin_w=10):
    """Seconds spent in each 10 W bucket (assumes ~1 Hz). Compact + FTP-agnostic: TiZ zones are
    recomputed from this at build time, so changing FTP re-buckets correctly."""
    h = {}
    for w in watts:
        if w is None:
            continue
        b = int(w // bin_w) * bin_w
        h[b] = h.get(b, 0) + 1
    return {str(k): v for k, v in h.items()}


def decoupling(watts, hr, min_sec=2400):
    """Aerobic (Pw:HR) decoupling % — first-half vs second-half power:HR efficiency. Standard long-
    ride durability read; None for rides under ~40 min or missing HR. Positive = HR drifted up
    relative to power (cardiac drift / lost durability)."""
    n = min(len(watts), len(hr))
    if n < min_sec:
        return None
    half = n // 2

    def ef(ws, hs):
        pw = [w for w in ws if w is not None]
        hh = [h for h in hs if h]
        if not pw or not hh:
            return None
        return (sum(pw) / len(pw)) / (sum(hh) / len(hh))
    e1, e2 = ef(watts[:half], hr[:half]), ef(watts[half:n], hr[half:n])
    if not e1 or not e2:
        return None
    return round((e1 - e2) / e1 * 100, 1)               # +% = efficiency dropped in 2nd half


def _r1(v):
    """Round to 1dp, pass through None — mmp/NP return None for rides shorter than the window."""
    return round(v, 1) if v is not None else None


def _avg(xs, drop_zero=False):
    vals = [x for x in xs if x is not None and (x > 0 if drop_zero else True)]
    return round(sum(vals) / len(vals), 1) if vals else None


def _label(act_summary):
    """Identity fields for the training-log cell — all from the activity summary (no stream cost)."""
    m = act_summary.get("map") or {}
    dist = act_summary.get("distance")
    elev = act_summary.get("total_elevation_gain")
    return {
        "name": act_summary.get("name"),
        "start": act_summary.get("start_date_local") or act_summary.get("start_date"),
        "polyline": m.get("summary_polyline") or None,         # encoded route; None for indoor
        "distance_mi": round(dist / 1609.34, 1) if dist else None,
        "elev_ft": round(elev * 3.28084) if elev else None,
    }


def summarize(act_summary, streams):
    """Reduce one activity + its streams to the compact per-ride record the engine consumes. Keeps
    the full MMP curve + fatigued-state points (for the PD fit & durability) and the context fields
    (cadence/temp/max-HR/device flag). `streams` is the dict from get_streams."""
    watts = streams.get("watts") or []
    hr = streams.get("heartrate") or []
    cad = streams.get("cadence") or []
    temp = streams.get("temp") or []
    np_ = normalized_power(watts) if watts else None
    return {
        "id": str(act_summary["id"]),
        "date": (act_summary.get("start_date_local") or act_summary["start_date"])[:10],
        "sport": act_summary.get("sport_type") or act_summary.get("type"),
        "duration_s": int(act_summary.get("moving_time") or act_summary.get("elapsed_time") or 0),
        "np": _r1(np_),
        "avg": act_summary.get("average_watts"),
        "avg_hr": act_summary.get("average_heartrate"),       # for EF (= NP / avg HR)
        "max_hr": max((h for h in hr if h), default=None) if hr else None,
        "avg_cadence": _avg(cad, drop_zero=True),             # ignore coasting (cadence 0)
        "avg_temp": _avg(temp),
        "device_watts": act_summary.get("device_watts"),      # False = Strava-ESTIMATED power (low quality)
        "decoupling": decoupling(watts, hr) if (watts and hr) else None,
        "mmp": {str(k): v for k in WINDOWS if (v := _r1(mmp(watts, k) if watts else None)) is not None},
        "fatigued": _fatigued_block(watts) if watts else {},   # durability: power after N kJ
        "phist": power_histogram(watts) if watts else {},      # → power-zone TiZ at build time
        **_label(act_summary),                                 # name / route / distance / elevation
    }


def save_streams(sid, streams):
    """Persist one ride's raw streams so future metrics can be derived without re-pulling Strava."""
    if not streams:
        return
    os.makedirs(STREAMS_DIR, exist_ok=True)
    with open(os.path.join(STREAMS_DIR, f"{sid}.json"), "w") as f:
        json.dump(streams, f)


def load_streams(sid):
    p = os.path.join(STREAMS_DIR, f"{sid}.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def fetch_zones():
    """Grab + cache the athlete's HR/power zones (one call). LTHR-equivalent for HR-zone TiZ later."""
    z = get_athlete_zones()
    if z:
        with open(ZONES_CACHE, "w") as f:
            json.dump(z, f)
    return z


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


def enrich_labels() -> dict:
    """Backfill name/polyline/distance/elev onto cached rides that predate those fields. These live
    in the activity SUMMARY (not streams), so this only re-lists — cheap, no per-ride stream calls."""
    cache = load_cache()
    need = {sid for sid, s in cache.items() if "name" not in s}
    if not need:
        return {"patched": 0, "total": len(cache)}
    patched, page = 0, 1
    while need:
        acts = list_activities(per_page=100, page=page)
        if not acts:
            break
        for a in acts:
            sid = str(a["id"])
            if sid in need:
                cache[sid].update(_label(a))
                need.discard(sid)
                patched += 1
        page += 1
    with open(CACHE, "w") as f:
        json.dump(cache, f)
    return {"patched": patched, "total": len(cache)}


def pull(full=False, after=None, days_back=None, refetch=False) -> dict:
    """Fetch rides → compact summaries (+ raw streams on disk), cached + resumable. Default =
    INCREMENTAL (only rides newer than the latest cached day). full=True walks all history.
    refetch=True re-fetches rides already in the cache too — used for the one-time enrichment
    re-pull. Never raises on 429: sets rate_limited so the caller can say "click again"."""
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
                if sid in cache and (not refetch or "fatigued" in cache[sid]):
                    skipped += 1                          # already present (refetch: already enriched)
                    continue
                try:
                    streams = get_streams(a["id"], keys=STREAM_KEYS)
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        raise                             # bubble to the outer handler
                    streams = {}                          # non-rate-limit (e.g. no streams) → skip power
                save_streams(sid, streams)                # keep raw streams for future re-derivation
                cache[sid] = summarize(a, streams)
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


def resync() -> dict:
    """One-time enrichment re-pull: re-fetch every ride's streams (full key set), store them raw, and
    rebuild every summary with the full MMP curve + fatigued points. Rate-limit-aware + resumable
    (a 429 stops cleanly; re-run continues — already-enriched rides still get refetched, so it picks
    up wherever the cache left off only if you guard externally; intended to be run to completion)."""
    z = fetch_zones()
    res = pull(full=True, refetch=True)
    res["zones"] = bool(z)
    return res


if __name__ == "__main__":
    import sys
    if "--resync" in sys.argv:
        print(resync())
    else:
        print(pull(full=("--full" in sys.argv)))
