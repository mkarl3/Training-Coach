"""Stage 2 — write a wko.db-shaped SQLite from Strava-computed metrics, so the app's Metrics facade
reads it UNCHANGED. Reuses slice0's canonical schema.sql (every column exists; the ones we don't
compute yet are simply NULL). The cache (.strava_summaries.json) is the source of truth; this DB is
derived and fully rebuilt each time — idempotent.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

from .metrics import build_daily, build_workouts

HERE = os.path.dirname(__file__)
SCHEMA = os.path.join(HERE, "..", "slice0", "wko_ingest", "schema.sql")
CACHE = os.path.join(HERE, ".strava_summaries.json")
DEFAULT_OUT = os.path.join(HERE, "strava_wko.db")


def _insert(conn, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    ph = ",".join("?" * len(cols))
    conn.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
                     [[r.get(c) for c in cols] for r in rows])


def _config_ftp() -> float | None:
    """The athlete's set threshold FTP for TSS (WKO5 'bikeFTP'), from strava_config.txt FTP=…
    Distinct from the modeled CP used by the gates. None → fall back to CP (runs hot)."""
    from .strava_auth import _read_config
    v = _read_config().get("FTP")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def build_db(summaries: list[dict], out_path: str = DEFAULT_OUT, load_ftp: float | None = None) -> dict:
    if load_ftp is None:
        load_ftp = _config_ftp()
    daily = build_daily(summaries, load_ftp=load_ftp)
    workouts = build_workouts(summaries, load_ftp=load_ftp)
    if not daily:
        raise RuntimeError("no rides with power in the cache — nothing to build")

    tmp = out_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = sqlite3.connect(tmp)
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    _insert(conn, "daily", daily)
    _insert(conn, "workout", workouts)
    now = dt.datetime.now().replace(microsecond=0).isoformat()
    conn.execute("INSERT INTO ingest_meta (source_file,sheet,family,role,rows_read,rows_loaded,"
                 "rows_rejected,date_min,date_max,loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("strava", "activities", "TH", "loaded", len(workouts), len(workouts), 0,
                  daily[0]["date"], daily[-1]["date"], now))
    conn.commit()
    conn.close()
    os.replace(tmp, out_path)                        # atomic swap
    return {"path": out_path, "daily_rows": len(daily), "workouts": len(workouts),
            "date_min": daily[0]["date"], "date_max": daily[-1]["date"], "load_ftp": load_ftp}


if __name__ == "__main__":
    summ = list(json.load(open(CACHE)).values())
    info = build_db(summ)
    print("built:", info)
    # Stage-2 verify: can the app's Metrics facade read it unchanged?
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "slice1"))
    from wko_metrics import metrics as M, DEFAULT_PROFILE          # noqa: E402
    conn = sqlite3.connect(info["path"])
    m = M.Metrics(conn, profile=DEFAULT_PROFILE)
    as_of = m.daily.index.max()
    print("facade loaded OK.")
    print("  daily rows:", len(m.daily), "| workouts:", len(m.workouts))
    print("  CTL now:", round(float(m.ctl.iloc[-1]), 1),
          "| ATL:", round(float(m.atl.iloc[-1]), 1),
          "| TSB:", round(float(m.tsb.iloc[-1]), 1))
    print("  weekly TSS (last 3):", [round(x) for x in m.weekly_tss().dropna().tail(3).tolist()])
    print("  mFTP now:", float(m.mftp.dropna().iloc[-1]) if not m.mftp.dropna().empty else None)
    try:
        print("  personal_ctl_floor_asof:", round(float(m.personal_ctl_floor_asof(as_of)), 1))
    except Exception as e:
        print("  ctl_floor:", repr(e))
