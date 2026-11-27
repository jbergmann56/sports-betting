-- DQ-14 raw non-sports ledger (gambling/accounts/nonsports.py, run inside `accounts cleanse`).
-- One row per raw non-sportsbook transaction (casino, poker, bonuses/points, deposits/withdrawals,
-- internal operations). The treatment of each raw category is LEARNED from the P&L baseline rows that
-- carry the raw transaction id, and every such row must be reproduced to the cent (gate). Rows after the
-- baseline get the learned treatment; a category with no baseline evidence gets a family analogy
-- (flagged) or stays UNCLASSIFIED with NULL P&L. Written only if every gate passes; append-only.

CREATE TABLE c_raw_non_sports (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 transaction_id TEXT NOT NULL,
 timestamp_utc TEXT NOT NULL,
 raw_category TEXT NOT NULL,             -- e.g. CA-PL, PK-PC-MTT, BN-BG, FN-DP-ETH, TR-PA-CRT
 delta_cents INTEGER NOT NULL,           -- wallet delta total (all fund types)
 funds_json TEXT,                        -- delta by fund type
 poker_reference TEXT,                   -- tournament reference (PK-*)
 baseline_row_ref TEXT,                  -- pnl_baseline_non_sports_transactions row, when matched by id
 ledger_category TEXT,                   -- baseline vocabulary: Casino | Poker | Bonuses and rewards | ...
 treatment TEXT NOT NULL CHECK (treatment IN ('RECOGNIZED', 'NON_PNL', 'ZERO', 'OPEN_POKER_STAKE', 'UNCLASSIFIED')),
 recognized_pnl_cents INTEGER,           -- NULL when UNCLASSIFIED
 rule_provenance TEXT NOT NULL CHECK (rule_provenance IN ('BASELINE_ROW', 'BASELINE_RULE', 'ANALOGY', 'NONE')),
 period TEXT NOT NULL CHECK (period IN ('BASELINE_MATCHED', 'BASELINE_PERIOD_UNMATCHED', 'AFTER_BASELINE')),
 PRIMARY KEY (run_id, transaction_id)
);

CREATE VIEW raw_non_sports AS SELECT * FROM c_raw_non_sports WHERE run_id = (SELECT run_id FROM latest_passed_run);
CREATE VIEW non_sports_after_baseline AS SELECT * FROM raw_non_sports WHERE period = 'AFTER_BASELINE';

CREATE TRIGGER c_raw_non_sports_no_update BEFORE UPDATE ON c_raw_non_sports BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_raw_non_sports_no_delete BEFORE DELETE ON c_raw_non_sports BEGIN SELECT RAISE(ABORT, 'append-only'); END;
