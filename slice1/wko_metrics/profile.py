"""Athlete profile (Slice 3.5) — the per-athlete container.

Holds three kinds of athlete-level data:
  1. IDENTITY      — athlete id + name (scopes every finding/note/check-in/calendar).
  2. FIXED FACTS   — birth year (→ age, masters flag), weekly time budget, units.
                     Default to None/unknown so the current athlete's behavior is unchanged
                     until they're filled in (e.g. the masters recovery rule only applies
                     once age is known).
  3. ATHLETE-RELATIVE TUNED CONSTANTS — relocated here from the slice configs. These were
     tagged athlete-relative in earlier slices; they live HERE now (one home), so a second
     athlete gets their own values. Defaults equal the current athlete's tuned values, so
     nothing changes for them.

Constants that are genuinely UNIVERSAL (methodological: Foster monotony 1.5/2.0, ACWR
1.3/1.5, the 5% decoupling line, EWMA spans, window lengths, data-sufficiency gates,
priority/family/reset structure) deliberately STAY in the slice configs — see config.py.

Lives in the wko_metrics package purely for import layering (slice1 detectors need it and
sit at the bottom of the stack); conceptually it is app-level.
"""
import json
import sqlite3
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class AthleteProfile:
    # --- identity ---
    athlete_id: int = 1
    name: str = "Athlete 1"

    # --- fixed facts (unknown by default -> no behavior change until set) ---
    birth_year: int | None = None
    units: str = "imperial"                       # "imperial" (mi/lb) | "metric"
    week_starts_on: str = "monday"                # "monday" | "sunday" — drives calendar weeks
    weight_kg: float | None = None                # current weight (kg). v1 DISPLAY-ONLY — captured
                                                  # but not consumed by any metric yet (like ramp_rate_cap)
    # NOTE: weekly availability is NOT here — it lives on the season (slice4), because real
    # available hours change season to season. The generator reads it from the active season.

    # --- athlete-relative tuned constants (relocated from configs) ---
    # personal CTL floor (dynamic, "demonstrated sustainable base")
    floor_hold_weeks: int = 8
    floor_window_months: int = 18
    # gap_unravel
    gap_fitness_percentile: float = 80.0
    gap_confirmed_ctl_drop: float = 3.0
    genuine_peak_margin: float = 3.0
    # under_load
    underload_below_floor_frac: float = 0.8
    underload_ramp_watch: float = 1.0
    ramp_rate_cap: float = 7.0                     # CTL pts/wk safe build cap — FOR THE CALENDAR
                                                   # (Feature 3); not consumed by detectors yet
    # overtraining
    ot_tsb_percentile: float = 10.0
    # fragile_ftp
    fragile_gap_watch_w: float = 30.0
    fragile_gap_confirmed_w: float = 50.0
    # injury_spike absolute-load gates (scaled to this athlete's load)
    acwr_min_acute_load: float = 30.0
    acwr_min_chronic_load: float = 20.0
    # monotony
    monotony_band_frac: float = 0.6
    tiz_concentration_watch: float = 0.45
    # watchman context (detraining drift)
    detraining_pctile: float = 25.0

    # --- derived ---
    def age(self, ref_year):
        return None if self.birth_year is None else ref_year - self.birth_year

    def is_masters(self, ref_year):
        a = self.age(ref_year)
        return a is not None and a >= 40

    # which fields are the "tuned / advanced" set (UI marks these change-with-care)
    TUNED_FIELDS = (
        "floor_hold_weeks", "floor_window_months", "gap_fitness_percentile",
        "gap_confirmed_ctl_drop", "genuine_peak_margin", "underload_below_floor_frac",
        "underload_ramp_watch", "ramp_rate_cap", "ot_tsb_percentile", "fragile_gap_watch_w",
        "fragile_gap_confirmed_w", "acwr_min_acute_load", "acwr_min_chronic_load",
        "monotony_band_frac", "tiz_concentration_watch", "detraining_pctile",
    )
    FIXED_FACT_FIELDS = ("name", "birth_year", "units", "week_starts_on", "weight_kg")


DEFAULT_PROFILE = AthleteProfile()


# --------------------------------------------------------------------------- #
# Persistence — one row per athlete, fields as a JSON blob (schema-evolution-safe).
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    athlete_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    data        TEXT NOT NULL            -- JSON of all profile fields
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    return conn


def _from_dict(d):
    valid = {f.name for f in fields(AthleteProfile)}
    return AthleteProfile(**{k: v for k, v in d.items() if k in valid})


def load_profile(conn, athlete_id=1):
    """Load the athlete's profile, or DEFAULT_PROFILE (and persist it) on first run."""
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT data FROM profile WHERE athlete_id=?", (athlete_id,)).fetchone()
    if row is None:
        save_profile(conn, DEFAULT_PROFILE)
        return DEFAULT_PROFILE
    return _from_dict(json.loads(row[0]))


def save_profile(conn, profile):
    conn.executescript(_SCHEMA)
    conn.execute("INSERT OR REPLACE INTO profile (athlete_id, name, data) VALUES (?,?,?)",
                 (profile.athlete_id, profile.name, json.dumps(asdict(profile))))
    conn.commit()
    return profile
