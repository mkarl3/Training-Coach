"""Dated load-FTP history: the store (coach.db table), the date->FTP resolver, and that the
metrics engine scores each ride with the FTP in effect on its date (time-varying TSS)."""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)                          # for the top-level `sources` package

from sources import metrics                            # noqa: E402
from wko_metrics import ftp_history                    # noqa: E402


# --- the resolver (pure) ------------------------------------------------------------------- #
HIST = [{"date": "2024-01-01", "ftp": 200}, {"date": "2024-06-01", "ftp": 250}]


def test_ftp_asof_picks_latest_effective_entry():
    assert metrics._ftp_asof(HIST, "2024-03-01", 999) == 200      # between entries -> first
    assert metrics._ftp_asof(HIST, "2024-07-01", 999) == 250      # after both -> latest
    assert metrics._ftp_asof(HIST, "2024-06-01", 999) == 250      # exactly on the entry date


def test_ftp_asof_backfills_earliest_and_falls_back_when_empty():
    assert metrics._ftp_asof(HIST, "2023-09-01", 999) == 200      # before all -> earliest (back-fill)
    assert metrics._ftp_asof([], "2024-01-01", 180) == 180        # empty history -> fallback


# --- the engine applies it per ride ------------------------------------------------------- #
def _ride(date, np_w):
    return {"date": date, "np": np_w, "duration_s": 3600, "mmp": {}}


def test_build_daily_is_time_varying_with_a_history():
    summ = [_ride("2024-01-15", 200), _ride("2024-06-15", 200)]   # identical rides, 1h @ NP 200
    rows = {r["date"]: r for r in metrics.build_daily(summ, load_ftp=HIST)}
    # Jan ride @ FTP 200 -> IF 1.0 -> TSS 100; Jun ride @ FTP 250 -> IF 0.8 -> TSS 64
    assert round(rows["2024-01-15"]["tss_sum"]) == 100
    assert round(rows["2024-06-15"]["tss_sum"]) == 64


def test_build_daily_single_float_is_uniform():
    summ = [_ride("2024-01-15", 200), _ride("2024-06-15", 200)]
    rows = {r["date"]: r for r in metrics.build_daily(summ, load_ftp=200)}
    assert round(rows["2024-01-15"]["tss_sum"]) == round(rows["2024-06-15"]["tss_sum"]) == 100


# --- the store (coach.db) ----------------------------------------------------------------- #
def _conn():
    return sqlite3.connect(":memory:")


def test_store_add_list_latest_delete():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    ftp_history.add_entry(c, "2024-06-01", 250)
    entries = ftp_history.list_entries(c)
    assert [e["effective_date"] for e in entries] == ["2024-01-01", "2024-06-01"]   # oldest first
    assert ftp_history.latest_ftp(c) == 250
    assert ftp_history.history(c) == [{"date": "2024-01-01", "ftp": 200},
                                      {"date": "2024-06-01", "ftp": 250}]
    ftp_history.delete_entry(c, entries[1]["id"])
    assert ftp_history.latest_ftp(c) == 200


def test_store_same_day_replaces():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    ftp_history.add_entry(c, "2024-01-01", 210)              # same date -> replace, not duplicate
    assert len(ftp_history.list_entries(c)) == 1
    assert ftp_history.latest_ftp(c) == 210


def test_propose_strava_ftp_only_when_changed_and_not_auto_applied():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    assert ftp_history.propose_strava_ftp(c, 200, "2026-06-24") is None     # unchanged -> no proposal
    assert ftp_history.propose_strava_ftp(c, None, "2026-06-24") is None    # missing -> no proposal
    p = ftp_history.propose_strava_ftp(c, 215, "2026-06-24")                # changed -> PENDING only
    assert p["status"] == "pending" and p["ftp"] == 215
    assert ftp_history.latest_ftp(c) == 200                                 # NOT applied to history
    assert ftp_history.get_pending(c)["ftp"] == 215


def test_propose_does_not_renag_same_value_after_dismiss():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    ftp_history.propose_strava_ftp(c, 215, "2026-06-24")
    ftp_history.dismiss_pending(c)
    assert ftp_history.get_pending(c) is None                               # hidden after dismiss
    ftp_history.propose_strava_ftp(c, 215, "2026-07-01")                    # same value again
    assert ftp_history.get_pending(c) is None                               # still hidden — no re-nag
    ftp_history.propose_strava_ftp(c, 230, "2026-07-02")                    # a DIFFERENT value
    assert ftp_history.get_pending(c)["ftp"] == 230                         # prompts again


def test_accept_pending_applies_at_seen_date():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    ftp_history.propose_strava_ftp(c, 215, "2026-06-24")
    acc = ftp_history.accept_pending(c)
    assert acc["effective_date"] == "2026-06-24" and acc["ftp"] == 215
    assert ftp_history.latest_ftp(c) == 215 and ftp_history.get_pending(c) is None
    assert ftp_history.accept_pending(c) is None                            # nothing left to accept


def test_clear_pending_if_value_supersedes_on_manual_add():
    c = _conn()
    ftp_history.add_entry(c, "2024-01-01", 200)
    ftp_history.propose_strava_ftp(c, 215, "2026-06-24")                    # pending 215
    ftp_history.add_entry(c, "2026-05-01", 215)                             # athlete hand-adds 215 (Edit path)
    ftp_history.clear_pending_if_value(c, 215)
    assert ftp_history.get_pending(c) is None
