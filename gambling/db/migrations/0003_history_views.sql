-- Read-side views over the rolling history.
-- Time ordering uses julianday(): stored UTC stamps mix "Z" and "+00:00" suffixes.

-- Every quote observation joined to its game.
CREATE VIEW quote_observations AS
 SELECT q.quote_id, q.batch_id, q.sport, q.event_id, q.game_key, q.quote_cohort_id,
        q.quote_captured_utc, q.market, q.period, q.side, q.selection, q.line,
        q.odds_american, q.odds_decimal, q.break_even_probability, q.quote_status,
        q.status_detail, q.market_id, q.outcome_id, q.price_id, q.attempt_id,
        q.received_utc, q.source_file,
        e.game, e.away, e.home, e.start_utc, e.pregame_quote, e.physical_game
 FROM market_quotes q
 JOIN events e ON e.batch_id = q.batch_id AND e.sport = q.sport AND e.event_id = q.event_id;

-- One row per distinct snapshot. Two fetch runs that received the same CDN
-- object share a snapshot time (Date - Age) and are the same observation;
-- the earliest-ingested batch is kept.
CREATE VIEW distinct_quote_observations AS
 SELECT * FROM (
   SELECT o.*, julianday(quote_captured_utc) AS captured_julian,
          ROW_NUMBER() OVER (PARTITION BY game_key, market, side, julianday(quote_captured_utc)
                             ORDER BY batch_id) AS duplicate_rank
   FROM quote_observations o)
 WHERE duplicate_rank = 1;

-- Most recent observation of each game/market/side, whatever its status.
CREATE VIEW latest_quotes AS
 SELECT * FROM (
   SELECT o.*, ROW_NUMBER() OVER (PARTITION BY game_key, market, side
                                  ORDER BY captured_julian DESC, batch_id DESC) AS recency_rank
   FROM distinct_quote_observations o)
 WHERE recency_rank = 1;

-- Chronological distinct observations per game/market/side with changes from the previous one.
CREATE VIEW line_movement AS
 SELECT game_key, sport, game, start_utc, market, side, selection, batch_id,
        quote_captured_utc, quote_status, line, odds_american,
        LAG(line) OVER w AS previous_line,
        LAG(odds_american) OVER w AS previous_odds,
        line - LAG(line) OVER w AS line_change,
        odds_american - LAG(odds_american) OVER w AS odds_change,
        ROW_NUMBER() OVER w AS observation_number
 FROM distinct_quote_observations
 WINDOW w AS (PARTITION BY game_key, market, side ORDER BY captured_julian, batch_id);

-- Request outcomes per UTC day and sport: tracks how reliable the Bovada feed is.
CREATE VIEW capture_health AS
 SELECT substr(r.started_utc, 1, 10) AS run_date_utc, a.sport,
        CASE WHEN a.purpose LIKE 'event_recovery:%' THEN 'event_recovery' ELSE a.purpose END AS purpose,
        a.variant, a.outcome, COUNT(*) AS attempts,
        ROUND(AVG(a.cdn_age_seconds), 0) AS avg_cdn_age_seconds
 FROM fetch_attempts a JOIN fetch_runs r ON r.run_id = a.run_id
 GROUP BY 1, 2, 3, 4, 5;

-- Sport-level verdict per run.
CREATE VIEW sport_health AS
 SELECT substr(r.started_utc, 1, 10) AS run_date_utc, s.sport,
        COUNT(*) AS runs,
        SUM(s.status = 'OK') AS ok_runs,
        SUM(s.status = 'NO_EVENTS') AS no_event_runs,
        SUM(s.status = 'BLOCKED') AS blocked_runs,
        SUM(s.status = 'FAILED') AS failed_runs,
        ROUND(AVG(s.pregame_complete * 1.0 / NULLIF(s.pregame_events, 0)), 3) AS avg_complete_share
 FROM sport_fetch_status s JOIN fetch_runs r ON r.run_id = s.run_id
 GROUP BY 1, 2;
