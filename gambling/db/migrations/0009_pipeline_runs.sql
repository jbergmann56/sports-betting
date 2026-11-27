-- Daily pipeline runs (gambling/pipeline/) recorded in the rolling database, append-only.
--
-- A run is recorded only after its files exist and their hashes match the manifest. The complete bet
-- sheet is kept row by row (key columns + the full row as JSON), so every daily run of every sport is
-- in one master table and later runs are appended, never replacing earlier ones. These rows are NOT
-- written into the legacy model_scores table: they come from a wrapper labelled
-- UNVALIDATED_GENERALIZED_WRAPPER, and recorded history must not be mixed with them.

CREATE TABLE pipeline_runs (
 run_key TEXT PRIMARY KEY,                  -- <sport>:<slate_date>:<run_id>
 sport TEXT NOT NULL,
 slate_date TEXT NOT NULL,
 run_id TEXT NOT NULL,
 pipeline TEXT NOT NULL,
 validation_status TEXT NOT NULL,
 started_utc TEXT NOT NULL,
 finished_utc TEXT NOT NULL,
 code_commit TEXT,
 champion_release TEXT,
 challenger_release TEXT,
 capture_sha256 TEXT NOT NULL,
 history_sha256 TEXT,
 betsheet_sha256 TEXT NOT NULL,
 rows INTEGER NOT NULL,
 manifest_json TEXT NOT NULL,
 manifest_sha256 TEXT NOT NULL,
 run_dir TEXT NOT NULL,
 recorded_utc TEXT NOT NULL
);
CREATE INDEX idx_pipeline_runs_slate ON pipeline_runs(sport, slate_date, started_utc);

CREATE TABLE pipeline_sheet_rows (
 run_key TEXT NOT NULL REFERENCES pipeline_runs(run_key),
 row_no INTEGER NOT NULL,
 sport TEXT NOT NULL, event_id TEXT, start_time_utc TEXT, away TEXT, home TEXT,
 market TEXT, side TEXT, selection TEXT, line REAL, american_odds REAL,
 quote_id TEXT, quote_as_of_utc TEXT,
 model_release_id TEXT, release_role TEXT, model_status TEXT, original_tier TEXT,
 p_win REAL, ev REAL, full_kelly REAL, adjusted_kelly REAL,
 status TEXT NOT NULL,
 score_as_of_utc TEXT,
 row_json TEXT NOT NULL,                    -- the complete sheet row (shared contract columns)
 PRIMARY KEY (run_key, row_no)
);
CREATE INDEX idx_pipeline_rows_quote ON pipeline_sheet_rows(quote_id);

-- Newest run per sport and slate date.
CREATE VIEW latest_pipeline_runs AS
 SELECT r.* FROM pipeline_runs r
 WHERE r.started_utc = (SELECT MAX(x.started_utc) FROM pipeline_runs x
                        WHERE x.sport = r.sport AND x.slate_date = r.slate_date);
CREATE VIEW latest_pipeline_sheets AS
 SELECT p.slate_date, s.* FROM pipeline_sheet_rows s JOIN latest_pipeline_runs p USING (run_key);

CREATE TRIGGER pipeline_runs_no_update BEFORE UPDATE ON pipeline_runs
BEGIN SELECT RAISE(ABORT, 'pipeline_runs is append-only'); END;
CREATE TRIGGER pipeline_runs_no_delete BEFORE DELETE ON pipeline_runs
BEGIN SELECT RAISE(ABORT, 'pipeline_runs is append-only'); END;
CREATE TRIGGER pipeline_sheet_rows_no_update BEFORE UPDATE ON pipeline_sheet_rows
BEGIN SELECT RAISE(ABORT, 'pipeline_sheet_rows is append-only'); END;
CREATE TRIGGER pipeline_sheet_rows_no_delete BEFORE DELETE ON pipeline_sheet_rows
BEGIN SELECT RAISE(ABORT, 'pipeline_sheet_rows is append-only'); END;
