-- Accounts database (data/accounts/accounts.sqlite), SEPARATE from the model scoring database.
-- Raw layer: Bovada exporter output exactly as received, plus the frozen P&L baseline.
-- Nothing here is cleansed; DQ-01..DQ-12 transformations go into later tables that reference
-- these rows. Everything is append-only.
--
--   import_runs            one row per `accounts import` invocation (tool, profile, counts)
--   export_runs            one row per exporter run (stem): window, status, file hashes
--   export_files           the four files of each run, verbatim bytes + SHA-256
--   raw_pages              each line of <stem>_pages.jsonl, verbatim
--   raw_transactions       each DISTINCT version of a transaction (id + content hash), canonical JSON
--   transaction_sightings  every place a version was seen (run, page, position)
--   coverage_windows       covered / failed-attempt windows; uncovered time is never zero activity
--   pnl_baseline_imports   the frozen P&L baseline file (hash, row counts); its tables are copied
--                          verbatim as pnl_baseline_<table> by the importer

CREATE TABLE import_runs (
 import_id INTEGER PRIMARY KEY AUTOINCREMENT,
 started_utc TEXT NOT NULL,
 tool TEXT NOT NULL,
 export_dir TEXT NOT NULL,
 profile_json TEXT NOT NULL,
 counts_json TEXT NOT NULL
);

CREATE TABLE export_runs (
 stem TEXT PRIMARY KEY,
 created_at_from_utc TEXT,
 started_at_utc TEXT,
 finished_at_utc TEXT,
 stopped_because TEXT,
 status TEXT NOT NULL CHECK (status IN ('COMPLETE', 'FAILED_NO_DATA', 'PARTIAL', 'NOT_USABLE')),
 pages INTEGER,
 raw_items INTEGER,
 unique_ids INTEGER,
 issues_json TEXT NOT NULL,
 import_id INTEGER NOT NULL REFERENCES import_runs(import_id)
);

CREATE TABLE export_files (
 stem TEXT NOT NULL REFERENCES export_runs(stem),
 role TEXT NOT NULL CHECK (role IN ('pages', 'run', 'json', 'csv')),
 file_name TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 bytes INTEGER NOT NULL,
 content BLOB NOT NULL,
 PRIMARY KEY (stem, role)
);

CREATE TABLE raw_pages (
 stem TEXT NOT NULL REFERENCES export_runs(stem),
 line_no INTEGER NOT NULL,
 page_no INTEGER,
 items INTEGER NOT NULL,
 line_sha256 TEXT NOT NULL,
 line_text TEXT NOT NULL,
 PRIMARY KEY (stem, line_no)
);

CREATE TABLE raw_transactions (
 transaction_id TEXT NOT NULL,
 version_sha256 TEXT NOT NULL,          -- sha256 of the canonical JSON (sorted keys)
 item_json TEXT NOT NULL,               -- canonical JSON of the item exactly as received
 timestamp_raw TEXT,
 timestamp_utc TEXT,
 wallet_category TEXT,
 wallet_currency TEXT,
 delta_total TEXT,                      -- decimal strings as received, never floats
 balance_total TEXT,
 product_group_id TEXT,
 first_seen_stem TEXT NOT NULL REFERENCES export_runs(stem),
 PRIMARY KEY (transaction_id, version_sha256)
);
CREATE INDEX idx_raw_tx_time ON raw_transactions(timestamp_utc);

CREATE TABLE transaction_sightings (
 transaction_id TEXT NOT NULL,
 version_sha256 TEXT NOT NULL,
 stem TEXT NOT NULL REFERENCES export_runs(stem),
 line_no INTEGER NOT NULL,
 position INTEGER NOT NULL,
 PRIMARY KEY (stem, line_no, position),
 FOREIGN KEY (transaction_id, version_sha256) REFERENCES raw_transactions(transaction_id, version_sha256)
);

CREATE TABLE coverage_windows (
 stem TEXT PRIMARY KEY REFERENCES export_runs(stem),
 from_utc TEXT,
 to_utc TEXT,
 covers INTEGER NOT NULL,               -- 1 only for COMPLETE runs
 status TEXT NOT NULL
);

CREATE TABLE pnl_baseline_imports (
 baseline_sha256 TEXT PRIMARY KEY,
 file_name TEXT NOT NULL,
 bytes INTEGER NOT NULL,
 tables_json TEXT NOT NULL,             -- {table: row_count}
 import_id INTEGER NOT NULL REFERENCES import_runs(import_id)
);

-- Latest version of each transaction (by the export run window it was last seen in).
CREATE VIEW latest_transactions AS
SELECT t.* FROM raw_transactions t
WHERE t.version_sha256 = (
  SELECT s.version_sha256 FROM transaction_sightings s JOIN export_runs r ON r.stem = s.stem
  WHERE s.transaction_id = t.transaction_id
  ORDER BY r.finished_at_utc DESC, s.stem DESC LIMIT 1);

CREATE TRIGGER import_runs_no_update BEFORE UPDATE ON import_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER import_runs_no_delete BEFORE DELETE ON import_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER export_runs_no_update BEFORE UPDATE ON export_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER export_runs_no_delete BEFORE DELETE ON export_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER export_files_no_update BEFORE UPDATE ON export_files BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER export_files_no_delete BEFORE DELETE ON export_files BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER raw_pages_no_update BEFORE UPDATE ON raw_pages BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER raw_pages_no_delete BEFORE DELETE ON raw_pages BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER raw_transactions_no_update BEFORE UPDATE ON raw_transactions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER raw_transactions_no_delete BEFORE DELETE ON raw_transactions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER transaction_sightings_no_update BEFORE UPDATE ON transaction_sightings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER transaction_sightings_no_delete BEFORE DELETE ON transaction_sightings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER coverage_windows_no_update BEFORE UPDATE ON coverage_windows BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER coverage_windows_no_delete BEFORE DELETE ON coverage_windows BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER pnl_baseline_imports_no_update BEFORE UPDATE ON pnl_baseline_imports BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER pnl_baseline_imports_no_delete BEFORE DELETE ON pnl_baseline_imports BEGIN SELECT RAISE(ABORT, 'append-only'); END;
