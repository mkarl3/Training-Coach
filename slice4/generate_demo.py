"""Checkpoint-2 demo: generate this athlete's plan skeleton as PLAIN DATA, with the rule
and any failure-mode cap behind each week. No UI, no coach — the bare, traceable structure.
"""
import datetime as dt
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # slice4
sys.path.insert(0, os.path.join(ROOT, "slice1"))

from wko_metrics import metrics, DEFAULT_PROFILE                  # noqa: E402
from plan import generator                                   # noqa: E402
import dataclasses                                                # noqa: E402

DB = os.path.join(ROOT, "slice0", "wko.db")
m = metrics.Metrics(sqlite3.connect(DB))
as_of = m.daily.index.max().strftime("%Y-%m-%d")

# Sample season: time-crunched masters athlete, A-race = a hilly gran fondo ~16 wks out, with
# the season starting 4 wks BEFORE the data date so a few weeks show planned-vs-actual.
# (birth_year set here only for the demo — shows the masters recovery rule firing; the real
#  profile is untouched.)
profile = dataclasses.replace(DEFAULT_PROFILE, birth_year=1980)
start = (dt.date.fromisoformat(as_of) - dt.timedelta(weeks=4)).isoformat()
a_date = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=16)).isoformat()
season = {"start_date": start, "weekly_hours_budget": 7.0}
events = [{"name": "Gran Fondo (hilly)", "event_date": a_date, "priority": "A",
           "event_type": "gran_fondo"}]
unavailable = [{"start_date": (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=6)).isoformat(),
                "end_date": (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=6, days=6)).isoformat(),
                "reason": "work travel"}]

plan = generator.generate_plan(m, profile, season, events, unavailable, as_of)
M = plan["meta"]
print("=" * 104)
print(f"A-RACE: {M['a_race']['name']}  {M['a_race']['date']}  type={M['a_race']['type']}  "
      f"emphasis={M['a_race']['emphasis']}")
print(f"plan {M['plan_start']} .. race over {M['weeks']} wks (weeks start {M['week_starts_on']}) | "
      f"start CTL {M['anchor_ctl']} -> target {M['target_peak_ctl']} (floor {M['personal_floor']})")
print(f"masters={M['masters']} | ramp cap {M['ramp_cap']}/wk | budget {M['weekly_hours_budget']} h/wk "
      f"| families {M['family_weeks']}")
print(f"ramp targets: base {M['base_ramp']} / build {M['build_ramp']} CTL/wk "
      f"({'demonstrated sustainable ramp ' + str(M['sustainable_ramp']) + '/wk' if M['ramp_source']=='history' else 'method default'})")
print(f"blocks {M['block_weeks']}")
print(f"target reached? {M['target_reached']}  (peak achieved CTL {M['peak_ctl_achieved']} "
      f"vs target {M['target_peak_ctl']})")
print(f"distribution Rx: {M['distribution_rx']}")
mg = M['monotony_guard']
print(f"monotony guardrail: {'ACTIVE' if mg['prone'] else 'inactive'} "
      f"(gray-band {mg['gray_band_frac']}/{mg['gray_band_cap']}, "
      f"TiZ conc {mg['tiz_concentration']}/{mg['tiz_concentration_cap']})")
print("=" * 104)
print(f"{'wk':>2} {'week of':10} {'block':8} {'CTL':>11} {'ramp':>5} {'pTSS':>4} {'aTSS':>4} "
      f"{'cap':>4} {'hrs':>4} {'FT':>2}  rule / caps fired")
print("-" * 104)
for w in plan["weeks"]:
    rec = "*" if w["is_recovery"] else " "
    ft = "T" if w["field_test"] else " "
    at = f"{w['actual_tss']}" if w["actual_tss"] is not None else "-"
    caps = ("  | " + " | ".join(w["constraints_fired"])) if w["constraints_fired"] else ""
    print(f"{w['week']:>2}{rec}{w['week_start']:10} {w['block']:8} "
          f"{w['ctl_start']:>4}->{w['ctl_target']:<5} {w['planned_ramp']:>+5.1f} "
          f"{w['weekly_tss_target']:>4} {at:>4} {w['single_ride_tss_cap']:>4} {w['est_hours']:>4} "
          f"{ft:>2}  {w['rationale']}{caps}")
print("-" * 104)
print("* = recovery week.  FT 'T' = field-test week (last of a block).  pTSS=planned, aTSS=actual.")
print("cap = 50%-rule single-ride TSS cap.  Every number from code; the right column is the rule.")
