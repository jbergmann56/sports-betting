-- Rolling history: record imports and Bovada fetch runs, extend quotes with
-- book identifiers and provenance, and make the evidence tables append-only.
-- Raw HTTP bodies are NOT stored here; they stay as files in the capture
-- directory and are referenced by path + sha256.

CREATE TABLE history_imports (
 import_id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_path TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, imported_utc TEXT NOT NULL, counts_json TEXT NOT NULL
);

CREATE TABLE fetch_runs (
 run_id TEXT PRIMARY KEY,
 batch_id TEXT REFERENCES capture_batches(batch_id),   -- NULL when the run produced no events
 capture_dir TEXT NOT NULL,
 started_utc TEXT NOT NULL, finished_utc TEXT NOT NULL,
 all_sports_ok INTEGER NOT NULL, snapshot_skew_seconds REAL,
 config_json TEXT NOT NULL,
 manifest_sha256 TEXT NOT NULL, board_sha256 TEXT NOT NULL,
 ingested_utc TEXT NOT NULL
);

CREATE TABLE fetch_attempts (
 attempt_id TEXT PRIMARY KEY,
 run_id TEXT NOT NULL REFERENCES fetch_runs(run_id),
 sequence INTEGER NOT NULL, sport TEXT NOT NULL, purpose TEXT NOT NULL,
 variant TEXT NOT NULL, attempt INTEGER NOT NULL, url TEXT NOT NULL,
 requested_utc TEXT, received_utc TEXT, http_status INTEGER, network_error TEXT,
 outcome TEXT NOT NULL, outcome_detail TEXT, event_count INTEGER,
 cdn_age_seconds INTEGER, server_date_utc TEXT, snapshot_as_of_utc TEXT,
 body_file TEXT NOT NULL, body_bytes INTEGER NOT NULL, body_sha256 TEXT NOT NULL
);
CREATE INDEX idx_attempts_run ON fetch_attempts(run_id, sport);

CREATE TABLE sport_fetch_status (
 run_id TEXT NOT NULL REFERENCES fetch_runs(run_id), sport TEXT NOT NULL,
 status TEXT NOT NULL, detail TEXT,
 events INTEGER, pregame_events INTEGER, pregame_with_any_line INTEGER,
 pregame_complete INTEGER, special_non_games INTEGER, recovered_from_event_page INTEGER,
 still_incomplete_json TEXT, attempt_outcomes_json TEXT, variant_event_counts_json TEXT,
 snapshot_as_of_min_utc TEXT, snapshot_as_of_max_utc TEXT,
 PRIMARY KEY(run_id, sport)
);

-- Provenance for rows ingested from fetch runs (NULL for frozen legacy rows).
ALTER TABLE events ADD COLUMN attempt_id TEXT;
ALTER TABLE events ADD COLUMN received_utc TEXT;
ALTER TABLE events ADD COLUMN cdn_age_seconds INTEGER;
ALTER TABLE events ADD COLUMN last_modified_utc TEXT;
ALTER TABLE market_quotes ADD COLUMN selection TEXT;
ALTER TABLE market_quotes ADD COLUMN odds_decimal REAL;
ALTER TABLE market_quotes ADD COLUMN status_detail TEXT;
ALTER TABLE market_quotes ADD COLUMN market_id TEXT;
ALTER TABLE market_quotes ADD COLUMN outcome_id TEXT;
ALTER TABLE market_quotes ADD COLUMN price_id TEXT;
ALTER TABLE market_quotes ADD COLUMN attempt_id TEXT;
ALTER TABLE market_quotes ADD COLUMN received_utc TEXT;

CREATE INDEX idx_quotes_game ON market_quotes(game_key, market, side, quote_captured_utc);
CREATE INDEX idx_events_game ON events(game_key, quote_captured_utc);

-- Controlled vocabulary for newly ingested quotes (legacy OPEN/MISSING rows are kept as recorded).
CREATE TRIGGER market_quotes_status_vocabulary BEFORE INSERT ON market_quotes
WHEN NEW.attempt_id IS NOT NULL AND NEW.quote_status NOT IN
  ('OFFERED_PREGAME','SUSPENDED','NOT_OFFERED','NOT_PREGAME','SPECIAL_NON_GAME')
BEGIN SELECT RAISE(ABORT, 'market_quotes: invalid quote_status'); END;

-- Append-only evidence: corrections go into new, separately versioned records.
CREATE TRIGGER capture_batches_no_update BEFORE UPDATE ON capture_batches BEGIN SELECT RAISE(ABORT, 'capture_batches is append-only'); END;
CREATE TRIGGER capture_batches_no_delete BEFORE DELETE ON capture_batches BEGIN SELECT RAISE(ABORT, 'capture_batches is append-only'); END;
CREATE TRIGGER quote_cohorts_no_update BEFORE UPDATE ON quote_cohorts BEGIN SELECT RAISE(ABORT, 'quote_cohorts is append-only'); END;
CREATE TRIGGER quote_cohorts_no_delete BEFORE DELETE ON quote_cohorts BEGIN SELECT RAISE(ABORT, 'quote_cohorts is append-only'); END;
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER market_quotes_no_update BEFORE UPDATE ON market_quotes BEGIN SELECT RAISE(ABORT, 'market_quotes is append-only'); END;
CREATE TRIGGER market_quotes_no_delete BEFORE DELETE ON market_quotes BEGIN SELECT RAISE(ABORT, 'market_quotes is append-only'); END;
CREATE TRIGGER model_scores_no_update BEFORE UPDATE ON model_scores BEGIN SELECT RAISE(ABORT, 'model_scores is append-only'); END;
CREATE TRIGGER model_scores_no_delete BEFORE DELETE ON model_scores BEGIN SELECT RAISE(ABORT, 'model_scores is append-only'); END;
CREATE TRIGGER source_files_no_update BEFORE UPDATE ON source_files BEGIN SELECT RAISE(ABORT, 'source_files is append-only'); END;
CREATE TRIGGER source_files_no_delete BEFORE DELETE ON source_files BEGIN SELECT RAISE(ABORT, 'source_files is append-only'); END;
CREATE TRIGGER history_imports_no_update BEFORE UPDATE ON history_imports BEGIN SELECT RAISE(ABORT, 'history_imports is append-only'); END;
CREATE TRIGGER history_imports_no_delete BEFORE DELETE ON history_imports BEGIN SELECT RAISE(ABORT, 'history_imports is append-only'); END;
CREATE TRIGGER fetch_runs_no_update BEFORE UPDATE ON fetch_runs BEGIN SELECT RAISE(ABORT, 'fetch_runs is append-only'); END;
CREATE TRIGGER fetch_runs_no_delete BEFORE DELETE ON fetch_runs BEGIN SELECT RAISE(ABORT, 'fetch_runs is append-only'); END;
CREATE TRIGGER fetch_attempts_no_update BEFORE UPDATE ON fetch_attempts BEGIN SELECT RAISE(ABORT, 'fetch_attempts is append-only'); END;
CREATE TRIGGER fetch_attempts_no_delete BEFORE DELETE ON fetch_attempts BEGIN SELECT RAISE(ABORT, 'fetch_attempts is append-only'); END;
CREATE TRIGGER sport_fetch_status_no_update BEFORE UPDATE ON sport_fetch_status BEGIN SELECT RAISE(ABORT, 'sport_fetch_status is append-only'); END;
CREATE TRIGGER sport_fetch_status_no_delete BEFORE DELETE ON sport_fetch_status BEGIN SELECT RAISE(ABORT, 'sport_fetch_status is append-only'); END;
