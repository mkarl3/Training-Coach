"""Coach orchestration tests — fake LLM client, real retrieval/store/capture plumbing.
Proves the structural grounding (what the model is and isn't handed) deterministically."""
import os
import sqlite3
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coach import store
from coach.capture import CaptureResult
from coach.orchestrator import Coach
from coach.retrieval import MethodologyIndex

SLICE3 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_DB = os.path.join(SLICE3, "methodology.db")


class FakeClient:
    """Captures every request; returns canned responses. No network."""
    def __init__(self):
        self.requests = []
        outer = self

        class _Messages:
            def create(self, **kw):
                outer.requests.append(kw)
                text = "keywords" if kw.get("max_tokens") == 100 else "Coach reply."
                block = types.SimpleNamespace(type="text", text=text)
                return types.SimpleNamespace(content=[block])

            def parse(self, **kw):
                outer.requests.append(kw)
                return types.SimpleNamespace(parsed_output=CaptureResult(notes=[{
                    "date": "2026-06-06", "category": "feel",
                    "note": "Reported flat legs.", "quote": "legs felt flat saturday"}]))

        self.messages = _Messages()


WATCH_STATE = {"as_of": "2026-06-08", "status": "green", "tripwires": [],
               "trend_annotations": [], "context": []}
CONFIRMED = [{"mode_id": "gap_unravel", "variant": "early_warning",
              "detector_family": "tripwire", "window_start": "2026-03-12",
              "window_end": "2026-03-18", "priority": 3,
              "evidence": {"ctl_drop": 5.0}, "data_flags": []}]


def make_coach(conn):
    idx = MethodologyIndex(INDEX_DB)
    return Coach(conn, WATCH_STATE, CONFIRMED, idx, client=FakeClient())


def test_respond_round_trip_persists_and_captures():
    conn = store.connect(":memory:")
    coach = make_coach(conn)
    cid = store.start_conversation(conn, "2026-06-08", "2026-06-08T09:00:00")
    out = coach.respond("Legs felt flat Saturday. How should I handle next week?",
                        cid, "2026-06-08", "2026-06-08T09:00:00")
    assert out["reply"] == "Coach reply."
    assert out["notes_captured"] == [{"date": "2026-06-06", "category": "feel",
                                      "note": "Reported flat legs."}]
    # both sides persisted
    h = store.history(conn, cid)
    assert [r for r, _, _ in h] == ["user", "assistant"]
    # methodology actually retrieved from the real index
    assert out["methodology_used"]


def test_model_is_handed_findings_not_raw_tables():
    conn = store.connect(":memory:")
    coach = make_coach(conn)
    cid = store.start_conversation(conn, "2026-06-08", "t")
    coach.respond("Why did my fitness drop in March?", cid, "2026-06-08", "t")
    main_call = coach.client.requests[-1]            # the reply-generating call
    prompt = str(main_call["messages"])
    # findings JSON is present (the engine's numbers, citable)
    assert "gap_unravel" in prompt and "ctl_drop" in prompt
    # methodology + notes sections present
    assert "METHODOLOGY" in prompt and "NOTES" in prompt
    # structural guarantee: no raw table dumps — these column names never appear
    for forbidden in ("tss_sum", "tiz_pwr_z1_sec", "if_daily", "SELECT "):
        assert forbidden not in prompt
    # system prompt carries the grounding rules
    assert "NEVER calculate" in main_call["system"]


def test_memory_carries_across_conversations():
    conn = store.connect(":memory:")
    coach = make_coach(conn)
    # anchor c1 on 06-06 so the fake note (dated 06-06) passes the date gate
    c1 = store.start_conversation(conn, "2026-06-06", "t1")
    coach.respond("Slept badly. Legs felt flat Saturday.", c1, "2026-06-06", "t1")
    # next week's conversation: prior notes + prior check-in date are in the context
    c2 = store.start_conversation(conn, "2026-06-08", "t2")
    coach.respond("Feeling better this week.", c2, "2026-06-08", "t2")
    prompt = str(coach.client.requests[-1]["messages"])
    assert "Prior check-ins on: 2026-06-06" in prompt   # prior check-in referenced
    assert "Reported flat legs." in prompt              # prior note carried forward


def test_empty_retrieval_instructs_soft_flag():
    conn = store.connect(":memory:")
    idx = MethodologyIndex(INDEX_DB)
    coach = Coach(conn, WATCH_STATE, [], idx, client=FakeClient())
    cid = store.start_conversation(conn, "2026-06-08", "t")
    # gibberish question -> nothing above the similarity floor
    coach.respond("zzqx blorf vfx?", cid, "2026-06-08", "t")
    prompt = str(coach.client.requests[-1]["messages"])
    assert "flag any general answer" in prompt
