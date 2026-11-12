-- Baseline: the exact schema of the frozen Nov 11, 2026 rolling history archive
-- (GAMBLING_ROLLING_SCORING_HISTORY.sqlite, Library version 28). Do not edit;
-- later changes belong in new numbered migrations.

CREATE TABLE capture_batches (
 batch_id TEXT PRIMARY KEY, source_name TEXT NOT NULL,
 min_quote_utc TEXT NOT NULL, max_quote_utc TEXT NOT NULL,
 quote_skew_seconds REAL NOT NULL, coherent_all_sports INTEGER NOT NULL,
 cohort_max_seconds INTEGER NOT NULL, source_snapshot_library_id TEXT,
 ingested_utc TEXT NOT NULL, notes TEXT
);
CREATE TABLE quote_cohorts (
 cohort_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
 min_quote_utc TEXT NOT NULL, max_quote_utc TEXT NOT NULL,
 quote_skew_seconds REAL NOT NULL, sports_json TEXT NOT NULL,
 physical_games INTEGER NOT NULL, FOREIGN KEY (batch_id) REFERENCES capture_batches(batch_id)
);
CREATE TABLE events (
 batch_id TEXT NOT NULL, sport TEXT NOT NULL, event_id TEXT NOT NULL,
 game_key TEXT NOT NULL, game TEXT NOT NULL, away TEXT NOT NULL, home TEXT NOT NULL,
 start_utc TEXT, quote_captured_utc TEXT NOT NULL, quote_cohort_id TEXT NOT NULL,
 pregame_quote INTEGER NOT NULL, physical_game INTEGER NOT NULL,
 bovada_url TEXT, raw_board_json TEXT NOT NULL,
 PRIMARY KEY(batch_id,sport,event_id),
 FOREIGN KEY(batch_id) REFERENCES capture_batches(batch_id),
 FOREIGN KEY(quote_cohort_id) REFERENCES quote_cohorts(cohort_id)
);
CREATE TABLE market_quotes (
 quote_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, sport TEXT NOT NULL,
 event_id TEXT NOT NULL, game_key TEXT NOT NULL, quote_cohort_id TEXT NOT NULL,
 quote_captured_utc TEXT NOT NULL, market TEXT NOT NULL, period TEXT NOT NULL,
 side TEXT NOT NULL, line REAL, odds_american REAL, break_even_probability REAL,
 quote_status TEXT NOT NULL, source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 FOREIGN KEY(batch_id,sport,event_id) REFERENCES events(batch_id,sport,event_id)
);
CREATE TABLE model_scores (
 score_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, sport TEXT NOT NULL,
 event_id TEXT NOT NULL, game_key TEXT NOT NULL, quote_cohort_id TEXT NOT NULL,
 quote_captured_utc TEXT NOT NULL, scored_at_utc TEXT,
 scored_time_provenance TEXT NOT NULL, model_probability_asof_utc TEXT,
 market TEXT NOT NULL, selection_side TEXT, selection_display TEXT,
 quote_id TEXT, quoted_line REAL, quoted_odds REAL,
 model_role TEXT NOT NULL, model_version TEXT NOT NULL, tier TEXT,
 model_probability REAL, model_probability_provenance TEXT,
 expected_value REAL, full_kelly REAL, adjusted_kelly REAL,
 adjusted_kelly_status TEXT, production_authorized INTEGER NOT NULL,
 action_status TEXT NOT NULL, pass_or_block_reason TEXT,
 model_health TEXT, source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 source_row_json TEXT NOT NULL,
 FOREIGN KEY(batch_id,sport,event_id) REFERENCES events(batch_id,sport,event_id),
 FOREIGN KEY(quote_id) REFERENCES market_quotes(quote_id)
);
CREATE TABLE source_files (
 batch_id TEXT NOT NULL, source_name TEXT NOT NULL, file_sha256 TEXT NOT NULL,
 source_library_id TEXT, PRIMARY KEY(batch_id,source_name),
 FOREIGN KEY(batch_id) REFERENCES capture_batches(batch_id)
);
CREATE TABLE settlements (
 game_key TEXT NOT NULL, sportsbook_event_id TEXT,
 final_away_score REAL, final_home_score REAL, settled_at_utc TEXT,
 result_source TEXT, PRIMARY KEY(game_key)
);
CREATE TABLE wager_links (
 wager_id TEXT NOT NULL, score_id TEXT NOT NULL, linked_at_utc TEXT NOT NULL,
 basis TEXT NOT NULL, PRIMARY KEY(wager_id,score_id),
 FOREIGN KEY(score_id) REFERENCES model_scores(score_id)
);
CREATE TABLE official_game_results (sport TEXT,espn_game_id TEXT,game_date TEXT,away_id TEXT,home_id TEXT,away_team TEXT,home_team TEXT,away_score INTEGER,home_score INTEGER,status TEXT,observed_utc TEXT,source_file TEXT,PRIMARY KEY(sport,espn_game_id));
CREATE TABLE quote_outcomes (
 quote_id TEXT PRIMARY KEY REFERENCES market_quotes(quote_id), game_key TEXT NOT NULL,
 result TEXT NOT NULL, hypothetical_unit_net REAL, graded_from TEXT NOT NULL);

CREATE INDEX idx_quote_time ON market_quotes(quote_captured_utc,sport);
CREATE INDEX idx_cohort_market ON market_quotes(quote_cohort_id,market);
CREATE INDEX idx_scores_status ON model_scores(sport,model_role,action_status);
CREATE INDEX idx_scores_cohort ON model_scores(quote_cohort_id,action_status);

CREATE VIEW game_scoring_coverage AS
 SELECT e.batch_id, e.sport, e.event_id, e.game_key, e.game,
        e.start_utc, e.quote_captured_utc, e.quote_cohort_id,
        e.pregame_quote, e.physical_game,
        COUNT(s.score_id) AS model_score_rows,
        CASE WHEN COUNT(s.score_id)=0 THEN 'UNSCORED'
             WHEN SUM(CASE WHEN s.action_status='PRODUCTION_QUALIFIED' THEN 1 ELSE 0 END)>0
                  THEN 'HAS_PRODUCTION_QUALIFIER'
             WHEN SUM(CASE WHEN s.action_status='RESEARCH_POSITIVE_EV' THEN 1 ELSE 0 END)>0
                  THEN 'RESEARCH_ONLY_OR_PASS'
             ELSE 'ALL_PASS' END AS game_status
 FROM events e LEFT JOIN model_scores s
   ON e.batch_id=s.batch_id AND e.sport=s.sport AND e.event_id=s.event_id
 GROUP BY e.batch_id,e.sport,e.event_id;
CREATE VIEW model_score_outcomes AS
 SELECT s.*,q.result AS graded_result,q.hypothetical_unit_net,
        f.final_away_score,f.final_home_score,f.result_source
 FROM model_scores s LEFT JOIN quote_outcomes q ON s.quote_id=q.quote_id
 LEFT JOIN settlements f ON s.game_key=f.game_key;
