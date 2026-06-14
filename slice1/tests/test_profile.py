"""AthleteProfile persistence — the intake data-layer addition `weight_kg` (Change 1).
JSON-blob storage, so this is a dataclass-only change: old rows (no weight_kg) load as None."""
import json
import sqlite3

from wko_metrics import profile as prof
from wko_metrics.profile import AthleteProfile, DEFAULT_PROFILE


def test_weight_kg_is_a_fixed_fact_field():
    assert "weight_kg" in AthleteProfile.FIXED_FACT_FIELDS
    assert DEFAULT_PROFILE.weight_kg is None             # unknown by default


def test_weight_kg_round_trips():
    c = sqlite3.connect(":memory:")
    import dataclasses
    p = dataclasses.replace(DEFAULT_PROFILE, weight_kg=72.5)
    prof.save_profile(c, p)
    assert prof.load_profile(c).weight_kg == 72.5


def test_old_profile_row_without_weight_loads_as_none():
    # simulate a profile persisted BEFORE weight_kg existed: a JSON blob missing the field.
    c = sqlite3.connect(":memory:")
    c.executescript(prof._SCHEMA)
    blob = {"athlete_id": 1, "name": "Old", "birth_year": 1986}   # no weight_kg key
    c.execute("INSERT INTO profile (athlete_id, name, data) VALUES (1, 'Old', ?)",
              (json.dumps(blob),))
    c.commit()
    loaded = prof.load_profile(c)
    assert loaded.weight_kg is None and loaded.name == "Old"


def test_weight_kg_is_not_a_tuned_field():
    # display-only, captured-but-unconsumed: it is a fixed fact, never a tuned/advanced constant.
    assert "weight_kg" not in AthleteProfile.TUNED_FIELDS
