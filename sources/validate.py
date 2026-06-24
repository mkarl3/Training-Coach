"""Go/no-go gate: do metrics computed from Strava streams REPLICATE WKO5's trends?

Three tests over the ~6mo overlap:
  1. TSS math  — computed daily TSS (using WKO5's own mFTP as the FTP) vs wko.db tss_sum.
                 Isolates "is the NP/TSS engine correct?" from "is the FTP estimate correct?"
  2. CTL trend — CTL built from computed TSS (seeded at WKO5's CTL on day 1) vs wko.db ctl.
  3. CP/FTP    — a rolling Critical-Power estimate from the PD points vs wko.db mFTP (the modeled
                 metric we're replacing — the riskiest piece). Trend correlation, not value match.
Renders an overlay chart (computed vs WKO5 CTL) to Documents/strava_vs_wko_ctl.png.
"""
from __future__ import annotations

import json
import os
import sqlite3
import datetime as dt

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(__file__)
DB = os.path.join(HERE, "..", "slice0", "wko.db")
SUMM = os.path.join(HERE, ".strava_summaries.json")


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (vx * vy) if vx and vy else None


def daterange(a, b):
    d = dt.date.fromisoformat(a)
    end = dt.date.fromisoformat(b)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


# ---- load WKO5 truth ----
db = sqlite3.connect(DB)
wko = {r[0]: {"tss": r[1], "ctl": r[2], "mftp": r[3]}
       for r in db.execute("SELECT date,tss_sum,ctl,mftp_w FROM daily WHERE is_projected=0")}
wko_dates = sorted(wko)

# ---- load Strava-derived ride summaries ----
summ = list(json.load(open(SUMM)).values())
summ = [s for s in summ if s["np"]]
by_date = {}
for s in summ:
    by_date.setdefault(s["date"], []).append(s)

start = max(min(by_date), wko_dates[0])
end = min(max(by_date), wko_dates[-1])
dates = [d for d in daterange(start, end)]

# forward-filled WKO mFTP (the FTP to use for the TSS-math test)
ftp_at, last = {}, None
for d in daterange(wko_dates[0], end):
    if wko.get(d, {}).get("mftp"):
        last = wko[d]["mftp"]
    ftp_at[d] = last

# ---- 1. computed daily TSS (NP-based, WKO mFTP as FTP) ----
comp_tss = {}
for d in dates:
    tot = 0.0
    for s in by_date.get(d, []):
        ftp = ftp_at.get(d) or 180
        if_ = s["np"] / ftp
        tot += (s["duration_s"] / 3600) * if_ ** 2 * 100
    comp_tss[d] = tot

tss_pairs = [(comp_tss[d], wko[d]["tss"]) for d in dates
             if wko.get(d, {}).get("tss") is not None and comp_tss[d] > 0]
r_tss = pearson([a for a, _ in tss_pairs], [b for _, b in tss_pairs])

# ---- 2. CTL from computed TSS, seeded at WKO CTL on day 1 ----
ctl = wko.get(start, {}).get("ctl") or 0.0
comp_ctl = {}
for d in dates:
    ctl += (comp_tss[d] - ctl) / 42.0
    comp_ctl[d] = ctl
ctl_pairs = [(comp_ctl[d], wko[d]["ctl"]) for d in dates if wko.get(d, {}).get("ctl") is not None]
r_ctl = pearson([a for a, _ in ctl_pairs], [b for _, b in ctl_pairs])

# ---- 3. rolling Critical Power (3min & 12min bests, trailing 90d) vs WKO mFTP ----
def rolling_best(win_key, days, d):
    lo = (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()
    vals = [s["mmp"][win_key] for ds in by_date for s in by_date[ds]
            if lo <= ds <= d and s["mmp"].get(win_key)]
    return max(vals) if vals else None

cp_pairs = []
for d in dates:
    p180, p720 = rolling_best("180", 90, d), rolling_best("720", 90, d)
    if p180 and p720 and p720 < p180:
        cp = (p720 * 720 - p180 * 180) / (720 - 180)
        if wko.get(d, {}).get("mftp"):
            cp_pairs.append((cp, wko[d]["mftp"]))
r_cp = pearson([a for a, _ in cp_pairs], [b for _, b in cp_pairs])
cp_now = cp_pairs[-1][0] if cp_pairs else None

print(f"overlap: {start} .. {end}  ({len(dates)} days, {len(summ)} rides w/ power)")
print(f"1. TSS math   r = {r_tss:.3f}  (n={len(tss_pairs)} ride-days)" if r_tss else "1. TSS: n/a")
print(f"2. CTL trend  r = {r_ctl:.3f}  (n={len(ctl_pairs)} days)" if r_ctl else "2. CTL: n/a")
if r_cp:
    print(f"3. CP vs mFTP r = {r_cp:.3f}  (n={len(cp_pairs)} days)  "
          f"CP_now ~{cp_now:.0f}W vs WKO mFTP {wko[end].get('mftp')}W")
else:
    print("3. CP vs mFTP: not enough rolling 3/12-min bests")

# ---- overlay chart: computed vs WKO CTL ----
W, H, pad = 1000, 420, 50
img = Image.new("RGB", (W, H), "#0b0b14"); d_ = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype(os.path.join(HERE, "assets", "PressStart2P.ttf"), 14)
    fs = ImageFont.truetype(os.path.join(HERE, "assets", "PressStart2P.ttf"), 10)
except Exception:
    f = fs = ImageFont.load_default()
ys = [wko[d]["ctl"] for d in dates if wko.get(d, {}).get("ctl") is not None] + list(comp_ctl.values())
ymin, ymax = min(ys), max(ys) + 2
def X(i): return pad + i * (W - 2 * pad) / max(1, len(dates) - 1)
def Y(v): return H - pad - (v - ymin) * (H - 2 * pad) / (ymax - ymin)
# WKO line (cream), computed (gold)
for series, col in [([wko.get(d, {}).get("ctl") for d in dates], "#f4f4f0"),
                    ([comp_ctl[d] for d in dates], "#f7d51d")]:
    pts = [(X(i), Y(v)) for i, v in enumerate(series) if v is not None]
    if len(pts) > 1:
        d_.line(pts, fill=col, width=3)
d_.text((pad, 14), "FITNESS (CTL): WKO5 vs Strava-computed", font=f, fill="#f4f4f0")
d_.text((pad, 36), f"WKO5 (cream)   Strava-computed (gold)   r={r_ctl:.3f}", font=fs, fill="#9fb0d8")
OUT = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "strava_vs_wko_ctl.png")
img.save(OUT)
print("chart:", OUT)
