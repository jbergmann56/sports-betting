"""Rolling SQLite history: migrations, frozen baseline import, ingest, append-only rules."""

import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from gambling.bovada import FetchConfig, fetch_board
from gambling.config import Paths, default_paths
from gambling.db import IngestError, MigrationError, apply_migrations, connect, ingest_capture, init_database
from gambling.db.export import export_snapshot
from gambling.db.ingest import pending_captures
from gambling.db.migrate import available_migrations
from gambling.db.models import attribution_summary, current_releases, release_detail, verify_artifacts
from gambling.db.queries import capture_health, latest_quotes, line_history, status
from gambling.history import connect_frozen, frozen_scores

from test_bovada import FAST, FakeTransport, board_with, nba_events, nba_url, response

FROZEN_COUNTS = {"capture_batches": 28, "events": 1156, "market_quotes": 6936,
                 "model_scores": 10173, "settlements": 148}


def fresh_db(tmp: Path) -> sqlite3.Connection:
    con = connect(tmp / "test.sqlite")
    apply_migrations(con)
    return con


def capture_run(root: Path, events, *, age=60, odds_override=None):
    """Write a real capture directory using the fetcher with a scripted transport."""
    events = [dict(e) for e in events]
    if odds_override is not None:
        events[0]["displayGroups"][0]["markets"][0]["outcomes"][0]["price"]["american"] = odds_override
    transport = FakeTransport({nba_url(0): [response("", body=board_with(events), age=age)]},
                              default=response("", body=b"{}", age=99999))
    return fetch_board(["NBA"], root, config=FetchConfig(policy=FAST), transport=transport,
                       sleep=lambda _: None, rand=lambda: 0.5)


class Migrations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def connect(self, name):
        con = connect(self.root / name)
        self.addCleanup(con.close)  # cleanups run LIFO: connections close before the folder is removed
        return con

    def test_fresh_database_gets_all_migrations_recorded(self):
        con = self.connect("test.sqlite")
        apply_migrations(con)
        rows = con.execute("SELECT version, sha256 FROM schema_migrations ORDER BY version").fetchall()
        self.assertEqual([r["version"] for r in rows], [m.version for m in available_migrations()])
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(rows))
        self.assertEqual(apply_migrations(con), [])  # idempotent

    def test_baseline_schema_matches_frozen_archive(self):
        con = self.connect("base.sqlite")
        con.executescript(available_migrations()[0].sql)
        with connect_frozen(default_paths()) as frozen:
            expected = {(r[0], r[1]): r[2] for r in frozen.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
        actual = {(r[0], r[1]): r[2] for r in con.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")}
        self.assertEqual(actual, expected)

    def test_edited_migration_is_refused(self):
        migrations = self.root / "migrations"
        shutil.copytree(Path(available_migrations.__code__.co_filename).parent / "migrations", migrations)
        con = self.connect("m.sqlite")
        apply_migrations(con, migrations)
        first = sorted(migrations.glob("0001_*.sql"))[0]
        first.write_text(first.read_text() + "\n-- sneaky edit\n")
        with self.assertRaises(MigrationError):
            apply_migrations(con, migrations)

    def test_crlf_checkout_is_not_an_edit(self):
        migrations = self.root / "migrations"
        shutil.copytree(Path(available_migrations.__code__.co_filename).parent / "migrations", migrations)
        con = self.connect("m.sqlite")
        apply_migrations(con, migrations)
        for path in migrations.glob("*.sql"):
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertEqual(apply_migrations(con, migrations), [])


class FrozenBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        source = default_paths()
        cls.paths = Paths(Path(cls.tmp.name))
        shutil.copy(source.frozen_archive, cls.paths.frozen_archive)
        cls.result = init_database(cls.paths)
        cls.con = connect(cls.paths.database)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def test_counts_match_frozen_archive(self):
        counts = self.result["baseline_imported_counts"]
        for table, expected in FROZEN_COUNTS.items():
            self.assertEqual(counts[table], expected, table)
        report = status(self.con)
        self.assertEqual(report["integrity"], "ok")
        self.assertEqual(report["foreign_key_errors"], 0)
        self.assertEqual(len(report["imports"]), 1)

    def test_frozen_queries_unchanged_on_rolling_db(self):
        self.con.row_factory = sqlite3.Row
        with connect_frozen(default_paths()) as frozen:
            for date, batch in (("2026-11-11", None), ("2026-11-10", "NCAABB_20261110_181149Z_UPDATE")):
                self.assertEqual(frozen_scores(self.con, date, batch), frozen_scores(frozen, date, batch))

    def test_init_is_idempotent(self):
        again = init_database(self.paths)
        self.assertEqual(again["migrations_applied"], [])
        self.assertIsNone(again["baseline_imported_counts"])

    def test_evidence_is_append_only(self):
        for sql in ("UPDATE market_quotes SET odds_american = 999",
                    "DELETE FROM events",
                    "UPDATE model_scores SET tier = 'x'",
                    "DELETE FROM capture_batches"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.con.execute(sql)

    def test_every_recorded_score_is_attributed_to_a_release(self):
        summary = attribution_summary(self.con)
        self.assertEqual(summary["unresolved_labels"], [])
        attributed = self.con.execute("SELECT COUNT(*) FROM model_score_attribution").fetchone()[0]
        self.assertEqual(attributed, FROZEN_COUNTS["model_scores"])  # one alias match per score, no fan-out
        labels = self.con.execute("SELECT COUNT(DISTINCT model_version) FROM model_scores").fetchone()[0]
        mapped = self.con.execute("SELECT COUNT(DISTINCT model_version) FROM model_release_aliases").fetchone()[0]
        self.assertEqual((labels, mapped), (29, 29))

    def test_shared_ncaafb_components_collapse_to_one_prediction(self):
        summary = attribution_summary(self.con)
        self.assertEqual(summary["distinct_predictions"], FROZEN_COUNTS["model_scores"] - 858)
        collapsed = {(r["release_id"], r["extra_copies"]) for r in summary["collapsed_copies"]}
        self.assertEqual(collapsed, {("NCAAFB_ML_W8PLUS_RULE", 429), ("NCAAFB_OU_RESEARCH", 429)})
        # The Nov 9-10 shared ML picks: 22 recorded production rows are 11 distinct picks.
        rows = self.con.execute(
            "SELECT COUNT(*) FROM model_scores WHERE model_version IN "
            "('EXISTING-W8PLUS-ML-UNCHANGED', 'SHARED-ML-COMPONENT; no distinct ML challenger adopted') "
            "AND action_status = 'PRODUCTION_QUALIFIED'").fetchone()[0]
        picks = self.con.execute(
            "SELECT COUNT(*) FROM model_predictions WHERE recorded_label IN "
            "('EXISTING-W8PLUS-ML-UNCHANGED', 'SHARED-ML-COMPONENT; no distinct ML challenger adopted') "
            "AND action_status = 'PRODUCTION_QUALIFIED'").fetchone()[0]
        self.assertEqual((rows, picks), (22, 11))
        # Kept copy is the champion's (original pre-bet authorization).
        roles = {r[0] for r in self.con.execute(
            "SELECT recorded_role FROM model_predictions WHERE recorded_rows > 1")}
        self.assertEqual(roles, {"CHAMPION"})

    def test_registry_role_at_quote_time(self):
        nba = release_detail(self.con, "NBA_R4_V27_20261030")
        self.assertEqual(nba["status_history"][0]["role"], "CHAMPION")
        self.assertEqual(nba["release"]["artifact_status"], "COMPLETE")
        nhl = {r["release_id"]: r for r in current_releases(self.con, "NHL")}
        self.assertEqual(nhl["NHL_ML_DAY0_V1_20261025"]["wagering_authorized"], 0)
        self.assertEqual(nhl["NHL_ML_DAY0_V1_20261025"]["role"], "CHAMPION")
        mismatched = self.con.execute(
            "SELECT COUNT(*) FROM model_predictions WHERE action_status = 'PRODUCTION_QUALIFIED' "
            "AND (registry_role_at_quote <> 'CHAMPION' OR registry_wagering_at_quote <> 1)").fetchone()[0]
        self.assertEqual(mismatched, 0)  # every recorded production pick came from a betting-authorized champion

    def test_registered_artifacts_verify(self):
        result = verify_artifacts(self.con)
        self.assertTrue(result["all_verified"], [r for r in result["releases"] if r["status"] == "FAILED"])

    def test_export_writes_new_archive_with_manifest(self):
        target = export_snapshot(self.con, self.paths.archives)
        with zipfile.ZipFile(target) as archive:
            manifest = json.loads(archive.read("MANIFEST.json"))
            self.assertIn("gambling.sqlite", archive.namelist())
        self.assertEqual(manifest["counts"]["events"], FROZEN_COUNTS["events"])
        self.assertEqual(len(manifest["migrations"]), len(available_migrations()))


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.captures = self.root / "captures"
        self.con = fresh_db(self.root)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_ingest_writes_run_attempts_events_and_quotes(self):
        run = capture_run(self.captures, nba_events())
        result = ingest_capture(self.con, run.run_dir)
        self.assertEqual(result["status"], "INGESTED")
        self.assertEqual((result["events"], result["quotes"]), (10, 60))
        count = lambda t: self.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        self.assertEqual(count("fetch_attempts"), len(run.sports["NBA"].attempts))
        self.assertEqual(count("sport_fetch_status"), 1)
        quote = self.con.execute("SELECT * FROM market_quotes WHERE market='Spread' AND side='Away' LIMIT 1").fetchone()
        self.assertEqual(quote["quote_status"], "OFFERED_PREGAME")
        self.assertTrue(quote["price_id"] and quote["outcome_id"] and quote["market_id"])
        self.assertEqual(quote["quote_captured_utc"], "2026-11-11T18:54:00+00:00")  # Date - Age, not fetch time
        self.assertEqual(quote["source_file"], f"{run.run_id}/board.json")
        attempt = self.con.execute("SELECT * FROM fetch_attempts WHERE attempt_id=?", (quote["attempt_id"],)).fetchone()
        self.assertTrue((run.run_dir / attempt["body_file"]).exists())  # raw body stays a file
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reingest_is_noop_and_tampering_is_rejected(self):
        run = capture_run(self.captures, nba_events())
        ingest_capture(self.con, run.run_dir)
        self.assertEqual(ingest_capture(self.con, run.run_dir)["status"], "ALREADY_INGESTED")
        board = run.run_dir / "board.json"
        board.write_text(board.read_text().replace("Boston Celtics", "Boston Celtix"))
        with self.assertRaises(IngestError):
            ingest_capture(self.con, run.run_dir)

    def test_tampered_raw_body_blocks_ingest(self):
        run = capture_run(self.captures, nba_events())
        body = sorted(run.run_dir.glob("*.body"))[0]
        body.write_bytes(b"tampered")
        with self.assertRaises(IngestError):
            ingest_capture(self.con, run.run_dir)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0], 0)

    def test_failed_run_still_recorded_for_health(self):
        transport = FakeTransport(default=response("", 503, b"busy"))
        run = fetch_board(["NBA"], self.captures, config=FetchConfig(policy=FAST), transport=transport,
                          sleep=lambda _: None, rand=lambda: 0.5)
        result = ingest_capture(self.con, run.run_dir)
        self.assertEqual(result["events"], 0)
        health = capture_health(self.con)
        self.assertEqual(health["sports"][0]["failed_runs"], 1)
        self.assertEqual(self.con.execute("SELECT batch_id FROM fetch_runs").fetchone()[0], None)

    def test_rolling_history_tracks_line_movement(self):
        first = capture_run(self.captures, nba_events(), age=600)
        second = capture_run(self.captures, nba_events(), age=5, odds_override="+250")
        self.assertEqual([p.name for p in pending_captures(self.con, self.captures)],
                         sorted([first.run_id, second.run_id]))
        for run in (first, second):
            ingest_capture(self.con, run.run_dir)
        self.assertEqual(pending_captures(self.con, self.captures), [])
        game_key = f"NBA:BOVADA:{nba_events()[0]['id']}"
        history = [r for r in line_history(self.con, game_key) if r["market"] == "Spread" and r["side"] == "Away"]
        self.assertEqual([r["observation_number"] for r in history], [1, 2])
        self.assertEqual(history[1]["odds_american"], 250)
        self.assertIsNotNone(history[1]["odds_change"])
        latest = [r for r in latest_quotes(self.con, "NBA", upcoming_after="2026-11-11T00:00:00+00:00")
                  if r["game_key"] == game_key and r["market"] == "Spread" and r["side"] == "Away"]
        self.assertEqual(latest[0]["odds_american"], 250)

    def test_same_cdn_snapshot_counts_once(self):
        # Two runs receiving the same cached object have the same Date - Age snapshot time.
        first = capture_run(self.captures, nba_events(), age=60)
        second = capture_run(self.captures, nba_events(), age=60)
        for run in (first, second):
            ingest_capture(self.con, run.run_dir)
        game_key = f"NBA:BOVADA:{nba_events()[0]['id']}"
        history = [r for r in line_history(self.con, game_key) if r["market"] == "Total" and r["side"] == "Over"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["batch_id"], min(first.run_id, second.run_id))
        raw = self.con.execute("SELECT COUNT(*) FROM market_quotes WHERE game_key=? AND market='Total' "
                               "AND side='Over'", (game_key,)).fetchone()[0]
        self.assertEqual(raw, 2)  # both fetches are still recorded as evidence

    def _score(self, run, *, release_id, role, status, score_id):
        quote = self.con.execute("SELECT * FROM market_quotes WHERE batch_id=? AND market='Moneyline' "
                                 "AND side='Away' LIMIT 1", (run.run_id,)).fetchone()
        self.con.execute(
            "INSERT INTO model_scores (score_id, batch_id, sport, event_id, game_key, quote_cohort_id, "
            "quote_captured_utc, scored_time_provenance, market, selection_side, quote_id, quoted_odds, "
            "model_role, model_version, production_authorized, action_status, source_file, source_sha256, "
            "source_row_json, release_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (score_id, quote["batch_id"], quote["sport"], quote["event_id"], quote["game_key"],
             quote["quote_cohort_id"], quote["quote_captured_utc"], "TEST", "Moneyline", "Away",
             quote["quote_id"], quote["odds_american"], role, release_id or "unregistered",
             int(status == "PRODUCTION_QUALIFIED"), status, "test", "0" * 64, "{}", release_id))

    def test_new_scores_must_name_a_release_with_matching_authority(self):
        run = capture_run(self.captures, nba_events())
        ingest_capture(self.con, run.run_dir)
        with self.assertRaises(sqlite3.IntegrityError):  # no release
            self._score(run, release_id=None, role="CHAMPION", status="PASS", score_id="s1")
        with self.assertRaises(sqlite3.IntegrityError):  # challenger cannot be production-qualified
            self._score(run, release_id="NBA_R3_20261029", role="CHALLENGER",
                        status="PRODUCTION_QUALIFIED", score_id="s2")
        self._score(run, release_id="NBA_R3_20261029", role="CHALLENGER", status="RESEARCH_POSITIVE_EV", score_id="s3")
        self._score(run, release_id="NBA_R4_V27_20261030", role="CHAMPION", status="PRODUCTION_QUALIFIED", score_id="s4")
        attributed = dict(self.con.execute(
            "SELECT score_id, attribution FROM model_score_attribution WHERE score_id IN ('s3','s4')").fetchall())
        self.assertEqual(attributed, {"s3": "DIRECT", "s4": "DIRECT"})

    def test_new_quotes_must_use_controlled_status_vocabulary(self):
        run = capture_run(self.captures, nba_events())
        board = json.loads((run.run_dir / "board.json").read_text())
        board[0]["quotes"][0]["quote_status"] = "PROBABLY_FINE"
        (run.run_dir / "board.json").write_text(json.dumps(board))
        with self.assertRaises(sqlite3.IntegrityError):
            ingest_capture(self.con, run.run_dir)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM market_quotes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
