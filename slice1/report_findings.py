"""Run all detectors over the dataset and print a structured summary + the
action-ranked findings. Findings are DATA (the contract the coach will consume);
this script only formats them for inspection.

Usage: python report_findings.py
"""
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wko_metrics import metrics, detectors

DB = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\slice0\wko.db"


def main():
    conn = sqlite3.connect(DB)
    m = metrics.Metrics(conn)
    findings = detectors.run_all(m)
    conn.close()

    print("=" * 78)
    print(f"FINDINGS: {len(findings)} total over {m.daily.index.min().date()}..{m.daily.index.max().date()}")
    by = Counter((f["mode_id"], f["variant"], f["severity"]) for f in findings)
    print(f"\n  {'mode':14s} {'variant':14s} {'severity':10s} count")
    for (mode, var, sev), n in sorted(by.items()):
        print(f"  {mode:14s} {var:14s} {sev:10s} {n}")

    print("\n" + "=" * 78)
    print("CONFIRMED findings, action-ranked (priority 1=highest; NOT diagnosis rank):")
    conf = [f for f in findings if f["severity"] == "confirmed"]
    for f in detectors.action_rank(conf):
        fl = (" flags=" + ",".join(f["data_flags"])) if f["data_flags"] else ""
        print(f"  [P{f['priority']}] {f['mode_id']:13s} {f['variant']:13s} "
              f"{f['window_start']}..{f['window_end']} ({f['detector_family']}){fl}")

    print("\n" + "=" * 78)
    print("HONEST FRAMING: detectors are encoded against ONE athlete's episodes. Firing")
    print("here is correct encoding, NOT validation of the fingerprints. ACWR is noisy for")
    print("this athlete (frequent spike-clusters) — injury_spike flags load risk, not tissue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
