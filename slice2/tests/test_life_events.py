"""Life-event findings modifier (intake data layer). Frozen semantics — hand-verified on
synthetic findings, then confirmed against the sample athlete's real crash window. The modifier
adds no metric and no detector; it only explains/quiets findings the detectors already emit."""
import sqlite3

from watchman import (apply_life_events, load_life_events, select, DEFAULT_SELECTION,
                      add_life_event, list_life_events, delete_life_event)

_LIFE_EVENT_DDL = (
    "CREATE TABLE life_event (id INTEGER PRIMARY KEY, athlete_id INTEGER NOT NULL DEFAULT 1, "
    "start_date TEXT NOT NULL, end_date TEXT, category TEXT NOT NULL, note TEXT, "
    "detector_effect TEXT NOT NULL, created_at TEXT NOT NULL);")


def _life_db():
    c = sqlite3.connect(":memory:")
    c.executescript(_LIFE_EVENT_DDL)
    return c


def finding(severity="confirmed", start="2026-03-01", end="2026-03-14", family="tripwire",
            flags=None, mode="gap_unravel"):
    return {"mode_id": mode, "variant": "early_warning", "severity": severity,
            "detector_family": family, "window_start": start, "window_end": end,
            "evidence": {}, "discriminator_result": {}, "data_flags": list(flags or []), "priority": 1}


def event(start="2026-03-05", end="2026-03-12", category="injury", effect="downgrade_severity"):
    return {"start_date": start, "end_date": end, "category": category, "detector_effect": effect}


# --------------------------------------------------------------------------- #
# Frozen semantics
# --------------------------------------------------------------------------- #
def test_downgrade_overlap_softens_confirmed_to_watch_and_flags():
    out = apply_life_events([finding()], [event()])
    assert out[0]["severity"] == "watch"
    assert "explained:injury" in out[0]["data_flags"]


def test_annotate_only_flags_but_keeps_severity():
    out = apply_life_events([finding()], [event(category="travel", effect="annotate_only")])
    assert out[0]["severity"] == "confirmed"
    assert out[0]["data_flags"] == ["explained:travel"]


def test_no_overlap_leaves_finding_untouched():
    out = apply_life_events([finding(start="2026-03-01", end="2026-03-14")],
                            [event(start="2026-05-01", end="2026-05-10")])
    assert out[0]["severity"] == "confirmed" and out[0]["data_flags"] == []


def test_ongoing_event_null_end_is_open_ended():
    # event starts 2026-02-01, no end -> overlaps any finding ending on/after that
    out = apply_life_events([finding(start="2026-04-01", end="2026-04-07")],
                            [event(start="2026-02-01", end=None)])
    assert out[0]["severity"] == "watch" and "explained:injury" in out[0]["data_flags"]


def test_flag_dedup_same_category():
    out = apply_life_events([finding()], [event(), event(start="2026-03-08", end="2026-03-10")])
    assert out[0]["data_flags"].count("explained:injury") == 1


def test_effects_compose_downgrade_plus_annotate():
    out = apply_life_events([finding()],
                            [event(category="illness", effect="downgrade_severity"),
                             event(category="travel", effect="annotate_only")])
    assert out[0]["severity"] == "watch"
    assert set(out[0]["data_flags"]) == {"explained:illness", "explained:travel"}


def test_trend_family_is_flagged_but_never_downgraded():
    out = apply_life_events([finding(family="trend")], [event()])
    assert out[0]["severity"] == "confirmed"                 # trend severity untouched
    assert "explained:injury" in out[0]["data_flags"]


def test_watch_finding_is_only_flagged():
    out = apply_life_events([finding(severity="watch")], [event()])
    assert out[0]["severity"] == "watch" and "explained:injury" in out[0]["data_flags"]


def test_never_deletes_and_preserves_other_findings():
    fs = [finding(mode="gap_unravel"), finding(mode="overtraining", start="2026-07-01", end="2026-07-07")]
    out = apply_life_events(fs, [event()])
    assert len(out) == 2
    assert out[1]["severity"] == "confirmed" and out[1]["data_flags"] == []   # untouched one


def test_empty_events_returns_input_byte_identical():
    fs = [finding()]
    assert apply_life_events(fs, []) is fs                   # no copy, no change


def test_does_not_mutate_input_findings():
    fs = [finding()]
    apply_life_events(fs, [event()])
    assert fs[0]["severity"] == "confirmed" and fs[0]["data_flags"] == []     # original intact


# --------------------------------------------------------------------------- #
# load_life_events — graceful, real reads
# --------------------------------------------------------------------------- #
def test_load_graceful_when_table_absent():
    assert load_life_events(sqlite3.connect(":memory:")) == []


# --------------------------------------------------------------------------- #
# CRUD (handoff 2) — write/read/delete + default-effect mapping + validation
# --------------------------------------------------------------------------- #
def test_add_life_event_default_effect_mapping():
    c = _life_db()
    add_life_event(c, "2026-03-01", "injury", "t", end_date="2026-03-20")
    add_life_event(c, "2026-04-01", "illness", "t")
    add_life_event(c, "2026-05-01", "travel", "t")
    add_life_event(c, "2026-05-10", "equipment", "t")
    evs = {e["category"]: e["detector_effect"] for e in list_life_events(c)}
    assert evs["injury"] == "downgrade_severity" and evs["illness"] == "downgrade_severity"
    assert evs["travel"] == "annotate_only" and evs["equipment"] == "annotate_only"


def test_add_life_event_override_and_validation():
    c = _life_db()
    add_life_event(c, "2026-03-01", "injury", "t", detector_effect="annotate_only")   # override wins
    assert list_life_events(c)[0]["detector_effect"] == "annotate_only"
    for bad_cat in ("sickness", "vacation", ""):
        try:
            add_life_event(c, "2026-03-01", bad_cat, "t")
            assert False, f"expected ValueError for category {bad_cat!r}"
        except ValueError:
            pass
    try:
        add_life_event(c, "2026-03-01", "injury", "t", detector_effect="nuke")
        assert False, "expected ValueError for bad effect"
    except ValueError:
        pass


def test_delete_life_event():
    c = _life_db()
    eid = add_life_event(c, "2026-03-01", "injury", "t")
    assert len(list_life_events(c)) == 1
    delete_life_event(c, eid)
    assert list_life_events(c) == []


def test_load_reads_rows():
    c = sqlite3.connect(":memory:")
    c.executescript("CREATE TABLE life_event (id INTEGER PRIMARY KEY, athlete_id INTEGER, "
                    "start_date TEXT, end_date TEXT, category TEXT, note TEXT, detector_effect TEXT, created_at TEXT);")
    c.execute("INSERT INTO life_event (athlete_id, start_date, end_date, category, detector_effect, created_at) "
              "VALUES (1,'2026-03-05','2026-03-12','injury','downgrade_severity','x')")
    c.commit()
    evs = load_life_events(c)
    assert len(evs) == 1 and evs[0]["category"] == "injury" and evs[0]["detector_effect"] == "downgrade_severity"


# --------------------------------------------------------------------------- #
# Real data — the sample athlete's crash window (checkpoint 3 & 4)
# --------------------------------------------------------------------------- #
def test_real_confirmed_finding_downgrades_and_collapses(findings, m):
    conf = [f for f in findings if f["severity"] == "confirmed" and f["detector_family"] == "tripwire"]
    assert conf, "expected at least one confirmed tripwire (the crash) in the sample athlete"
    target = conf[0]
    ev = [event(start=target["window_start"], end=target["window_end"],
                category="injury", effect="downgrade_severity")]

    downgraded = apply_life_events(findings, ev)
    hit = [f for f in downgraded if f["mode_id"] == target["mode_id"]
           and f["window_start"] == target["window_start"]][0]
    assert hit["severity"] == "watch" and "explained:injury" in hit["data_flags"]
    # select.py rule 3: an explained gap collapses into the watch rollup, not a red alert
    after = select(downgraded, m.daily.index.max().strftime("%Y-%m-%d"), m, DEFAULT_SELECTION)
    assert not any(t["mode_id"] == target["mode_id"]
                   and t["window_start"] == target["window_start"] for t in after["tripwires"])

    # annotate_only over the same finding -> stays confirmed, still flagged (checkpoint 4)
    annotated = apply_life_events(findings, [event(start=target["window_start"],
                                  end=target["window_end"], category="travel", effect="annotate_only")])
    hit2 = [f for f in annotated if f["mode_id"] == target["mode_id"]
            and f["window_start"] == target["window_start"]][0]
    assert hit2["severity"] == "confirmed" and "explained:travel" in hit2["data_flags"]
