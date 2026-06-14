-- Season-input layer (Slice 4, step 1). The goals/boundaries/constraints a calendar is
-- built backward from — none of which exist in WKO5. Athlete-scoped (Slice 3.5 convention).

-- A planning season: a window with a start, an availability budget, and one or more goal
-- events. The A-race(s) among its events define the peak date(s) the plan builds backward
-- from. Weekly time budget lives HERE, not on the profile — availability is season-specific
-- (a heavy work season differs from an off-season), so the generator reads it from the season.
CREATE TABLE IF NOT EXISTS season (
    id                  INTEGER PRIMARY KEY,
    athlete_id          INTEGER NOT NULL DEFAULT 1,
    name                TEXT NOT NULL,
    start_date          TEXT NOT NULL,             -- ISO 'YYYY-MM-DD'; plan begins here
    weekly_hours_budget REAL NOT NULL,             -- real available hours/wk this season
    is_active           INTEGER NOT NULL DEFAULT 1, -- the season the dashboard/coach plan against
    created_at          TEXT NOT NULL,
    -- no-event fallback (intake): when no goal_event is set, the athlete gives a general
    -- DIRECTION. With no A-race date there is no peak/taper — this sets build EMPHASIS only
    -- (open-ended base/build). Values are the generator's existing emphasis classes, validated
    -- in app (no column CHECK): durability | sustained_threshold | anaerobic | balanced.
    general_goal        TEXT                       -- nullable; appended to match the ALTER migration
);

-- Goal events. priority + type shape the build:
--   priority A -> the race the plan peaks for (taper targets it); B -> train through;
--               C -> training/tune-up, no taper.
--   type drives the build emphasis the generator applies in step 2:
--     road_race_hilly / gran_fondo / climbing_gc -> durability + long-ride priority
--     time_trial / road_race_flat               -> sustained threshold (FTP/TTE)
--     criterium                                  -> anaerobic / repeatability
--     mixed / other                              -> balanced
CREATE TABLE IF NOT EXISTS goal_event (
    id          INTEGER PRIMARY KEY,
    season_id   INTEGER NOT NULL REFERENCES season(id),
    athlete_id  INTEGER NOT NULL DEFAULT 1,
    name        TEXT NOT NULL,
    event_date  TEXT NOT NULL,                 -- ISO date
    priority    TEXT NOT NULL CHECK (priority IN ('A', 'B', 'C')),
    event_type  TEXT NOT NULL,                 -- one of the types above (validated in app)
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_season ON goal_event(season_id);

-- Known unavailable periods (travel, surgery, commitments). The generator routes planned
-- recovery into these where it can, and never prescribes load the athlete can't do.
CREATE TABLE IF NOT EXISTS unavailable_period (
    id          INTEGER PRIMARY KEY,
    season_id   INTEGER NOT NULL REFERENCES season(id),
    athlete_id  INTEGER NOT NULL DEFAULT 1,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    reason      TEXT,                           -- free text: "work travel", "vacation", ...
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_unavail_season ON unavailable_period(season_id);

-- Historical life context (intake): injury/illness/newborn/travel tagged onto the PAST timeline.
-- Distinct from unavailable_period (forward-looking) — the same real event may be recorded as both.
-- Read by the watchman life-event findings modifier (slice2). detector_effect is decided at intake
-- write time from `category`, then stored explicitly so the consumer stays dumb.
CREATE TABLE IF NOT EXISTS life_event (
    id              INTEGER PRIMARY KEY,
    athlete_id      INTEGER NOT NULL DEFAULT 1,
    start_date      TEXT NOT NULL,            -- ISO 'YYYY-MM-DD'
    end_date        TEXT,                     -- NULL = point / ongoing
    category        TEXT NOT NULL,            -- injury | illness | life | travel | equipment | other
    note            TEXT,                     -- free text, coach only
    detector_effect TEXT NOT NULL             -- annotate_only | downgrade_severity
        CHECK (detector_effect IN ('annotate_only','downgrade_severity')),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_life_event_athlete ON life_event(athlete_id, start_date);

-- Transient plan modifiers (Slice 4.5 — diary-driven). Each bends one or more weeks without
-- touching the season's standing inputs: 'availability' overrides the weekly hours for a window
-- (an opportunity UP, or a reduced re-entry window DOWN); 'intensity_cap' holds a window easy
-- (aerobic only, no CTL building) for a re-entry or an ongoing limiter. The generator reads the
-- ACTIVE ones; undo flips active=0. Guardrails still bind — a modifier can only relax the time
-- budget or tighten intensity, never loosen a safety limit.
CREATE TABLE IF NOT EXISTS plan_modifier (
    id          INTEGER PRIMARY KEY,
    season_id   INTEGER NOT NULL REFERENCES season(id),
    athlete_id  INTEGER NOT NULL DEFAULT 1,
    kind        TEXT NOT NULL,                   -- 'availability' | 'intensity_cap'
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    hours       REAL,                            -- availability: hours/wk for the window
    reason      TEXT,
    active      INTEGER NOT NULL DEFAULT 1,      -- undo sets this 0
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_modifier_season ON plan_modifier(season_id, active);

-- Adjustment audit trail (Slice 4.5). One row per APPLIED diary-driven change: what it was, a
-- human summary, and how to undo it. The athlete sees this as plan history; undo deactivates the
-- adjustment and the row it created. Nothing here is applied without the athlete confirming first.
CREATE TABLE IF NOT EXISTS plan_adjustment (
    id          INTEGER PRIMARY KEY,
    season_id   INTEGER NOT NULL REFERENCES season(id),
    athlete_id  INTEGER NOT NULL DEFAULT 1,
    kind        TEXT NOT NULL,                   -- AdjustmentKind value (hard_time_loss, ...)
    summary     TEXT NOT NULL,
    applied     TEXT NOT NULL,                   -- JSON: what was written
    undo_ref    TEXT NOT NULL,                   -- JSON: {"table":..., "id":...} to reverse
    active      INTEGER NOT NULL DEFAULT 1,      -- undo sets this 0
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adjustment_season ON plan_adjustment(season_id);
