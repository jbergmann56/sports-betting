-- ESPN scoreboard captures and observations (results collector, gambling/results/espn.py).
--
-- Builds on the existing official_game_results table (0001; one row per (sport, espn_game_id)):
-- a final is inserted there the first time a completed game is observed and is never
-- overwritten. A later observation with different scores is recorded in
-- espn_result_conflicts for review instead of silently replacing the recorded final.
--
--   espn_result_captures      every raw scoreboard response: URL, request date, retrieval time, bytes
--   espn_result_observations  one parsed row per event per capture (any status, not only finals)
--   espn_result_conflicts     observed final scores that differ from official_game_results

CREATE TABLE espn_result_captures (
 capture_id TEXT PRIMARY KEY,               -- sha256 of body + retrieval time
 sport TEXT NOT NULL CHECK (sport IN ('NBA', 'NHL', 'NCAAFB', 'NCAABB', 'NFL')),
 url TEXT NOT NULL,
 requested_date TEXT NOT NULL,              -- YYYY-MM-DD scoreboard date asked for
 retrieved_utc TEXT NOT NULL,
 body_sha256 TEXT NOT NULL,
 bytes INTEGER NOT NULL,
 body BLOB NOT NULL,
 collector TEXT NOT NULL
);
CREATE INDEX idx_espn_captures_sport_date ON espn_result_captures(sport, requested_date);

CREATE TABLE espn_result_observations (
 capture_id TEXT NOT NULL REFERENCES espn_result_captures(capture_id),
 espn_game_id TEXT NOT NULL,
 sport TEXT NOT NULL,
 start_utc TEXT,
 game_date TEXT NOT NULL,                   -- US/Eastern calendar date of the start
 status_name TEXT NOT NULL,                 -- e.g. STATUS_FINAL, STATUS_SCHEDULED, STATUS_POSTPONED
 completed INTEGER NOT NULL,
 away_id TEXT, home_id TEXT, away_team TEXT, home_team TEXT,
 away_score INTEGER, home_score INTEGER,
 neutral_site INTEGER,
 PRIMARY KEY (capture_id, espn_game_id)
);
CREATE INDEX idx_espn_obs_game ON espn_result_observations(sport, espn_game_id);

CREATE TABLE espn_result_conflicts (
 conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
 sport TEXT NOT NULL,
 espn_game_id TEXT NOT NULL,
 recorded_away_score INTEGER, recorded_home_score INTEGER, recorded_source TEXT,
 observed_away_score INTEGER, observed_home_score INTEGER,
 capture_id TEXT NOT NULL REFERENCES espn_result_captures(capture_id),
 detected_utc TEXT NOT NULL
);

CREATE TRIGGER espn_result_captures_no_update BEFORE UPDATE ON espn_result_captures
BEGIN SELECT RAISE(ABORT, 'espn_result_captures is append-only'); END;
CREATE TRIGGER espn_result_captures_no_delete BEFORE DELETE ON espn_result_captures
BEGIN SELECT RAISE(ABORT, 'espn_result_captures is append-only'); END;
CREATE TRIGGER espn_result_observations_no_update BEFORE UPDATE ON espn_result_observations
BEGIN SELECT RAISE(ABORT, 'espn_result_observations is append-only'); END;
CREATE TRIGGER espn_result_observations_no_delete BEFORE DELETE ON espn_result_observations
BEGIN SELECT RAISE(ABORT, 'espn_result_observations is append-only'); END;
CREATE TRIGGER espn_result_conflicts_no_update BEFORE UPDATE ON espn_result_conflicts
BEGIN SELECT RAISE(ABORT, 'espn_result_conflicts is append-only'); END;
CREATE TRIGGER espn_result_conflicts_no_delete BEFORE DELETE ON espn_result_conflicts
BEGIN SELECT RAISE(ABORT, 'espn_result_conflicts is append-only'); END;

-- Latest observation per game (by retrieval time).
CREATE VIEW espn_latest_observation AS
SELECT o.* , c.retrieved_utc
FROM espn_result_observations o
JOIN espn_result_captures c ON c.capture_id = o.capture_id
WHERE c.retrieved_utc = (SELECT MAX(c2.retrieved_utc) FROM espn_result_observations o2
                         JOIN espn_result_captures c2 ON c2.capture_id = o2.capture_id
                         WHERE o2.sport = o.sport AND o2.espn_game_id = o.espn_game_id);
