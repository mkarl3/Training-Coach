"""Checkpoint demo for the subjective-capture store.

Part 1 (always runs, no API): pushes a SIMULATED extractor output — including a fabricated
quote and an invented-metric attempt — through the validation gate, showing exactly what
would and would not reach storage.
Part 2 (needs ANTHROPIC_API_KEY): live extraction of the sample check-in.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coach.capture import (SubjectiveNote, NoteCategory, validate_notes, extract_notes)

MSG = ("Rough one. Slept badly all week, work's been brutal and I was up late three nights. "
       "Legs felt flat Saturday, totally empty. Skipped Friday entirely. "
       "Sunday's long ride actually felt decent once I got going.")
CHECKIN = "2026-06-08"


def show(accepted, rejected, title):
    print("=" * 78)
    print(title)
    print(f"  accepted -> stored ({len(accepted)}):")
    for n in accepted:
        print(f"    {n.date}  [{n.category.value:15s}] {n.note}")
        print(f"               quote: \"{n.quote}\"")
    if rejected:
        print(f"  REJECTED by the gate ({len(rejected)}):")
        for n, why in rejected:
            print(f"    {n.date}  [{n.category.value:15s}] {n.note}   <- {why}")


def main():
    print(f"Check-in message ({CHECKIN}):\n  \"{MSG}\"\n")

    # ---- Part 1: simulated extractor output through the validation gate ----
    simulated = [
        SubjectiveNote(date="2026-06-08", category=NoteCategory.sleep,
                       note="Reported sleeping badly all week.",
                       quote="Slept badly all week"),
        SubjectiveNote(date="2026-06-06", category=NoteCategory.feel,
                       note="Reported flat, empty legs on Saturday.",
                       quote="Legs felt flat Saturday, totally empty"),
        SubjectiveNote(date="2026-06-05", category=NoteCategory.time_constraint,
                       note="Skipped Friday's session.",
                       quote="Skipped Friday entirely"),
        # VIOLATION: invented number + fabricated quote (athlete never said this)
        SubjectiveNote(date="2026-06-07", category=NoteCategory.sleep,
                       note="Slept only 4 hours.",
                       quote="only got 4 hours"),
        # VIOLATION: future-dated note
        SubjectiveNote(date="2026-06-10", category=NoteCategory.motivation,
                       note="Feels good about next week.",
                       quote="felt decent once I got going"),
    ]
    show(*validate_notes(simulated, MSG, CHECKIN),
         title="PART 1 — validation gate on simulated output (2 violations planted)")

    # ---- Part 2: live extraction (requires credentials) ----
    print("=" * 78)
    try:
        accepted, rejected = extract_notes(MSG, CHECKIN)
        show(accepted, rejected, "PART 2 — LIVE extraction (claude-opus-4-8)")
    except Exception as e:
        print(f"PART 2 — live extraction skipped: {type(e).__name__}: {str(e)[:120]}")
        print("  (set ANTHROPIC_API_KEY and re-run to see the live result)")


if __name__ == "__main__":
    main()
