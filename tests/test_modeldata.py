"""Model-input store in the rolling history SQLite database (migration 0006).

Covers immutability, lossless import, time-safe retrieval, run pinning, and how the
md_* tables sit on the existing data model: one release registry, links to capture
batches / quote cohorts / model_scores, game_key joins, no collision with the
existing source_files table. The golden-proof test needs the model environment.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gambling.config import Paths, default_paths
from gambling.db import init_database
from gambling.db.migrate import MigrationError
from gambling.modeldata.store import ModelDataError, open_store, sha256_bytes

CSV = (b"game_id,snapshot_as_of_utc,team,line\n"
       b"1,2026-11-10T13:00:00+00:00,\"A, Inc\",-3.5\n"
       b"2,2026-11-11T13:00:00+00:00,B,\n"
       b"3,,C,7\n")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = open_store(Path(self.tmp.name) / "gambling.sqlite")
        self.addCleanup(self.s.con.close)

    def reg(self, data=CSV, name="odds.csv", sens="PUBLIC_MARKET"):
        return self.s.register_source(data, name, sens, "unit test", "tester")

    # ---------------------------------------------------------------- schema fit
    def test_tables_come_from_the_shared_migrator(self):
        self.assertEqual(self.s.migrate(), [])
        names = [r[0] for r in self.s.fetchall("SELECT name FROM schema_migrations ORDER BY version")]
        self.assertEqual(names[-1], "model_data")
        tables = {r[0] for r in self.s.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("schema_versions", tables)  # no second migration system
        self.assertIn("md_source_files", tables)

    def test_existing_source_files_table_is_untouched(self):
        cols = [r[1] for r in self.s.fetchall("PRAGMA table_info(source_files)")]
        self.assertEqual(cols, ["batch_id", "source_name", "file_sha256", "source_library_id"])
        self.reg()
        self.assertEqual(self.s.fetchone("SELECT COUNT(*) FROM source_files")[0], 0)

    def test_runs_use_the_existing_release_registry(self):
        self.s.register_run("r1", "REPLAY", ["NFL_REV2_CAL_20261024", "NFL_W8_FULL_SLOPE_20261026"], {}, [],
                            sport="NFL")
        self.assertEqual(self.s.run_releases("r1"), ["NFL_REV2_CAL_20261024", "NFL_W8_FULL_SLOPE_20261026"])
        with self.assertRaisesRegex(ModelDataError, "not registered in model_releases"):
            self.s.register_run("r2", "REPLAY", ["NFL_INVENTED_RELEASE"], {}, [])
        self.assertIsNone(self.s.fetchone("SELECT run_id FROM md_model_runs WHERE run_id = 'r2'"))
        before = self.s.fetchone("SELECT COUNT(*) FROM model_releases")[0]
        self.assertEqual(before, 18)  # registering runs never adds releases

    def test_run_links_are_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.register_run("r3", "REPLAY", ["NBA_R4_V27_20261030"], {}, [], batch_id="NO_SUCH_BATCH")
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.register_run("r4", "REPLAY", ["NBA_R4_V27_20261030"], {}, [])
            self.s.link_scores("r4", ["NO_SUCH_SCORE"], "test")

    def test_game_key_column_joins_existing_history(self):
        data = b"game_key,feature\nNBA|2026-11-12|BOS|NYK,0.4\n,0.1\n"
        sha = self.reg(data, "features.csv", "MODEL_INTERNAL")
        self.s.ensure_dataset("t/features", "features", "NBA", "test")
        vid = self.s.import_version("t/features", "v1", sha, "csv", "t", game_key_column="game_key")
        joined = self.s.fetchall("SELECT game_key, sport, version_id FROM md_rows_by_game")
        self.assertEqual(joined, [("NBA|2026-11-12|BOS|NYK", "NBA", vid)])
        with self.assertRaisesRegex(ModelDataError, "game_key_column"):
            self.s.import_version("t/features", "v2", sha, "csv", "t", game_key_column="missing")

    def test_sport_vocabulary_matches_history(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.ensure_dataset("t/bad", "games", "MLB", "test")

    # ---------------------------------------------------------------- store contract
    def test_source_round_trip_is_byte_identical_and_chunked(self):
        big = os.urandom(3 * (1 << 20) + 17)
        sha = self.reg(big, "blob.bin", "MODEL_INTERNAL")
        self.assertEqual(sha, sha256_bytes(big))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.s.materialize_source(sha, Path(d) / "x.bin").read_bytes(), big)
        self.assertEqual(self.s.fetchone("SELECT chunk_count FROM md_source_files WHERE sha256 = ?", (sha,))[0], 4)
        self.assertEqual(self.reg(big, "other-name.bin", "MODEL_INTERNAL"), sha)  # content-addressed

    def test_csv_import_is_lossless_and_time_safe(self):
        sha = self.reg()
        self.s.ensure_dataset("t/odds", "odds", "NFL", "test")
        vid = self.s.import_version("t/odds", "v1", sha, "csv", "tester",
                                    available_from_utc="2026-11-11T14:00:00+00:00", time_column="snapshot_as_of_utc")
        rows = self.s.rows(vid)
        self.assertEqual(rows[0], {"game_id": "1", "snapshot_as_of_utc": "2026-11-10T13:00:00+00:00",
                                   "team": "A, Inc", "line": "-3.5"})
        self.assertEqual(rows[1]["line"], "")  # empty string preserved, not None
        self.assertTrue(self.s.verify_version(vid)["lossless"])
        self.assertEqual([r["game_id"] for r in self.s.rows(vid, as_of_utc="2026-11-10T23:59:59Z")], ["1"])
        self.assertEqual(len(self.s.rows(vid, "2026-11-10T23:59:59Z", include_untimed=True)), 2)

    def test_gzip_csv(self):
        sha = self.reg(gzip.compress(CSV), "x.csv.gz")
        self.s.ensure_dataset("t/gz", "reference", None, "test")
        self.assertEqual(len(self.s.rows(self.s.import_version("t/gz", "v1", sha, "csv.gz", "tester"))), 3)

    def test_version_as_of_uses_publication_and_availability(self):
        ds = "t/ratings"
        self.s.ensure_dataset(ds, "ratings", "NBA", "test")
        v1 = self.s.import_version(ds, "v1", self.reg(CSV + b"9,,x,1\n"), "csv", "t",
                                   available_from_utc="2026-11-01T00:00:00Z")
        v2 = self.s.import_version(ds, "v2", self.reg(CSV + b"8,,y,2\n"), "csv", "t",
                                   available_from_utc="2026-11-05T00:00:00Z")
        self.assertIsNone(self.s.version_as_of(ds, "2026-11-10T00:00:00Z"))  # nothing published yet
        self.s.set_status(v1, "PUBLISHED", "ok", "t")
        self.s.set_status(v2, "PUBLISHED", "ok", "t")
        self.assertEqual(self.s.version_as_of(ds, "2026-11-03T00:00:00Z"), v1)
        self.assertEqual(self.s.version_as_of(ds, "2026-11-06T00:00:00Z"), v2)
        self.s.set_status(v2, "RETRACTED", "bad source", "t")
        self.assertEqual(self.s.version_as_of(ds, "2026-11-06T00:00:00Z"), v1)
        self.assertEqual(self.s.status(v2), "RETRACTED")

    def test_same_label_different_bytes_is_refused(self):
        self.s.ensure_dataset("t/x", "reference", None, "test")
        self.s.import_version("t/x", "v1", self.reg(), "csv", "t")
        with self.assertRaises(ModelDataError):
            self.s.import_version("t/x", "v1", self.reg(CSV + b"z,,,\n"), "csv", "t")

    def test_account_exports_are_rejected(self):
        sha = self.reg(b"id,aggregate.wallet.balance.total,stake\n1,10,5\n", "acct.csv", "MODEL_INTERNAL")
        self.s.ensure_dataset("t/acct", "reference", None, "test")
        with self.assertRaisesRegex(ModelDataError, "accounts database"):
            self.s.import_version("t/acct", "v1", sha, "csv", "t")

    def test_user_flags_need_classification_or_review(self):
        data = b"game,actual_bet_status,stake_eligible\n1,No bet,False\n"
        self.s.ensure_dataset("t/flag", "games", None, "test")
        with self.assertRaisesRegex(ModelDataError, "user observation"):
            self.s.import_version("t/flag", "v1", self.reg(data, "f.csv", "MODEL_INTERNAL"), "csv", "t",
                                  reviewed_columns={"stake_eligible": "model eligibility flag"})
        sha2 = self.reg(data + b"2,,\n", "g.csv", "CONTAINS_USER_OBSERVATION_FLAGS")
        vid = self.s.import_version("t/flag", "v2", sha2, "csv", "t", reviewed_columns={"stake_eligible": "flag"})
        flags = dict(self.s.fetchall("SELECT name, flagged FROM md_dataset_columns WHERE version_id = ?", (vid,)))
        self.assertEqual(flags, {"game": None, "actual_bet_status": "USER_OBSERVATION_FLAG",
                                 "stake_eligible": "REVIEWED_MODEL_FIELD"})

    def test_evidence_tables_are_append_only(self):
        sha = self.reg()
        for sql in ("UPDATE md_source_files SET provenance = 'x' WHERE sha256 = ?",
                    "DELETE FROM md_source_file_chunks WHERE sha256 = ?"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                self.s.execute(sql, (sha,))

    def test_failed_import_leaves_nothing_behind(self):
        sha = self.reg(b"a,a_time\n1,not-a-time\n", "bad.csv", "MODEL_INTERNAL")
        self.s.ensure_dataset("t/atomic", "reference", None, "test")
        self.s.con.execute("CREATE TRIGGER t_fail BEFORE INSERT ON md_dataset_rows "
                           "BEGIN SELECT RAISE(ABORT, 'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.import_version("t/atomic", "v1", sha, "csv", "t")
        self.assertEqual(self.s.fetchone("SELECT COUNT(*) FROM md_dataset_versions")[0], 0)

    def test_changed_applied_migration_is_refused(self):
        self.s.execute("UPDATE schema_migrations SET sha256 = 'x' WHERE name = 'model_data'")
        with self.assertRaisesRegex(MigrationError, "changed after it was applied"):
            self.s.migrate()

    def test_run_pins_reproduce_exact_files(self):
        a = self.reg()
        b = self.reg(b"\x00binary", "b.bin", "MODEL_INTERNAL")
        self.s.register_run("run", "REPLAY", ["NHL_ML_V3"], {"python": "3.13"}, [{"location": "x.py", "sha256": "0"}])
        self.s.pin_input("run", "inputs/a.csv", "INPUT", a)
        self.s.pin_input("run", "inputs/deep/b.bin", "INPUT", b)
        with self.assertRaises(ModelDataError):
            self.s.pin_input("run", "inputs/a.csv", "INPUT", b)
        with tempfile.TemporaryDirectory() as d:
            files = self.s.materialize_run("run", Path(d))
            self.assertEqual(sorted(sha256_bytes(p.read_bytes()) for p in files), sorted([a, b]))

    def test_snapshot_is_consistent_hashed_and_never_overwrites(self):
        self.reg()
        with tempfile.TemporaryDirectory() as d:
            info = self.s.snapshot(Path(d) / "snap.sqlite")
            self.assertEqual(info["sha256"], sha256_bytes((Path(d) / "snap.sqlite").read_bytes()))
            self.assertTrue((Path(d) / "snap.sqlite.sha256").read_text().startswith(info["sha256"]))
            copy = sqlite3.connect(Path(d) / "snap.sqlite")
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM md_source_files").fetchone()[0], 1)
            copy.close()
            with self.assertRaises(ModelDataError):
                self.s.snapshot(Path(d) / "snap.sqlite")

    @unittest.skipIf(importlib.util.find_spec("pyarrow") is None, "pyarrow not installed")
    def test_parquet_import(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        buf = io.BytesIO()
        pq.write_table(pa.table({"game_id": [1, 2], "spread": [3.5, None], "team": ["A", "B"]}), buf)
        sha = self.reg(buf.getvalue(), "b.parquet", "PUBLIC_MARKET")
        self.s.ensure_dataset("t/pq", "odds", "NCAAFB", "test")
        vid = self.s.import_version("t/pq", "v1", sha, "parquet", "t")
        self.assertEqual(self.s.rows(vid), [{"game_id": "1", "spread": "3.5", "team": "A"},
                                            {"game_id": "2", "spread": None, "team": "B"}])
        self.assertTrue(self.s.verify_version(vid)["lossless"])


class OnFrozenHistory(unittest.TestCase):
    """0006 applied on top of a database holding the frozen baseline: links to real rows."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        paths = Paths(Path(cls.tmp.name))
        shutil.copy(default_paths().frozen_archive, paths.frozen_archive)
        init_database(paths)
        cls.store = open_store(paths.database)

    @classmethod
    def tearDownClass(cls):
        cls.store.con.close()
        cls.tmp.cleanup()

    def test_run_links_to_batch_cohort_and_scores(self):
        s = self.store
        # Frozen scores carry legacy model_version labels; the release comes from model_release_aliases.
        batch, cohort, score, release = s.fetchone(
            "SELECT ms.batch_id, ms.quote_cohort_id, ms.score_id, a.release_id FROM model_scores ms "
            "JOIN model_release_aliases a ON a.sport = ms.sport AND a.model_version = ms.model_version "
            "AND a.market IN (ms.market, '*') WHERE ms.sport = 'NFL' AND a.release_id IS NOT NULL LIMIT 1")
        before = {t: s.fetchone(f"SELECT COUNT(*) FROM {t}")[0] for t in ("model_scores", "market_quotes", "events")}
        s.register_run("nfl-link", "REPLAY", [release], {}, [], sport="NFL", batch_id=batch,
                       quote_cohort_id=cohort)
        self.assertEqual(s.link_scores("nfl-link", [score], "test link"), 1)
        joined = s.fetchone("SELECT ms.batch_id FROM md_run_score_links l JOIN model_scores ms "
                            "USING (score_id) WHERE l.run_id = 'nfl-link'")
        self.assertEqual(joined[0], batch)
        after = {t: s.fetchone(f"SELECT COUNT(*) FROM {t}")[0] for t in before}
        self.assertEqual(before, after)  # existing history unchanged


@unittest.skipIf(any(importlib.util.find_spec(m) is None for m in ("pandas", "numpy", "scipy")),
                 "model environment not installed (requirements-models.txt)")
class GoldenFromDatabaseTests(unittest.TestCase):
    def test_golden_fixtures_replay_from_model_data_tables(self):
        from gambling.modeldata.golden import import_golden, prove_golden
        ext = os.environ.get("GOLDEN_EXTERNAL_DIR")
        with tempfile.TemporaryDirectory() as d:
            store = open_store(Path(d) / "gambling.sqlite")
            import_golden(store, Path(ext) if ext else None)
            reports = {r["fixture_id"]: r for r in prove_golden(store)}
            store.con.close()
        for fid in ("NFL_20261110_072712CST", "NHL_DAY0_20261112", "NCAAFB_20261102", "NBA_R4_20261112"):
            self.assertEqual(reports[fid]["status"], "PASSED", reports[fid])
        self.assertIn(reports["NCAABB_V4_20261101"]["status"], ("PASSED", "SKIPPED"))


if __name__ == "__main__":
    unittest.main()
