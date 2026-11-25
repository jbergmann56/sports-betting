-- gambling_model_data — versioned, append-only model-input store (MySQL 8.0+ / Azure Database for MySQL)
--
-- Scope: historical games, odds snapshots, team ratings, pregame feature snapshots, model
-- releases, predictions and evaluation results. OUT OF SCOPE BY DESIGN: sportsbook wagers,
-- tickets, account transactions, balances, bonuses and any personal account data — those
-- live in a separate accounts database with separate credentials (docs/model-data/README.md).
--
-- Immutability: every evidence table is append-only; triggers reject UPDATE and DELETE.
-- Lifecycle changes (publish, supersede, retract) are appended to dataset_version_events.
-- Statement separator for the migration runner: a line that is exactly two dashes, a space and two semicolons.

CREATE TABLE schema_versions (
  version        INT          NOT NULL PRIMARY KEY,
  name           VARCHAR(200) NOT NULL,
  sha256         CHAR(64)     NOT NULL,
  applied_utc    VARCHAR(40)  NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Immutable source evidence: original file bytes keyed by SHA-256.
CREATE TABLE source_files (
  sha256             CHAR(64)      NOT NULL PRIMARY KEY,
  bytes              BIGINT        NOT NULL,
  original_name      VARCHAR(500)  NOT NULL,
  media_type         VARCHAR(100)  NOT NULL,
  sensitivity        VARCHAR(60)   NOT NULL,  -- PUBLIC_MARKET | MODEL_INTERNAL | CONTAINS_USER_OBSERVATION_FLAGS
  provenance         TEXT          NOT NULL,  -- where the file came from (URL, package + path, capture id)
  parent_sha256      CHAR(64)      NULL,      -- e.g. member of an archive ZIP
  parent_member_path VARCHAR(1000) NULL,
  chunk_count        INT           NOT NULL,
  registered_utc     VARCHAR(40)   NOT NULL,
  registered_by      VARCHAR(200)  NOT NULL,
  CONSTRAINT ck_sensitivity CHECK (sensitivity IN ('PUBLIC_MARKET','MODEL_INTERNAL','CONTAINS_USER_OBSERVATION_FLAGS')),
  CONSTRAINT fk_source_parent FOREIGN KEY (parent_sha256) REFERENCES source_files(sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

CREATE TABLE source_file_chunks (
  sha256     CHAR(64) NOT NULL,
  chunk_no   INT      NOT NULL,
  data       LONGBLOB NOT NULL,
  PRIMARY KEY (sha256, chunk_no),
  CONSTRAINT fk_chunk_file FOREIGN KEY (sha256) REFERENCES source_files(sha256)
) ENGINE=InnoDB;
-- ;;

-- Logical datasets (one per kind of data per sport/source).
CREATE TABLE datasets (
  dataset_id   VARCHAR(120) NOT NULL PRIMARY KEY,
  domain       VARCHAR(30)  NOT NULL,  -- games | results | odds | ratings | features | predictions | evaluations | reference | replay_input
  sport        VARCHAR(10)  NULL,
  description  TEXT         NOT NULL,
  created_utc  VARCHAR(40)  NOT NULL,
  CONSTRAINT ck_domain CHECK (domain IN ('games','results','odds','ratings','features','predictions',
                                         'evaluations','reference','replay_input'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Append-only versions. available_from_utc = earliest time the content was knowable
-- (capture time, result time), used for "as known at T" retrieval.
CREATE TABLE dataset_versions (
  version_id          BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  dataset_id          VARCHAR(120)  NOT NULL,
  version_label       VARCHAR(200)  NOT NULL,
  source_sha256       CHAR(64)      NOT NULL,
  parser              VARCHAR(40)   NOT NULL,  -- csv | csv.gz | parquet | json | blob
  available_from_utc  VARCHAR(40)   NULL,
  time_column         VARCHAR(200)  NULL,      -- per-row point-in-time column, if any
  row_count           BIGINT        NOT NULL,
  column_count        INT           NOT NULL,
  content_sha256      CHAR(64)      NOT NULL,  -- sha256 over canonical row hashes in order
  parent_version_id   BIGINT        NULL,
  import_tool         VARCHAR(200)  NOT NULL,
  created_utc         VARCHAR(40)   NOT NULL,
  notes               TEXT          NULL,
  UNIQUE KEY uq_dataset_label (dataset_id, version_label),
  KEY ix_dataset_available (dataset_id, available_from_utc),
  CONSTRAINT fk_version_dataset FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id),
  CONSTRAINT fk_version_source  FOREIGN KEY (source_sha256) REFERENCES source_files(sha256),
  CONSTRAINT fk_version_parent  FOREIGN KEY (parent_version_id) REFERENCES dataset_versions(version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

CREATE TABLE dataset_version_events (
  event_id     BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  version_id   BIGINT       NOT NULL,
  status       VARCHAR(20)  NOT NULL,  -- STAGED | PUBLISHED | SUPERSEDED | RETRACTED
  reason       TEXT         NOT NULL,
  event_utc    VARCHAR(40)  NOT NULL,
  actor        VARCHAR(200) NOT NULL,
  CONSTRAINT ck_status CHECK (status IN ('STAGED','PUBLISHED','SUPERSEDED','RETRACTED')),
  CONSTRAINT fk_event_version FOREIGN KEY (version_id) REFERENCES dataset_versions(version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

CREATE TABLE dataset_columns (
  version_id    BIGINT       NOT NULL,
  ordinal       INT          NOT NULL,
  name          VARCHAR(300) NOT NULL,
  source_dtype  VARCHAR(60)  NOT NULL,
  flagged       VARCHAR(60)  NULL,      -- USER_OBSERVATION_FLAG when name matches the sensitivity guard
  PRIMARY KEY (version_id, ordinal),
  CONSTRAINT fk_col_version FOREIGN KEY (version_id) REFERENCES dataset_versions(version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Lossless row store: every source row exactly as parsed (values as text), in source order.
CREATE TABLE dataset_rows (
  version_id    BIGINT       NOT NULL,
  row_no        BIGINT       NOT NULL,
  row_time_utc  VARCHAR(40)  NULL,      -- value of time_column, if declared
  row_sha256    CHAR(64)     NOT NULL,
  row_json      JSON         NOT NULL,  -- JSON array of values aligned with dataset_columns
  PRIMARY KEY (version_id, row_no),
  KEY ix_row_time (version_id, row_time_utc),
  CONSTRAINT fk_row_version FOREIGN KEY (version_id) REFERENCES dataset_versions(version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Mirror of model releases (authority remains the SQLite registry until migration is validated).
CREATE TABLE model_releases (
  release_id        VARCHAR(120) NOT NULL PRIMARY KEY,
  sport             VARCHAR(10)  NOT NULL,
  markets_json      JSON         NOT NULL,
  artifact_status   VARCHAR(40)  NOT NULL,
  mirrored_from     VARCHAR(300) NOT NULL,   -- e.g. sqlite registry migration 0005 sha256
  mirrored_utc      VARCHAR(40)  NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- A reproducible model run (golden fixture, replay or future live scoring run).
CREATE TABLE model_runs (
  run_id            VARCHAR(160) NOT NULL PRIMARY KEY,
  run_kind          VARCHAR(30)  NOT NULL,   -- GOLDEN_FIXTURE | REPLAY | LIVE | RESEARCH
  release_ids_json  JSON         NOT NULL,
  input_cutoff_utc  VARCHAR(40)  NULL,
  environment_json  JSON         NOT NULL,
  scorer_json       JSON         NOT NULL,   -- scorer files and sha256
  created_utc       VARCHAR(40)  NOT NULL,
  notes             TEXT         NULL,
  CONSTRAINT ck_run_kind CHECK (run_kind IN ('GOLDEN_FIXTURE','REPLAY','LIVE','RESEARCH'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Exactly which inputs a run used, and where the scorer expects each file.
CREATE TABLE run_inputs (
  run_id        VARCHAR(160)  NOT NULL,
  stage_path    VARCHAR(1000) NOT NULL,     -- path relative to the run's working directory
  role          VARCHAR(30)   NOT NULL,     -- INPUT | EXPECTED_OUTPUT | ARCHIVE
  version_id    BIGINT        NULL,
  source_sha256 CHAR(64)      NOT NULL,
  PRIMARY KEY (run_id, stage_path(255)),
  CONSTRAINT fk_ri_run     FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
  CONSTRAINT fk_ri_version FOREIGN KEY (version_id) REFERENCES dataset_versions(version_id),
  CONSTRAINT fk_ri_source  FOREIGN KEY (source_sha256) REFERENCES source_files(sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

CREATE TABLE run_results (
  result_id     BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  run_id        VARCHAR(160) NOT NULL,
  executed_utc  VARCHAR(40)  NOT NULL,
  input_source  VARCHAR(30)  NOT NULL,      -- REPO_FIXTURE | MODEL_DATA_DB
  status        VARCHAR(20)  NOT NULL,      -- PASSED | FAILED | SKIPPED
  report_json   JSON         NOT NULL,
  CONSTRAINT fk_rr_run FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

-- Evaluation results written by research (ChatGPT) or development, linked to exact versions.
CREATE TABLE evaluation_results (
  evaluation_id      BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  release_id         VARCHAR(120) NOT NULL,
  population_version BIGINT       NULL,
  metric             VARCHAR(80)  NOT NULL,
  population         TEXT         NOT NULL,
  value_num          DOUBLE       NULL,
  n_obs              BIGINT       NULL,
  ci_low             DOUBLE       NULL,
  ci_high            DOUBLE       NULL,
  computed_utc       VARCHAR(40)  NOT NULL,
  research_ref       VARCHAR(500) NOT NULL,   -- docs/research/... decision or report path
  CONSTRAINT fk_eval_release FOREIGN KEY (release_id) REFERENCES model_releases(release_id),
  CONSTRAINT fk_eval_version FOREIGN KEY (population_version) REFERENCES dataset_versions(version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- ;;

CREATE VIEW dataset_version_status AS
SELECT v.version_id, v.dataset_id, v.version_label, v.available_from_utc,
       (SELECT e.status FROM dataset_version_events e WHERE e.version_id = v.version_id
         ORDER BY e.event_id DESC LIMIT 1) AS status
FROM dataset_versions v;
-- ;;

-- Append-only enforcement.
CREATE TRIGGER source_files_no_update BEFORE UPDATE ON source_files FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source_files is append-only';
-- ;;
CREATE TRIGGER source_files_no_delete BEFORE DELETE ON source_files FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source_files is append-only';
-- ;;
CREATE TRIGGER source_chunks_no_update BEFORE UPDATE ON source_file_chunks FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source_file_chunks is append-only';
-- ;;
CREATE TRIGGER source_chunks_no_delete BEFORE DELETE ON source_file_chunks FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'source_file_chunks is append-only';
-- ;;
CREATE TRIGGER versions_no_update BEFORE UPDATE ON dataset_versions FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_versions is append-only';
-- ;;
CREATE TRIGGER versions_no_delete BEFORE DELETE ON dataset_versions FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_versions is append-only';
-- ;;
CREATE TRIGGER rows_no_update BEFORE UPDATE ON dataset_rows FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_rows is append-only';
-- ;;
CREATE TRIGGER rows_no_delete BEFORE DELETE ON dataset_rows FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_rows is append-only';
-- ;;
CREATE TRIGGER events_no_update BEFORE UPDATE ON dataset_version_events FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_version_events is append-only';
-- ;;
CREATE TRIGGER events_no_delete BEFORE DELETE ON dataset_version_events FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'dataset_version_events is append-only';
-- ;;
CREATE TRIGGER run_inputs_no_update BEFORE UPDATE ON run_inputs FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'run_inputs is append-only';
-- ;;
CREATE TRIGGER run_inputs_no_delete BEFORE DELETE ON run_inputs FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'run_inputs is append-only';
-- ;;
CREATE TRIGGER runs_no_update BEFORE UPDATE ON model_runs FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'model_runs is append-only';
-- ;;
CREATE TRIGGER runs_no_delete BEFORE DELETE ON model_runs FOR EACH ROW
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'model_runs is append-only';
