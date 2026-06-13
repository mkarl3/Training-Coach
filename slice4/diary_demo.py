"""Slice 4.5 step-1 checkpoint: run the diary CLASSIFIER on sample check-in messages and print
its output as PLAIN DATA — the classification + extracted inputs + the verbatim quote behind
each, plus anything the structural gate rejected. No recompute is wired; this shows only that
the brain is sane and traceable before it can touch the plan.
"""
import datetime as dt
import os
import sqlite3
import sys

import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # slice4
sys.path.insert(0, os.path.join(ROOT, "slice1"))
sys.path.insert(0, os.path.join(ROOT, "slice3"))

from wko_metrics import metrics, DEFAULT_PROFILE                  # noqa: E402
from plan import generator, diary                                 # noqa: E402
from coach.config import DEFAULT as COACH                         # noqa: E402 (model id lives here)

m = metrics.Metrics(sqlite3.connect(os.path.join(ROOT, "slice0", "wko.db")))
as_of = m.daily.index.max().strftime("%Y-%m-%d")

# A realistic plan so relative dates ("this week") resolve against actual week starts.
a_date = (dt.date.fromisoformat(as_of) + dt.timedelta(weeks=16)).isoformat()
season = {"start_date": as_of, "weekly_hours_budget": 7.0}
events = [{"name": "Gran Fondo", "event_date": a_date, "priority": "A", "event_type": "gran_fondo"}]
plan = generator.generate_plan(m, DEFAULT_PROFILE, season, events, [], as_of)
plan_weeks, budget = plan["weeks"], season["weekly_hours_budget"]

client = anthropic.Anthropic()

SAMPLES = [
    "I caught the flu and was off the bike Monday through Wednesday. Pretty wiped but on the mend.",
    "Family's out of town this week and I've got about 12 hours to train. What about a big volume block?",
    "My knee's been grumpy on climbs - physio says keep it easy for a couple of weeks.",
    "Legs felt heavy on today's ride and I slept badly, but nothing major.",
    "I might have a work trip coming up, not sure when yet.",
    "Tweaked my ankle pretty good last night and have no idea how long I'll be out.",
    "Thanks coach, this plan looks great!",
    "Felt amazing today, fully recovered from that cold - ready to smash a huge week.",
]

print("=" * 100)
print(f"DIARY CLASSIFIER — check-in date {as_of} | standing budget {budget} h/wk | "
      f"plan wk1 starts {plan_weeks[0]['week_start']}")
print("=" * 100)
for msg in SAMPLES:
    acc, rej = diary.read_diary(msg, as_of, plan_weeks, budget, client, COACH.model)
    print(f'\nATHLETE: "{msg}"')
    if not acc and not rej:
        print("  -> (nothing plan-relevant)")
    for n in acc:
        bits = []
        for f in ("start_date", "end_date", "available_hours", "duration_weeks",
                  "intensity_capped", "reduced_hours", "severity", "reason"):
            v = getattr(n, f)
            if v is not None:
                bits.append(f"{f}={v}")
        extra = ("  [" + ", ".join(bits) + "]") if bits else ""
        q = f'  q:"{n.quote}"'
        cq = f"  ASK: {n.clarifying_question}" if n.clarifying_question else ""
        print(f"  -> {n.kind.value} (conf {n.confidence:.2f}): {n.summary}{extra}{cq}")
        print(f"     {q}")
    for n, reason in rej:
        print(f"  -> REJECTED [{reason}]: {n.kind.value} q:\"{n.quote}\"")
print("\n" + "=" * 100)
print("Classification + extracted INPUTS only — no TSS/CTL anywhere. Nothing applied; step 2 "
      "wires propose->confirm->recompute.")
