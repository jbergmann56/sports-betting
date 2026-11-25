-- Model registry: which frozen release made each prediction, what its files
-- were, and what authority it held over time.
--
--   model_releases          one row per frozen release (or shared component)
--   model_release_artifacts the files that define it, with sha256
--   model_release_status    append-only history of role / scoring authority /
--                           wagering authorization; the latest row at or before
--                           a time is the status in effect at that time
--   model_release_aliases   maps legacy free-text model_version labels (per
--                           market) onto releases, with the strength of evidence
--   model_scores.release_id direct link for every new score

CREATE TABLE model_releases (
 release_id TEXT PRIMARY KEY,
 sport TEXT NOT NULL,
 markets_json TEXT NOT NULL,
 component_kind TEXT NOT NULL CHECK (component_kind IN ('MODEL', 'SHARED_COMPONENT', 'RESEARCH_BASELINE')),
 description TEXT NOT NULL,
 release_local_date TEXT,
 training_cutoff TEXT,
 artifact_status TEXT NOT NULL CHECK (artifact_status IN
   ('COMPLETE', 'IN_FROZEN_ARCHIVE', 'PARTIAL', 'ARTIFACTS_MISSING')),
 artifact_notes TEXT,
 authority_source TEXT,
 registered_utc TEXT NOT NULL
);

CREATE TABLE model_release_artifacts (
 release_id TEXT NOT NULL REFERENCES model_releases(release_id),
 location TEXT NOT NULL,          -- path under the package root, or zip:<archive>!<member>
 artifact_role TEXT NOT NULL CHECK (artifact_role IN
   ('CODE', 'COEFFICIENTS', 'MODEL_BINARY', 'CONFIG', 'AUTHORITY', 'DATA')),
 sha256 TEXT NOT NULL,
 bytes INTEGER NOT NULL,
 PRIMARY KEY (release_id, location)
);

CREATE TABLE model_release_status (
 status_id INTEGER PRIMARY KEY AUTOINCREMENT,
 release_id TEXT NOT NULL REFERENCES model_releases(release_id),
 role TEXT NOT NULL CHECK (role IN ('CHAMPION', 'CHALLENGER', 'SHADOW', 'RESEARCH', 'RETIRED')),
 scoring_authority INTEGER NOT NULL CHECK (scoring_authority IN (0, 1)),   -- its scores are the official board
 wagering_authorized INTEGER CHECK (wagering_authorized IN (0, 1)),       -- NULL = not documented
 effective_from_utc TEXT NOT NULL,
 evidence_level TEXT NOT NULL CHECK (evidence_level IN ('DOCUMENTED', 'USER_CONFIRMED', 'INFERRED')),
 decision_source TEXT NOT NULL,
 recorded_utc TEXT NOT NULL,
 notes TEXT
);
CREATE INDEX idx_release_status ON model_release_status(release_id, effective_from_utc);

CREATE TABLE model_release_aliases (
 sport TEXT NOT NULL,
 model_version TEXT NOT NULL,     -- legacy label exactly as recorded in model_scores
 market TEXT NOT NULL,            -- 'Moneyline' | 'Spread' | 'Total' | '*'
 release_id TEXT REFERENCES model_releases(release_id),   -- NULL = unresolved
 evidence_level TEXT NOT NULL CHECK (evidence_level IN ('DOCUMENTED', 'USER_CONFIRMED', 'INFERRED', 'UNRESOLVED')),
 evidence TEXT NOT NULL,
 recorded_utc TEXT NOT NULL,
 PRIMARY KEY (sport, model_version, market)
);

ALTER TABLE model_scores ADD COLUMN release_id TEXT REFERENCES model_releases(release_id);

-- New scores on captured runs must name a registered release (legacy rows keep NULL).
CREATE TRIGGER model_scores_require_release BEFORE INSERT ON model_scores
WHEN NEW.release_id IS NULL AND EXISTS (SELECT 1 FROM fetch_runs WHERE batch_id = NEW.batch_id)
BEGIN SELECT RAISE(ABORT, 'model_scores: new scores must reference a registered release_id'); END;

-- A challenger, shadow or research release can never produce a production-qualified score.
CREATE TRIGGER model_scores_authority_check BEFORE INSERT ON model_scores
WHEN NEW.release_id IS NOT NULL AND NEW.action_status = 'PRODUCTION_QUALIFIED' AND NOT EXISTS (
  SELECT 1 FROM model_release_status st
  WHERE st.release_id = NEW.release_id AND st.role = 'CHAMPION' AND st.wagering_authorized = 1
    AND julianday(st.effective_from_utc) <= julianday(NEW.quote_captured_utc)
    AND NOT EXISTS (SELECT 1 FROM model_release_status later
                    WHERE later.release_id = st.release_id
                      AND julianday(later.effective_from_utc) > julianday(st.effective_from_utc)
                      AND julianday(later.effective_from_utc) <= julianday(NEW.quote_captured_utc)))
BEGIN SELECT RAISE(ABORT, 'model_scores: release is not a wagering-authorized champion at quote time'); END;

-- Registry history is append-only like the rest of the evidence.
CREATE TRIGGER model_releases_no_update BEFORE UPDATE ON model_releases BEGIN SELECT RAISE(ABORT, 'model_releases is append-only'); END;
CREATE TRIGGER model_releases_no_delete BEFORE DELETE ON model_releases BEGIN SELECT RAISE(ABORT, 'model_releases is append-only'); END;
CREATE TRIGGER model_release_artifacts_no_update BEFORE UPDATE ON model_release_artifacts BEGIN SELECT RAISE(ABORT, 'model_release_artifacts is append-only'); END;
CREATE TRIGGER model_release_artifacts_no_delete BEFORE DELETE ON model_release_artifacts BEGIN SELECT RAISE(ABORT, 'model_release_artifacts is append-only'); END;
CREATE TRIGGER model_release_status_no_update BEFORE UPDATE ON model_release_status BEGIN SELECT RAISE(ABORT, 'model_release_status is append-only'); END;
CREATE TRIGGER model_release_status_no_delete BEFORE DELETE ON model_release_status BEGIN SELECT RAISE(ABORT, 'model_release_status is append-only'); END;
CREATE TRIGGER model_release_aliases_no_update BEFORE UPDATE ON model_release_aliases BEGIN SELECT RAISE(ABORT, 'model_release_aliases is append-only'); END;
CREATE TRIGGER model_release_aliases_no_delete BEFORE DELETE ON model_release_aliases BEGIN SELECT RAISE(ABORT, 'model_release_aliases is append-only'); END;

-- Status periods: each status row is in effect until the release's next one.
CREATE VIEW release_status_history AS
 SELECT st.*,
        LEAD(effective_from_utc) OVER (PARTITION BY release_id
                                       ORDER BY julianday(effective_from_utc), status_id) AS effective_until_utc
 FROM model_release_status st;

CREATE VIEW current_release_status AS
 SELECT r.sport, r.release_id, r.component_kind, r.markets_json, r.artifact_status,
        h.role, h.scoring_authority, h.wagering_authorized, h.effective_from_utc,
        h.evidence_level, h.decision_source
 FROM model_releases r
 LEFT JOIN release_status_history h ON h.release_id = r.release_id AND h.effective_until_utc IS NULL;

-- Every recorded score with the release that made it (direct link, else alias).
CREATE VIEW model_score_attribution AS
 SELECT s.score_id, s.batch_id, s.sport, s.event_id, s.game_key, s.quote_cohort_id,
        s.quote_captured_utc, s.market, s.selection_side, s.selection_display, s.quote_id,
        s.quoted_line, s.quoted_odds, s.model_role AS recorded_role, s.model_version AS recorded_label,
        COALESCE(s.release_id, a.release_id) AS release_id,
        CASE WHEN s.release_id IS NOT NULL THEN 'DIRECT'
             WHEN a.release_id IS NOT NULL THEN a.evidence_level
             ELSE 'UNRESOLVED' END AS attribution,
        s.tier, s.model_probability, s.expected_value, s.full_kelly, s.adjusted_kelly,
        s.adjusted_kelly_status, s.production_authorized, s.action_status, s.pass_or_block_reason
 FROM model_scores s
 LEFT JOIN model_release_aliases a
   ON a.sport = s.sport AND a.model_version = s.model_version AND a.market IN (s.market, '*');

-- One row per distinct prediction. The legacy NCAAFB scorer stored shared
-- components (ML rule, totals research) once under the champion configuration
-- and again under the challenger one; those copies are the same prediction by
-- the same release and collapse here. The champion copy's recorded status is
-- kept (original pre-bet authorization). Raw rows remain in model_scores.
CREATE VIEW model_predictions AS
 SELECT p.*,
        (SELECT h.role FROM release_status_history h
          WHERE h.release_id = p.release_id
            AND julianday(h.effective_from_utc) <= julianday(p.quote_captured_utc)
            AND (h.effective_until_utc IS NULL OR julianday(h.effective_until_utc) > julianday(p.quote_captured_utc))
        ) AS registry_role_at_quote,
        (SELECT h.wagering_authorized FROM release_status_history h
          WHERE h.release_id = p.release_id
            AND julianday(h.effective_from_utc) <= julianday(p.quote_captured_utc)
            AND (h.effective_until_utc IS NULL OR julianday(h.effective_until_utc) > julianday(p.quote_captured_utc))
        ) AS registry_wagering_at_quote
 FROM (
   SELECT m.*,
          COUNT(*) OVER k AS recorded_rows,
          GROUP_CONCAT(m.recorded_role, ',') OVER k AS recorded_roles,
          ROW_NUMBER() OVER (PARTITION BY m.batch_id, m.sport, m.event_id, m.market,
                                          COALESCE(m.selection_side, ''), COALESCE(m.selection_display, ''),
                                          COALESCE(m.quote_id, ''), COALESCE(m.release_id, m.recorded_label)
                             ORDER BY CASE m.recorded_role WHEN 'CHAMPION' THEN 0 ELSE 1 END, m.score_id) AS copy_rank
   FROM model_score_attribution m
   WINDOW k AS (PARTITION BY m.batch_id, m.sport, m.event_id, m.market,
                             COALESCE(m.selection_side, ''), COALESCE(m.selection_display, ''),
                             COALESCE(m.quote_id, ''), COALESCE(m.release_id, m.recorded_label)
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
 ) p
 WHERE p.copy_rank = 1;
