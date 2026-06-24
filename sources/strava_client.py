"""Strava connector — list activities and pull per-second power/HR streams, mapped into the
source-agnostic Activity model. stdlib only (urllib).

This is connector #1. The rest of the system consumes Activity, never this module's JSON, so a
.fit / Garmin / intervals.icu connector later just produces the same Activity objects.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from .model import Activity
from .strava_auth import get_access_token

API = "https://www.strava.com/api/v3"


def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {get_access_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_activities(per_page: int = 30, page: int = 1, after: int | None = None) -> list[dict]:
    """Summary objects, newest first. `after` = unix seconds to only fetch newer activities."""
    params = {"per_page": per_page, "page": page}
    if after:
        params["after"] = after
    return _get("/athlete/activities", params)


def get_streams(activity_id: int,
                keys=("time", "watts", "heartrate", "cadence")) -> dict[str, list]:
    """Per-second streams for one activity, as {key: [values]} aligned by index."""
    raw = _get(f"/activities/{activity_id}/streams",
               {"keys": ",".join(keys), "key_by_type": "true"})
    return {k: v["data"] for k, v in raw.items() if isinstance(v, dict) and "data" in v}


def to_activity(summary: dict, with_streams: bool = True) -> Activity:
    """Map a Strava summary (+ optional streams) into the source-agnostic Activity."""
    streams = {}
    if with_streams:
        try:
            streams = get_streams(summary["id"])
        except Exception:
            streams = {}                                  # no power meter / streams unavailable
    return Activity(
        source="strava", source_id=str(summary["id"]),
        start=summary.get("start_date_local") or summary.get("start_date"),
        sport=summary.get("sport_type") or summary.get("type") or "Ride",
        duration_s=int(summary.get("elapsed_time") or summary.get("moving_time") or 0),
        elapsed=True,
        distance_m=summary.get("distance"),
        avg_power_w=summary.get("average_watts"),
        device_watts=summary.get("device_watts"),
        streams=streams,
    )


def fetch_recent(n: int = 10, with_streams: bool = True) -> list[Activity]:
    """The most recent n activities as Activity objects (rate-limit friendly: one streams call each)."""
    out = []
    for s in list_activities(per_page=n):
        out.append(to_activity(s, with_streams=with_streams))
        if with_streams:
            time.sleep(0.2)                               # gentle on the 200-req/15-min limit
    return out


if __name__ == "__main__":                                # smoke test once authorized
    acts = fetch_recent(5, with_streams=True)
    for a in acts:
        w = a.streams.get("watts") or []
        print(a, "| avg_reported=", a.avg_power_w,
              "| watts samples=", len(w),
              "| first 5w=", w[:5])
