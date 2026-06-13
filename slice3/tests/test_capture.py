"""Capture-boundary tests. All deterministic — the validation gate is a pure function,
so the no-invented-metrics guarantee is provable without an LLM call."""
import sqlite3
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach.capture import (SubjectiveNote, NoteCategory, validate_notes,
                           store_checkin, notes_for_window, CaptureResult)

MSG = ("Rough week. Slept badly all week, work's been brutal. "
       "Legs felt flat Saturday. Got the long ride in Sunday though.")
CHECKIN = "2026-06-08"  # a Monday


def note(date, cat, text, quote):
    return SubjectiveNote(date=date, category=cat, note=text, quote=quote)


def test_valid_notes_accepted():
    notes = [
        note("2026-06-06", NoteCategory.feel, "Reported flat legs on Saturday's ride.",
             "Legs felt flat Saturday"),
        note("2026-06-08", NoteCategory.sleep, "Reported sleeping badly all week.",
             "Slept badly all week"),
    ]
    ok, bad = validate_notes(notes, MSG, CHECKIN)
    assert len(ok) == 2 and not bad


def test_fabricated_quote_rejected():
    # The model "remembers" something the athlete never said -> rejected, never stored.
    fab = note("2026-06-07", NoteCategory.sleep, "Reported 5 hours of sleep.",
               "only slept 5 hours")
    ok, bad = validate_notes([fab], MSG, CHECKIN)
    assert not ok and bad[0][1] == "quote_not_verbatim"


def test_future_and_stale_dates_rejected():
    future = note("2026-06-09", NoteCategory.feel, "x", "Legs felt flat Saturday")
    stale = note("2026-05-01", NoteCategory.feel, "x", "Legs felt flat Saturday")
    ok, bad = validate_notes([future, stale], MSG, CHECKIN)
    assert not ok
    assert {r for _, r in bad} == {"date_out_of_window"}


def test_schema_has_no_numeric_fields():
    # Structural guarantee #1: there is literally nowhere to put an invented metric.
    fields = SubjectiveNote.model_fields
    assert set(fields) == {"date", "category", "note", "quote"}
    for f in fields.values():
        assert f.annotation in (str, NoteCategory)


def test_quote_match_is_whitespace_and_case_insensitive():
    n = note("2026-06-08", NoteCategory.stress, "Work stress.", "work's   been BRUTAL")
    ok, _ = validate_notes([n], MSG, CHECKIN)
    assert ok


def test_round_trip_storage_and_window_query():
    conn = sqlite3.connect(":memory:")
    notes = [note("2026-06-06", NoteCategory.feel, "Flat legs Saturday.",
                  "Legs felt flat Saturday")]
    store_checkin(conn, CHECKIN, notes, created_at="2026-06-08T09:00:00")
    rows = notes_for_window(conn, "2026-06-01", "2026-06-08")
    assert rows == [("2026-06-06", "feel", "Flat legs Saturday.", "Legs felt flat Saturday")]
    # a window not covering the note returns nothing
    assert notes_for_window(conn, "2026-06-07", "2026-06-08") == []


def test_capture_result_parses_categories():
    r = CaptureResult(notes=[{"date": "2026-06-08", "category": "sleep",
                              "note": "x", "quote": "Slept badly all week"}])
    assert r.notes[0].category is NoteCategory.sleep
