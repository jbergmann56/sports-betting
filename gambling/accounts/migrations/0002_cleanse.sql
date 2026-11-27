-- DQ-01..DQ-12 cleanse (gambling/accounts/cleanse.py). Built only from the raw layer (0001): the
-- imported P&L baseline copy (pnl_baseline_*) and raw Bovada transactions. Every run writes a dq_runs
-- row and every rule hit to dq_issues. Canonical rows are written ONLY if all hard gates pass, under
-- that run's id; nothing is overwritten. Reports use the views over the latest passed run.

CREATE TABLE dq_runs (
 run_id INTEGER PRIMARY KEY,
 started_utc TEXT NOT NULL,
 tool TEXT NOT NULL,
 baseline_sha256 TEXT NOT NULL,
 raw_transactions INTEGER NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED')),
 gates_json TEXT NOT NULL,
 summary_json TEXT NOT NULL
);

CREATE TABLE dq_issues (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 seq INTEGER NOT NULL,
 rule_id TEXT NOT NULL,
 severity TEXT NOT NULL CHECK (severity IN ('INFO', 'LOW', 'MEDIUM', 'HIGH', 'GATE')),
 table_name TEXT NOT NULL,
 row_ref TEXT,
 field TEXT,
 raw_value TEXT,
 cleansed_value TEXT,
 action TEXT NOT NULL,
 evidence TEXT,
 PRIMARY KEY (run_id, seq)
);
CREATE INDEX idx_dq_issues_rule ON dq_issues(run_id, rule_id);

CREATE TABLE c_wagers (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 wager_key TEXT NOT NULL,
 baseline_wager_id TEXT NOT NULL,
 bovada_reference TEXT,
 id_match_method TEXT NOT NULL,          -- REFERENCE | REFERENCE_NOT_IN_RAW | TIME_RISK | UNMATCHED
 raw_transaction_ids TEXT,               -- JSON list of matched raw transaction ids
 sport TEXT NOT NULL,
 market_raw TEXT, market TEXT, market_scope TEXT NOT NULL,   -- MODEL_MARKET | OUT_OF_MODEL_SCOPE
 matchup TEXT, away TEXT, home TEXT,
 selection TEXT,
 direction_raw TEXT, direction TEXT, direction_method TEXT,
 odds_raw TEXT, odds_american REAL, odds_status TEXT NOT NULL,  -- RECORDED | RAW_API | BACKSOLVED | UNRECOVERABLE
 stake_cents INTEGER NOT NULL,
 net_pnl_cents INTEGER NOT NULL,
 result_raw TEXT NOT NULL, result TEXT NOT NULL,
 placed_raw TEXT, placed_utc TEXT, placed_precision TEXT NOT NULL,
 placed_time_basis TEXT NOT NULL,         -- RAW_API_CONFIRMED | RAW_API_CORRECTED | BASELINE_UNVERIFIED | BASELINE_DISAGREES_WITH_RAW | NONE
 settled_raw TEXT, settled_utc TEXT, settled_precision TEXT NOT NULL,
 original_frozen_tier TEXT,              -- authorization evidence as recorded (DQ-11)
 prebet_evidence_category TEXT,          -- authorization evidence as recorded (DQ-11)
 retrospective_champion_tier TEXT,       -- champion_tier_current: retrospective classification only (DQ-11)
 retrospective_champion_model TEXT,
 source TEXT NOT NULL,
 source_row_ref TEXT NOT NULL,
 dq_status TEXT NOT NULL,                -- CLEAN | FIXED | FLAGGED
 PRIMARY KEY (run_id, wager_key)
);

CREATE TABLE c_open_wagers (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 wager_key TEXT NOT NULL,
 bovada_reference TEXT,
 sport TEXT, market TEXT, matchup TEXT, selection TEXT,
 odds_american REAL, risk_cents INTEGER NOT NULL,
 placed_utc TEXT,
 placed_time_basis TEXT NOT NULL,
 realized_pnl_cents INTEGER NOT NULL CHECK (realized_pnl_cents = 0),
 source_row_ref TEXT NOT NULL,
 PRIMARY KEY (run_id, wager_key)
);

CREATE TABLE c_accounting_adjustments (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 adjustment_id TEXT NOT NULL,
 kind TEXT NOT NULL,                     -- AGGREGATE_SETTLEMENT | PRIOR_UNALLOCATED
 sport TEXT,
 stake_cents INTEGER NOT NULL,
 recognized_pnl_cents INTEGER NOT NULL,
 date_chicago TEXT,                      -- NULL stays NULL (never dated by inference)
 description TEXT,
 source_row_ref TEXT NOT NULL,
 PRIMARY KEY (run_id, adjustment_id)
);

CREATE TABLE c_accounting_exclusions (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 exclusion_id TEXT NOT NULL,
 bovada_reference TEXT,
 reason TEXT NOT NULL,
 present_in_baseline INTEGER NOT NULL,
 source TEXT NOT NULL,
 PRIMARY KEY (run_id, exclusion_id)
);

CREATE TABLE c_non_sports_ledger (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 ledger_key TEXT NOT NULL,
 key_method TEXT NOT NULL,               -- BOVADA_ID | COMPOSITE
 timestamp_utc TEXT, timestamp_precision TEXT NOT NULL,
 category TEXT NOT NULL,
 activity TEXT,
 wallet_delta_cents INTEGER,
 recognized_pnl_cents INTEGER NOT NULL,
 accounting_treatment TEXT,
 bovada_transaction_id TEXT,
 source_period TEXT,
 source_row_ref TEXT NOT NULL,
 PRIMARY KEY (run_id, ledger_key)
);

CREATE TABLE c_wager_links (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 wager_key TEXT NOT NULL,
 score_id TEXT NOT NULL,                 -- model_scores.score_id in data/gambling.sqlite (separate database)
 score_role TEXT,
 match_grade TEXT NOT NULL,              -- carried through unchanged
 quote_utc TEXT, placed_utc TEXT,
 source_row_ref TEXT NOT NULL,
 PRIMARY KEY (run_id, wager_key, score_id, score_role)
);

CREATE VIEW latest_passed_run AS SELECT MAX(run_id) AS run_id FROM dq_runs WHERE status = 'PASSED';
CREATE VIEW wagers AS SELECT * FROM c_wagers WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW open_wagers AS SELECT * FROM c_open_wagers WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW accounting_adjustments AS SELECT * FROM c_accounting_adjustments WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW accounting_exclusions AS SELECT * FROM c_accounting_exclusions WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW non_sports_ledger AS SELECT * FROM c_non_sports_ledger WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW wager_links AS SELECT * FROM c_wager_links WHERE run_id = (SELECT run_id FROM latest_passed_run);

CREATE TRIGGER dq_runs_no_update BEFORE UPDATE ON dq_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER dq_runs_no_delete BEFORE DELETE ON dq_runs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER dq_issues_no_update BEFORE UPDATE ON dq_issues BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER dq_issues_no_delete BEFORE DELETE ON dq_issues BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_wagers_no_update BEFORE UPDATE ON c_wagers BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_wagers_no_delete BEFORE DELETE ON c_wagers BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_open_wagers_no_update BEFORE UPDATE ON c_open_wagers BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_open_wagers_no_delete BEFORE DELETE ON c_open_wagers BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_accounting_adjustments_no_update BEFORE UPDATE ON c_accounting_adjustments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_accounting_adjustments_no_delete BEFORE DELETE ON c_accounting_adjustments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_accounting_exclusions_no_update BEFORE UPDATE ON c_accounting_exclusions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_accounting_exclusions_no_delete BEFORE DELETE ON c_accounting_exclusions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_non_sports_ledger_no_update BEFORE UPDATE ON c_non_sports_ledger BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_non_sports_ledger_no_delete BEFORE DELETE ON c_non_sports_ledger BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_wager_links_no_update BEFORE UPDATE ON c_wager_links BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_wager_links_no_delete BEFORE DELETE ON c_wager_links BEGIN SELECT RAISE(ABORT, 'append-only'); END;
