-- Model-input store inside the rolling history database.
--
-- Builds on the existing data model instead of duplicating it:
--   * releases come from model_releases (0004); authority stays in model_release_status
--   * runs can point at the capture batch / quote cohort they scored (capture_batches,
--     quote_cohorts) and at the model_scores rows they reproduce
--   * dataset rows can carry the existing game_key so inputs join to events,
--     market_quotes, model_scores and official_game_results
-- All new objects use the md_ prefix; the existing source_files table (capture files
-- per batch) keeps its meaning. Sportsbook account and wager data never enter these
-- tables: gambling.modeldata.store.guard_columns rejects account exports.
--
--   md_source_files        immutable source bytes, content-addressed by sha256
--   md_source_file_chunks  the bytes, 1 MiB chunks
--   md_datasets            logical datasets (games, ratings, features, replay inputs ...)
--   md_dataset_versions    immutable parsed versions with availability time and content hash
--   md_dataset_version_events  append-only status (STAGED/PUBLISHED/SUPERSEDED/RETRACTED)
--   md_dataset_columns     column catalog with user-observation flags
--   md_dataset_rows        lossless rows (JSON array of text values), optional time and game_key
--   md_model_runs          a reproducible scoring run
--   md_run_releases        which registered releases the run executed
--   md_run_inputs          exact bytes pinned at each staged path
--   md_run_results         each execution of a run (replay reports)
--   md_run_score_links     model_scores rows a run reproduces
--   md_evaluation_results  research metrics per release (ChatGPT-side evaluations, by reference)

CREATE TABLE md_source_files (
 sha256 TEXT PRIMARY KEY,
 bytes INTEGER NOT NULL,
 original_name TEXT NOT NULL,
 media_type TEXT NOT NULL,
 sensitivity TEXT NOT NULL CHECK (sensitivity IN ('PUBLIC_MARKET', 'MODEL_INTERNAL', 'CONTAINS_USER_OBSERVATION_FLAGS')),
 provenance TEXT NOT NULL,
 parent_sha256 TEXT REFERENCES md_source_files(sha256),
 parent_member_path TEXT,
 chunk_count INTEGER NOT NULL,
 registered_utc TEXT NOT NULL,
 registered_by TEXT NOT NULL
);

CREATE TABLE md_source_file_chunks (
 sha256 TEXT NOT NULL REFERENCES md_source_files(sha256),
 chunk_no INTEGER NOT NULL,
 data BLOB NOT NULL,
 PRIMARY KEY (sha256, chunk_no)
);

CREATE TABLE md_datasets (
 dataset_id TEXT PRIMARY KEY,
 domain TEXT NOT NULL CHECK (domain IN ('games', 'results', 'odds', 'ratings', 'features', 'predictions',
                                        'evaluations', 'reference', 'replay_input')),
 sport TEXT CHECK (sport IS NULL OR sport IN ('NBA', 'NHL', 'NCAAFB', 'NCAABB', 'NFL')),
 description TEXT NOT NULL,
 created_utc TEXT NOT NULL
);

CREATE TABLE md_dataset_versions (
 version_id INTEGER PRIMARY KEY AUTOINCREMENT,
 dataset_id TEXT NOT NULL REFERENCES md_datasets(dataset_id),
 version_label TEXT NOT NULL,
 source_sha256 TEXT NOT NULL REFERENCES md_source_files(sha256),
 parser TEXT NOT NULL,
 available_from_utc TEXT,
 time_column TEXT,
 game_key_column TEXT,
 row_count INTEGER NOT NULL,
 column_count INTEGER NOT NULL,
 content_sha256 TEXT NOT NULL,
 parent_version_id INTEGER REFERENCES md_dataset_versions(version_id),
 import_tool TEXT NOT NULL,
 created_utc TEXT NOT NULL,
 notes TEXT,
 UNIQUE (dataset_id, version_label)
);
CREATE INDEX idx_md_dataset_available ON md_dataset_versions(dataset_id, available_from_utc);

CREATE TABLE md_dataset_version_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 version_id INTEGER NOT NULL REFERENCES md_dataset_versions(version_id),
 status TEXT NOT NULL CHECK (status IN ('STAGED', 'PUBLISHED', 'SUPERSEDED', 'RETRACTED')),
 reason TEXT NOT NULL,
 event_utc TEXT NOT NULL,
 actor TEXT NOT NULL
);

CREATE TABLE md_dataset_columns (
 version_id INTEGER NOT NULL REFERENCES md_dataset_versions(version_id),
 ordinal INTEGER NOT NULL,
 name TEXT NOT NULL,
 source_dtype TEXT NOT NULL,
 flagged TEXT CHECK (flagged IS NULL OR flagged IN ('USER_OBSERVATION_FLAG', 'REVIEWED_MODEL_FIELD')),
 PRIMARY KEY (version_id, ordinal)
);

CREATE TABLE md_dataset_rows (
 version_id INTEGER NOT NULL REFERENCES md_dataset_versions(version_id),
 row_no INTEGER NOT NULL,
 row_time_utc TEXT,
 game_key TEXT,                  -- same key as events.game_key / model_scores.game_key when known
 row_sha256 TEXT NOT NULL,
 row_json TEXT NOT NULL,
 PRIMARY KEY (version_id, row_no)
);
CREATE INDEX idx_md_row_time ON md_dataset_rows(version_id, row_time_utc);
CREATE INDEX idx_md_row_game ON md_dataset_rows(game_key);

CREATE TABLE md_model_runs (
 run_id TEXT PRIMARY KEY,
 run_kind TEXT NOT NULL CHECK (run_kind IN ('GOLDEN_FIXTURE', 'REPLAY', 'LIVE', 'RESEARCH')),
 sport TEXT CHECK (sport IS NULL OR sport IN ('NBA', 'NHL', 'NCAAFB', 'NCAABB', 'NFL')),
 batch_id TEXT REFERENCES capture_batches(batch_id),
 quote_cohort_id TEXT REFERENCES quote_cohorts(cohort_id),
 input_cutoff_utc TEXT,
 environment_json TEXT NOT NULL,
 scorer_json TEXT NOT NULL,
 created_utc TEXT NOT NULL,
 notes TEXT
);

CREATE TABLE md_run_releases (
 run_id TEXT NOT NULL REFERENCES md_model_runs(run_id),
 release_id TEXT NOT NULL REFERENCES model_releases(release_id),
 PRIMARY KEY (run_id, release_id)
);

CREATE TABLE md_run_inputs (
 run_id TEXT NOT NULL REFERENCES md_model_runs(run_id),
 stage_path TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('INPUT', 'EXPECTED_OUTPUT', 'ARCHIVE', 'MANIFEST')),
 version_id INTEGER REFERENCES md_dataset_versions(version_id),
 source_sha256 TEXT NOT NULL REFERENCES md_source_files(sha256),
 PRIMARY KEY (run_id, stage_path)
);

CREATE TABLE md_run_results (
 result_id INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES md_model_runs(run_id),
 executed_utc TEXT NOT NULL,
 input_source TEXT NOT NULL,
 status TEXT NOT NULL,
 report_json TEXT NOT NULL
);

CREATE TABLE md_run_score_links (
 run_id TEXT NOT NULL REFERENCES md_model_runs(run_id),
 score_id TEXT NOT NULL REFERENCES model_scores(score_id),
 basis TEXT NOT NULL,
 linked_utc TEXT NOT NULL,
 PRIMARY KEY (run_id, score_id)
);

CREATE TABLE md_evaluation_results (
 evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 release_id TEXT NOT NULL REFERENCES model_releases(release_id),
 population_version INTEGER REFERENCES md_dataset_versions(version_id),
 metric TEXT NOT NULL,
 population TEXT NOT NULL,
 value_num REAL,
 n_obs INTEGER,
 ci_low REAL,
 ci_high REAL,
 computed_utc TEXT NOT NULL,
 research_ref TEXT NOT NULL
);

CREATE VIEW md_dataset_version_status AS
SELECT v.version_id, v.dataset_id, v.version_label, v.available_from_utc,
       (SELECT e.status FROM md_dataset_version_events e WHERE e.version_id = v.version_id
         ORDER BY e.event_id DESC LIMIT 1) AS status
FROM md_dataset_versions v;

-- Inputs joined to the existing game/quote/score history by game_key.
CREATE VIEW md_rows_by_game AS
SELECT r.game_key, d.sport, d.dataset_id, d.domain, v.version_id, v.version_label, r.row_no,
       r.row_time_utc, r.row_json
FROM md_dataset_rows r
JOIN md_dataset_versions v ON v.version_id = r.version_id
JOIN md_datasets d ON d.dataset_id = v.dataset_id
WHERE r.game_key IS NOT NULL;

CREATE TRIGGER md_source_files_no_update BEFORE UPDATE ON md_source_files
BEGIN SELECT RAISE(ABORT, 'md_source_files is append-only'); END;
CREATE TRIGGER md_source_files_no_delete BEFORE DELETE ON md_source_files
BEGIN SELECT RAISE(ABORT, 'md_source_files is append-only'); END;
CREATE TRIGGER md_source_file_chunks_no_update BEFORE UPDATE ON md_source_file_chunks
BEGIN SELECT RAISE(ABORT, 'md_source_file_chunks is append-only'); END;
CREATE TRIGGER md_source_file_chunks_no_delete BEFORE DELETE ON md_source_file_chunks
BEGIN SELECT RAISE(ABORT, 'md_source_file_chunks is append-only'); END;
CREATE TRIGGER md_dataset_versions_no_update BEFORE UPDATE ON md_dataset_versions
BEGIN SELECT RAISE(ABORT, 'md_dataset_versions is append-only'); END;
CREATE TRIGGER md_dataset_versions_no_delete BEFORE DELETE ON md_dataset_versions
BEGIN SELECT RAISE(ABORT, 'md_dataset_versions is append-only'); END;
CREATE TRIGGER md_dataset_columns_no_update BEFORE UPDATE ON md_dataset_columns
BEGIN SELECT RAISE(ABORT, 'md_dataset_columns is append-only'); END;
CREATE TRIGGER md_dataset_columns_no_delete BEFORE DELETE ON md_dataset_columns
BEGIN SELECT RAISE(ABORT, 'md_dataset_columns is append-only'); END;
CREATE TRIGGER md_dataset_rows_no_update BEFORE UPDATE ON md_dataset_rows
BEGIN SELECT RAISE(ABORT, 'md_dataset_rows is append-only'); END;
CREATE TRIGGER md_dataset_rows_no_delete BEFORE DELETE ON md_dataset_rows
BEGIN SELECT RAISE(ABORT, 'md_dataset_rows is append-only'); END;
CREATE TRIGGER md_dataset_version_events_no_update BEFORE UPDATE ON md_dataset_version_events
BEGIN SELECT RAISE(ABORT, 'md_dataset_version_events is append-only'); END;
CREATE TRIGGER md_dataset_version_events_no_delete BEFORE DELETE ON md_dataset_version_events
BEGIN SELECT RAISE(ABORT, 'md_dataset_version_events is append-only'); END;
CREATE TRIGGER md_model_runs_no_update BEFORE UPDATE ON md_model_runs
BEGIN SELECT RAISE(ABORT, 'md_model_runs is append-only'); END;
CREATE TRIGGER md_model_runs_no_delete BEFORE DELETE ON md_model_runs
BEGIN SELECT RAISE(ABORT, 'md_model_runs is append-only'); END;
CREATE TRIGGER md_run_releases_no_update BEFORE UPDATE ON md_run_releases
BEGIN SELECT RAISE(ABORT, 'md_run_releases is append-only'); END;
CREATE TRIGGER md_run_releases_no_delete BEFORE DELETE ON md_run_releases
BEGIN SELECT RAISE(ABORT, 'md_run_releases is append-only'); END;
CREATE TRIGGER md_run_inputs_no_update BEFORE UPDATE ON md_run_inputs
BEGIN SELECT RAISE(ABORT, 'md_run_inputs is append-only'); END;
CREATE TRIGGER md_run_inputs_no_delete BEFORE DELETE ON md_run_inputs
BEGIN SELECT RAISE(ABORT, 'md_run_inputs is append-only'); END;
CREATE TRIGGER md_run_results_no_update BEFORE UPDATE ON md_run_results
BEGIN SELECT RAISE(ABORT, 'md_run_results is append-only'); END;
CREATE TRIGGER md_run_results_no_delete BEFORE DELETE ON md_run_results
BEGIN SELECT RAISE(ABORT, 'md_run_results is append-only'); END;
CREATE TRIGGER md_run_score_links_no_update BEFORE UPDATE ON md_run_score_links
BEGIN SELECT RAISE(ABORT, 'md_run_score_links is append-only'); END;
CREATE TRIGGER md_run_score_links_no_delete BEFORE DELETE ON md_run_score_links
BEGIN SELECT RAISE(ABORT, 'md_run_score_links is append-only'); END;
CREATE TRIGGER md_evaluation_results_no_update BEFORE UPDATE ON md_evaluation_results
BEGIN SELECT RAISE(ABORT, 'md_evaluation_results is append-only'); END;
CREATE TRIGGER md_evaluation_results_no_delete BEFORE DELETE ON md_evaluation_results
BEGIN SELECT RAISE(ABORT, 'md_evaluation_results is append-only'); END;
