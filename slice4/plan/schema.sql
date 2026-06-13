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
    created_at          TEXT NOT NULL
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
