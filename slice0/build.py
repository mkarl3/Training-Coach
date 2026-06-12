"""Slice-0 entry point: build the SQLite dataset, validate it, print the reports.

Usage:
    python build.py [exports_dir] [db_path]
"""
import datetime
import os
import sqlite3
import sys

from wko_ingest import loader, validator

DEFAULT_EXPORTS = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\WKO5 Exports"
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wko.db")


def main():
    exports = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXPORTS
    db = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DB
    now = datetime.datetime.now().replace(microsecond=0).isoformat()

    summary = loader.build_database(db, exports, loaded_at=now)
    print("=" * 78)
    print("BUILD")
    print(f"  files parsed : {summary['files']}")
    print(f"  workouts     : {summary['workouts']}")
    print(f"  daily rows   : {summary['daily_rows']}")
    print(f"  date range   : {summary['date_min']} .. {summary['date_max']}")
    print(f"  ride horizon : {summary['horizon']}  (days after this = is_projected)")
    if summary["pmc_conflicts"]:
        print(f"  PMC wellness conflicts: {len(summary['pmc_conflicts'])} (kept first non-null)")

    report = validator.run(db, exports)

    print("=" * 78)
    print("ROUND-TRIP CHECKS")
    for name, ok, detail in report["round_trip"]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:34s} {detail}")

    print("=" * 78)
    print("CROSS-CHECK vs Week-of-5/25 snapshot")
    fid = report["cross_check_fidelity"]
    rec = report["cross_check_reconcile"]
    fid_fail = [c for c in fid if not c[1]]
    print(f"  parse-fidelity : {len(fid) - len(fid_fail)}/{len(fid)} matched")
    for name, ok, detail, _ in fid_fail:
        print(f"    [FAIL] {name}  {detail}")
    rec_div = [c for c in rec if not c[1]]
    if rec:
        print(f"  reconciliation : {len(rec) - len(rec_div)}/{len(rec)} agree; "
              f"{len(rec_div)} cross-source divergence(s) on volatile recent acute-load (expected):")
        for name, ok, detail, _ in rec_div:
            print(f"    [note] {name}  {detail}  (yearly file authoritative; weekly snapshot stale)")

    print("=" * 78)
    print("INGEST_META")
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        print(f"  {'source_file':46s} {'sheet':16s} {'fam':5s} {'role':16s} {'read':>5s} {'load':>5s}  range")
        for r in cur.execute(
            "SELECT source_file, sheet, family, role, rows_read, rows_loaded, date_min, date_max "
            "FROM ingest_meta ORDER BY family, source_file"
        ):
            sf, sh, fam, role, rr, rl, dn, dx = r
            print(f"  {sf:46s} {sh:16s} {fam:5s} {role:16s} {rr:5d} {rl:5d}  {dn}..{dx}")

        print("=" * 78)
        print("DATA_FLAGS raised")
        flagged = list(cur.execute(
            "SELECT date, data_flags FROM daily WHERE data_flags IS NOT NULL ORDER BY date"))
        if not flagged:
            print("  (none)")
        else:
            from collections import Counter
            tally = Counter()
            for d, fl in flagged:
                for token in fl.split(";"):
                    tally[token] += 1
            print(f"  {len(flagged)} day(s) flagged. Breakdown:")
            for token, c in tally.most_common():
                print(f"    {token:24s} {c}")
            print("  Days:")
            for d, fl in flagged:
                print(f"    {d}  {fl}")
    finally:
        conn.close()

    ok = report["round_trip_ok"] and report["cross_check_ok"]
    print("=" * 78)
    print("RESULT:", "OK" if ok else "ISSUES FOUND (see FAIL lines above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
