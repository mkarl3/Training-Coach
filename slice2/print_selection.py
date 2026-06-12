"""Checkpoint demo: what the watchman would surface on a given 'today'.

Usage: python print_selection.py [YYYY-MM-DD ...]
"""
import os
import sqlite3
import sys

SLICE2 = os.path.dirname(os.path.abspath(__file__))
SLICE1 = os.path.join(os.path.dirname(SLICE2), "slice1")
sys.path.insert(0, SLICE2)
sys.path.insert(0, SLICE1)

from wko_metrics import metrics, detectors          # noqa: E402
from watchman import select                          # noqa: E402

DB = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\slice0\wko.db"
DEFAULT_DATES = ["2026-03-25", "2025-07-10", "2026-05-29"]


def show(state):
    print("=" * 74)
    print(f"TODAY = {state['as_of']}    BOARD: {state['status'].upper()}")
    d = state["direction"]
    print("  direction (trailing 28d): " + "  ".join(
        f"{k.upper()} {d[k]['now']} ({d[k]['dir']} {d[k]['change']:+})" for k in ("ctl", "atl", "tsb") if d[k]))
    trips = state["tripwires"]
    anns = state["trend_annotations"]
    print(f"  WATCH OUT FOR — {len(trips)} acute alert(s), {len(anns)} trend zone(s):")
    if not trips and not anns:
        print("    — nothing active (green is a valid, common state) —")
    for f in trips:
        tag = " [PROVISIONAL]" if f["provisional"] else ""
        fl = (" flags=" + ",".join(f["data_flags"])) if f["data_flags"] else ""
        print(f"    [tripwire] {f['mode_id']:13s} {f['severity']}{tag} on {f['window_start']}..{f['window_end']}{fl}")
        print(f"               evidence={f['evidence']}")
    for a in anns:
        tag = " [PROVISIONAL]" if a["provisional"] else ""
        fl = (" flags=" + ",".join(a["data_flags"])) if a["data_flags"] else ""
        print(f"    [trend zone] {a['mode_id']:13s}{tag} {a['zone_start']}..{a['zone_end']}{fl}")
        print(f"               evidence={a['evidence']}")
    if state["watch_rollup"]:
        print("  watch-tier (collapsed, not alerts): " +
              ", ".join(f"{w['mode_id']}×{w['count']} (latest {w['latest']})" for w in state["watch_rollup"]))
    g = state["gauge"]
    if g:
        for leg, v in g["legs"].items():
            metric = (f"decoupling={v['decoupling_pct']}%" if v["decoupling_pct"] is not None
                      else f"1h-2h gap={v['gap_1h_2h_w']}W")
            print(f"  DURABILITY GAUGE [{leg}]: {metric} ({v['severity']}, last {v['last_assessed']})")
    print(f"  trajectory points: {len(state['trajectory'])} "
          f"(last {sum(p['provisional'] for p in state['trajectory'])} provisional)")


def main():
    dates = sys.argv[1:] or DEFAULT_DATES
    conn = sqlite3.connect(DB)
    m = metrics.Metrics(conn)
    findings = detectors.run_all(m)
    conn.close()
    print(f"Full findings set: {len(findings)} (the watchman selects from these)\n")
    for d in dates:
        show(select(findings, d, m))
    print("=" * 74)


if __name__ == "__main__":
    main()
