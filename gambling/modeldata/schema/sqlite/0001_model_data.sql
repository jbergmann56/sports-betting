-- gambling_model_data — SQLite dialect for CI and offline use.
-- Same tables, columns, constraints and append-only rules as mysql/0001_model_data.sql;
-- only types and trigger syntax differ. Statement separator: a line that is exactly
-- two dashes, a space and two semicolons.

CREATE TABLE schema_versions (
  version INTEGER NOT NULL PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL
);
-- ;;
CREATE TABLE source_files (
  sha256 TEXT NOT NULL PRIMARY KEY, bytes INTEGER NOT NULL, original_name TEXT NOT NULL,
  media_type TEXT NOT NULL,
  sensitivity TEXT NOT NULL CHECK (sensitivity IN ('PUBLIC_MARKET','MODEL_INTERNAL','CONTAINS_USER_OBSERVATION_FLAGS')),
  provenance TEXT NOT NULL, parent_sha256 TEXT NULL REFERENCES source_files(sha256), parent_member_path TEXT NULL,
  chunk_count INTEGER NOT NULL, registered_utc TEXT NOT NULL, registered_by TEXT NOT NULL
);
-- ;;
CREATE TABLE source_file_chunks (
  sha256 TEXT NOT NULL REFERENCES source_files(sha256), chunk_no INTEGER NOT NULL, data BLOB NOT NULL,
  PRIMARY KEY (sha256, chunk_no)
);
-- ;;
CREATE TABLE datasets (
  dataset_id TEXT NOT NULL PRIMARY KEY,
  domain TEXT NOT NULL CHECK (domain IN ('games','results','odds','ratings','features','predictions',
                                         'evaluations','reference','replay_input')),
  sport TEXT NULL, description TEXT NOT NULL, created_utc TEXT NOT NULL
);
-- ;;
CREATE TABLE dataset_versions (
  version_id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
  version_label TEXT NOT NULL, source_sha256 TEXT NOT NULL REFERENCES source_files(sha256), parser TEXT NOT NULL,
  available_from_utc TEXT NULL, time_column TEXT NULL, row_count INTEGER NOT NULL, column_count INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL, parent_version_id INTEGER NULL REFERENCES dataset_versions(version_id),
  import_tool TEXT NOT NULL, created_utc TEXT NOT NULL, notes TEXT NULL,
  CONSTRAINT uq_dataset_label UNIQUE (dataset_id, version_label)
);
-- ;;
CREATE INDEX ix_dataset_available ON dataset_versions (dataset_id, available_from_utc);
-- ;;
CREATE TABLE dataset_version_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL REFERENCES dataset_versions(version_id),
  status TEXT NOT NULL CHECK (status IN ('STAGED','PUBLISHED','SUPERSEDED','RETRACTED')),
  reason TEXT NOT NULL, event_utc TEXT NOT NULL, actor TEXT NOT NULL
);
-- ;;
CREATE TABLE dataset_columns (
  version_id INTEGER NOT NULL REFERENCES dataset_versions(version_id), ordinal INTEGER NOT NULL,
  name TEXT NOT NULL, source_dtype TEXT NOT NULL, flagged TEXT NULL, PRIMARY KEY (version_id, ordinal)
);
-- ;;
CREATE TABLE dataset_rows (
  version_id INTEGER NOT NULL REFERENCES dataset_versions(version_id), row_no INTEGER NOT NULL,
  row_time_utc TEXT NULL, row_sha256 TEXT NOT NULL, row_json TEXT NOT NULL, PRIMARY KEY (version_id, row_no)
);
-- ;;
CREATE INDEX ix_row_time ON dataset_rows (version_id, row_time_utc);
-- ;;
CREATE TABLE model_releases (
  release_id TEXT NOT NULL PRIMARY KEY, sport TEXT NOT NULL, markets_json TEXT NOT NULL,
  artifact_status TEXT NOT NULL, mirrored_from TEXT NOT NULL, mirrored_utc TEXT NOT NULL
);
-- ;;
CREATE TABLE model_runs (
  run_id TEXT NOT NULL PRIMARY KEY,
  run_kind TEXT NOT NULL CHECK (run_kind IN ('GOLDEN_FIXTURE','REPLAY','LIVE','RESEARCH')),
  release_ids_json TEXT NOT NULL, input_cutoff_utc TEXT NULL, environment_json TEXT NOT NULL,
  scorer_json TEXT NOT NULL, created_utc TEXT NOT NULL, notes TEXT NULL
);
-- ;;
CREATE TABLE run_inputs (
  run_id TEXT NOT NULL REFERENCES model_runs(run_id), stage_path TEXT NOT NULL, role TEXT NOT NULL,
  version_id INTEGER NULL REFERENCES dataset_versions(version_id),
  source_sha256 TEXT NOT NULL REFERENCES source_files(sha256), PRIMARY KEY (run_id, stage_path)
);
-- ;;
CREATE TABLE run_results (
  result_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES model_runs(run_id),
  executed_utc TEXT NOT NULL, input_source TEXT NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL
);
-- ;;
CREATE TABLE evaluation_results (
  evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT, release_id TEXT NOT NULL REFERENCES model_releases(release_id),
  population_version INTEGER NULL REFERENCES dataset_versions(version_id), metric TEXT NOT NULL,
  population TEXT NOT NULL, value_num REAL NULL, n_obs INTEGER NULL, ci_low REAL NULL, ci_high REAL NULL,
  computed_utc TEXT NOT NULL, research_ref TEXT NOT NULL
);
-- ;;
CREATE VIEW dataset_version_status AS
SELECT v.version_id, v.dataset_id, v.version_label, v.available_from_utc,
       (SELECT e.status FROM dataset_version_events e WHERE e.version_id = v.version_id
         ORDER BY e.event_id DESC LIMIT 1) AS status
FROM dataset_versions v;
-- ;;
CREATE TRIGGER source_files_no_update BEFORE UPDATE ON source_files FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'source_files is append-only'); END;
-- ;;
CREATE TRIGGER source_files_no_delete BEFORE DELETE ON source_files FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'source_files is append-only'); END;
-- ;;
CREATE TRIGGER source_file_chunks_no_update BEFORE UPDATE ON source_file_chunks FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'source_file_chunks is append-only'); END;
-- ;;
CREATE TRIGGER source_file_chunks_no_delete BEFORE DELETE ON source_file_chunks FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'source_file_chunks is append-only'); END;
-- ;;
CREATE TRIGGER dataset_versions_no_update BEFORE UPDATE ON dataset_versions FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_versions is append-only'); END;
-- ;;
CREATE TRIGGER dataset_versions_no_delete BEFORE DELETE ON dataset_versions FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_versions is append-only'); END;
-- ;;
CREATE TRIGGER dataset_rows_no_update BEFORE UPDATE ON dataset_rows FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_rows is append-only'); END;
-- ;;
CREATE TRIGGER dataset_rows_no_delete BEFORE DELETE ON dataset_rows FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_rows is append-only'); END;
-- ;;
CREATE TRIGGER dataset_version_events_no_update BEFORE UPDATE ON dataset_version_events FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_version_events is append-only'); END;
-- ;;
CREATE TRIGGER dataset_version_events_no_delete BEFORE DELETE ON dataset_version_events FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'dataset_version_events is append-only'); END;
-- ;;
CREATE TRIGGER run_inputs_no_update BEFORE UPDATE ON run_inputs FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'run_inputs is append-only'); END;
-- ;;
CREATE TRIGGER run_inputs_no_delete BEFORE DELETE ON run_inputs FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'run_inputs is append-only'); END;
-- ;;
CREATE TRIGGER model_runs_no_update BEFORE UPDATE ON model_runs FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'model_runs is append-only'); END;
-- ;;
CREATE TRIGGER model_runs_no_delete BEFORE DELETE ON model_runs FOR EACH ROW
BEGIN SELECT RAISE(ABORT, 'model_runs is append-only'); END;
