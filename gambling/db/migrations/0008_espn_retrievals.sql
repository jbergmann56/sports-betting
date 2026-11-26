-- Repeat ESPN fetches whose response is byte-identical to one already stored.
--
-- 0007 stored every fetch as a full capture. 0007 is applied to the live database and is frozen,
-- so this migration adds a lightweight table instead: when a fetch returns the same bytes as the
-- latest capture for that sport and date, only the retrieval (URL, time, body hash) is recorded,
-- pointing at that capture. The response, its observations and any finals already exist.
-- A changed response is still stored in full as a new capture.

CREATE TABLE espn_result_retrievals (
 retrieval_id INTEGER PRIMARY KEY AUTOINCREMENT,
 capture_id TEXT NOT NULL REFERENCES espn_result_captures(capture_id),
 url TEXT NOT NULL,
 retrieved_utc TEXT NOT NULL,
 body_sha256 TEXT NOT NULL,
 collector TEXT NOT NULL
);
CREATE INDEX idx_espn_retrievals_capture ON espn_result_retrievals(capture_id);

CREATE TRIGGER espn_result_retrievals_no_update BEFORE UPDATE ON espn_result_retrievals
BEGIN SELECT RAISE(ABORT, 'espn_result_retrievals is append-only'); END;
CREATE TRIGGER espn_result_retrievals_no_delete BEFORE DELETE ON espn_result_retrievals
BEGIN SELECT RAISE(ABORT, 'espn_result_retrievals is append-only'); END;
