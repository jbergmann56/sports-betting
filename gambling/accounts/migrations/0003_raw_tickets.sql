-- DQ-13 raw ticket ledger (gambling/accounts/ledger.py, run inside `accounts cleanse`).
-- One row per Bovada bet reference, built only from raw sportsbook transactions (BGS-SB-*): placement,
-- settlements, unsettlements and voids. It cross-checks the P&L baseline (tickets in both must agree to
-- the cent) and carries the tickets after the baseline cut-off. Written under the cleanse run id only if
-- every gate passes; append-only. Missing coverage is a status, never zero activity.

CREATE TABLE c_raw_tickets (
 run_id INTEGER NOT NULL REFERENCES dq_runs(run_id),
 bovada_reference TEXT NOT NULL,
 ticket_status TEXT NOT NULL CHECK (ticket_status IN ('SETTLED', 'VOID', 'OPEN', 'PLACEMENT_NOT_COVERED')),
 lifecycle TEXT NOT NULL,                 -- JSON list of raw categories in time order, e.g. ["PL","ST","US","ST"]
 raw_transaction_ids TEXT NOT NULL,       -- JSON list
 placed_utc TEXT,                         -- from the raw placement transaction (authoritative)
 placed_date_chicago TEXT,
 settled_utc TEXT,                        -- final settlement or void
 bet_type TEXT,                           -- Single | Double | Treble | 4-Fold ...
 legs INTEGER NOT NULL,
 legs_json TEXT NOT NULL,                 -- per leg: sport, market, selection, price, period, event, event date (tags stripped)
 sport TEXT,                              -- single-leg sport code (NFL/NBA/NHL/NCAAFB/NCAABB) or MULTI
 market TEXT,                             -- Moneyline | Spread | Total | MULTI | other raw text
 market_scope TEXT NOT NULL,              -- MODEL_MARKET | OUT_OF_MODEL_SCOPE (parlays, live, other markets)
 is_live INTEGER NOT NULL,
 matchup TEXT, away TEXT, home TEXT,
 selection TEXT, direction TEXT,
 price_american REAL,
 risk_cents INTEGER NOT NULL,
 to_win_cents INTEGER,
 funds_json TEXT,                         -- placement debit by fund type (BonusFunds / LockedFunds / UnlockedFunds)
 result TEXT NOT NULL CHECK (result IN ('WIN', 'LOSS', 'PUSH', 'VOID', 'OPEN', 'OTHER', 'UNKNOWN')),
 net_pnl_cents INTEGER,                   -- NULL while open
 net_pnl_basis TEXT NOT NULL,             -- RAW_LIFECYCLE | SETTLEMENT_MINUS_RISK | NONE
 baseline_status TEXT NOT NULL CHECK (baseline_status IN ('BASELINE_SETTLED', 'BASELINE_OPEN', 'NOT_IN_BASELINE')),
 period TEXT NOT NULL CHECK (period IN ('THROUGH_BASELINE', 'AFTER_BASELINE', 'UNKNOWN')),
 PRIMARY KEY (run_id, bovada_reference)
);

-- DQ-05 also verifies settlement times against the final raw settlement/void.
ALTER TABLE c_wagers ADD COLUMN settled_time_basis TEXT;

CREATE VIEW raw_tickets AS SELECT * FROM c_raw_tickets WHERE run_id = (SELECT run_id FROM latest_passed_run);

-- Tickets whose P&L the baseline does not yet contain: new tickets, and baseline-open tickets settled since.
CREATE VIEW tickets_after_baseline AS
 SELECT * FROM raw_tickets
 WHERE baseline_status = 'NOT_IN_BASELINE' OR (baseline_status = 'BASELINE_OPEN' AND ticket_status <> 'OPEN');

CREATE TRIGGER c_raw_tickets_no_update BEFORE UPDATE ON c_raw_tickets BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER c_raw_tickets_no_delete BEFORE DELETE ON c_raw_tickets BEGIN SELECT RAISE(ABORT, 'append-only'); END;
