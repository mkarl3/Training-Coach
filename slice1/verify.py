"""Step-3 verification: module output vs independent hand/numpy recomputation.

Independent recomputations here deliberately AVOID calling wko_metrics functions —
they use raw SQL + numpy so the comparison is a real cross-check, not a tautology.
"""
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wko_metrics import DEFAULT, metrics  # noqa: E402

DB = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\slice0\wko.db"


def line(label, expected, got, unit=""):
    ok = (expected is None and got is None) or (
        expected is not None and got is not None and abs(expected - got) < 1e-6)
    print(f"  [{'OK ' if ok else 'XX '}] {label:40s} hand={expected!r:>12} module={got!r:>12} {unit}")
    return ok


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    m = metrics.Metrics(conn, DEFAULT)
    allok = True

    # ---- 1. Ramp rate @ 2025-03-15 (window 7) ----
    print("1) RAMP RATE @ 2025-03-15, window=7")
    ctl_now = cur.execute("SELECT ctl FROM daily WHERE date='2025-03-15'").fetchone()[0]
    ctl_prev = cur.execute("SELECT ctl FROM daily WHERE date='2025-03-08'").fetchone()[0]
    hand = (ctl_now - ctl_prev) * 7.0 / 7.0
    got = float(m.ramp_rate().loc["2025-03-15"])
    allok &= line("CTL ramp (pts/week)", hand, got)

    # ---- 2. Foster monotony & strain @ 2025-03-15 (window 7, ddof=0) ----
    print("2) FOSTER MONOTONY/STRAIN @ 2025-03-15, window=7, ddof=0")
    loads = np.array([r[0] for r in cur.execute(
        "SELECT tss_sum FROM daily WHERE date BETWEEN '2025-03-09' AND '2025-03-15' ORDER BY date")])
    mean, sd = loads.mean(), loads.std(ddof=0)
    hand_mono = mean / sd
    hand_strain = loads.sum() * hand_mono
    allok &= line("monotony", round(hand_mono, 6), round(float(m.monotony().loc["2025-03-15"]), 6))
    allok &= line("strain", round(hand_strain, 6), round(float(m.strain().loc["2025-03-15"]), 6))
    print(f"      (loads={loads.tolist()} mean={mean:.4f} sd={sd:.4f})")

    # ---- 3. ACWR (EWMA) @ 2025-03-15 ----
    print("3) ACWR EWMA @ 2025-03-15, acute=7 chronic=28")
    rows = cur.execute(
        "SELECT date, tss_sum FROM daily WHERE is_projected=0 ORDER BY date").fetchall()
    dates = [r[0] for r in rows]
    arr = np.array([r[1] for r in rows], dtype=float)
    idx = dates.index("2025-03-15")

    def ewma(a, span):
        al = 2.0 / (span + 1)
        out = np.empty_like(a)
        out[0] = a[0]
        for i in range(1, len(a)):
            out[i] = al * a[i] + (1 - al) * out[i - 1]
        return out

    ac = ewma(arr, 7)[idx]
    ch = ewma(arr, 28)[idx]
    hand_acwr = ac / ch
    mod = m.acwr().loc["2025-03-15"]
    allok &= line("acute EWMA", round(ac, 6), round(float(mod["acute"]), 6))
    allok &= line("chronic EWMA", round(ch, 6), round(float(mod["chronic"]), 6))
    allok &= line("acwr", round(hand_acwr, 6), round(float(mod["acwr"]), 6))

    # ---- 4. TSB trajectory @ 2025-03-15 (window 14) ----
    print("4) TSB TRAJECTORY @ 2025-03-15, window=14")
    tsb = np.array([r[0] for r in cur.execute(
        "SELECT tsb FROM daily WHERE date BETWEEN '2025-03-02' AND '2025-03-15' ORDER BY date")], dtype=float)
    x = np.arange(len(tsb))
    hand_slope = np.polyfit(x, tsb, 1)[0]
    traj = m.tsb_trajectory().loc["2025-03-15"]
    allok &= line("tsb slope (pts/day)", round(hand_slope, 6), round(float(traj["tsb_slope"]), 6))
    print(f"      direction (module) = {traj['tsb_direction']!r}  (slope>{DEFAULT.tsb_flat_eps} => rising)")

    # ---- 5. Aerobic decoupling @ 2023-08-05 long ride ----
    print("5) AEROBIC DECOUPLING @ 2023-08-05 (dur 10577s >= 9000s)")
    raw = cur.execute(
        "SELECT pwhr_pct FROM workout WHERE started_at='2023-08-05T06:17:00'").fetchone()[0]
    dec = m.decoupling()
    rowd = dec[dec["started_at"] == "2023-08-05T06:17:00"].iloc[0]
    allok &= line("decoupling % (= WKO pwHr)", round(raw, 6), round(float(rowd["decoupling_pct"]), 6))
    print(f"      sufficient={rowd['sufficient']} decoupled={rowd['decoupled']} (>{DEFAULT.decoupling_high_pct}%)")

    # ---- 6. Power-duration ratio @ 2023-04-29 ----
    print("6) POWER-DURATION 1h/2h @ 2023-04-29")
    p1, p2 = cur.execute(
        "SELECT p1hr_w, p2hr_w FROM workout WHERE date='2023-04-29' AND p2hr_w IS NOT NULL").fetchone()
    pd_ = m.power_duration()
    rowp = pd_[(pd_["date"] == "2023-04-29") & (pd_["p2hr_w"] == p2)].iloc[0]
    allok &= line("1h/2h ratio", round(p1 / p2, 6), round(float(rowp["pd_ratio_1h_2h"]), 6))
    allok &= line("1h-2h gap (W)", float(p1 - p2), float(rowp["pd_gap_1h_2h_w"]))

    # ---- 7. TiZ power-zone share @ 2025-03-15 (28-day rolling) ----
    print("7) TIZ POWER-ZONE SHARE @ 2025-03-15, window=28")
    zsum = cur.execute(
        "SELECT " + ",".join(f"COALESCE(SUM(COALESCE(tiz_pwr_z{i}_sec,0)),0)" for i in range(1, 7)) +
        " FROM daily WHERE date BETWEEN '2025-02-16' AND '2025-03-15'").fetchone()
    total = sum(zsum)
    hand_z1 = zsum[0] / total
    dist = m.tiz_power_distribution().loc["2025-03-15"]
    allok &= line("Z1 share", round(hand_z1, 6), round(float(dist["tiz_pwr_z1_share"]), 6))
    allok &= line("shares sum to 1.0", 1.0, round(float(dist.sum()), 6))
    print(f"      zone seconds (28d) = {list(zsum)} total={total}")

    conn.close()
    print("\nRESULT:", "ALL MATCH" if allok else "MISMATCH — see XX lines")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
