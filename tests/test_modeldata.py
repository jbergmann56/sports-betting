"""Model-input database: immutability, lossless import, time-safe retrieval, run pinning.

Runs on SQLite always. Set GAMBLING_MODELDATA_TEST_URL to an EMPTY MySQL database
(e.g. mysql://user:pw@127.0.0.1:3306/gambling_model_data_test) to run the same
tests on MySQL. The golden-proof test needs the model environment.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from gambling.modeldata.store import ModelDataError, connect, sha256_bytes

MYSQL_URL = os.environ.get("GAMBLING_MODELDATA_TEST_URL")
CSV = (b"game_id,snapshot_as_of_utc,team,line\n"
       b"1,2026-11-10T13:00:00+00:00,\"A, Inc\",-3.5\n"
       b"2,2026-11-11T13:00:00+00:00,B,\n"
       b"3,,C,7\n")


class StoreContract:
    """Backend-independent contract; mixed into one TestCase per backend."""

    def new_store(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def setUp(self):
        self.s = self.new_store()
        self.s.migrate()
        self.uid = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.s.con.close()

    def reg(self, data=CSV, name="odds.csv", sens="PUBLIC_MARKET"):
        return self.s.register_source(data, name, sens, "unit test", "tester")

    def test_migrate_is_idempotent(self):
        self.assertEqual(self.s.migrate(), [])

    def test_only_numbered_schema_files_are_migrations(self):
        names = [r[0] for r in self.s.fetchall("SELECT name FROM schema_versions")]
        self.assertTrue(names)
        self.assertTrue(all(n[:4].isdigit() and n[4] == "_" for n in names), names)

    def test_source_round_trip_is_byte_identical_and_chunked(self):
        big = os.urandom(3 * (1 << 20) + 17)
        sha = self.reg(big, f"blob-{self.uid}.bin", "MODEL_INTERNAL")
        self.assertEqual(sha, sha256_bytes(big))
        with tempfile.TemporaryDirectory() as d:
            p = self.s.materialize_source(sha, Path(d) / "x.bin")
            self.assertEqual(p.read_bytes(), big)
        self.assertEqual(self.s.fetchone("SELECT chunk_count FROM source_files WHERE sha256 = ?", (sha,))[0], 4)
        self.assertEqual(self.reg(big, f"other-name-{self.uid}.bin", "MODEL_INTERNAL"), sha)  # content-addressed

    def test_csv_import_is_lossless_and_time_safe(self):
        sha = self.reg(CSV + self.uid.encode() + b",,,\n")
        self.s.ensure_dataset(f"t/odds/{self.uid}", "odds", "NFL", "test")
        vid = self.s.import_version(f"t/odds/{self.uid}", "v1", sha, "csv", "tester",
                                    available_from_utc="2026-11-11T14:00:00+00:00", time_column="snapshot_as_of_utc")
        rows = self.s.rows(vid)
        self.assertEqual(rows[0], {"game_id": "1", "snapshot_as_of_utc": "2026-11-10T13:00:00+00:00",
                                   "team": "A, Inc", "line": "-3.5"})
        self.assertEqual(rows[1]["line"], "")  # empty string preserved, not None
        self.assertTrue(self.s.verify_version(vid)["lossless"])
        cut = self.s.rows(vid, as_of_utc="2026-11-10T23:59:59Z")
        self.assertEqual([r["game_id"] for r in cut], ["1"])  # later and untimed rows excluded
        self.assertEqual(len(self.s.rows(vid, "2026-11-10T23:59:59Z", include_untimed=True)), 3)

    def test_gzip_csv(self):
        sha = self.reg(gzip.compress(CSV + self.uid.encode() + b",,,\n"), f"x-{self.uid}.csv.gz")
        self.s.ensure_dataset(f"t/gz/{self.uid}", "reference", None, "test")
        vid = self.s.import_version(f"t/gz/{self.uid}", "v1", sha, "csv.gz", "tester")
        self.assertEqual(len(self.s.rows(vid)), 4)

    def test_version_as_of_uses_publication_and_availability(self):
        ds = f"t/ratings/{self.uid}"
        self.s.ensure_dataset(ds, "ratings", "NBA", "test")
        v1 = self.s.import_version(ds, "v1", self.reg(CSV + b"9,,x,1\n" + self.uid.encode() + b",,,\n"), "csv",
                                   "t", available_from_utc="2026-11-01T00:00:00Z")
        v2 = self.s.import_version(ds, "v2", self.reg(CSV + b"8,,y,2\n" + self.uid.encode() + b",,,\n"), "csv",
                                   "t", available_from_utc="2026-11-05T00:00:00Z")
        self.assertIsNone(self.s.version_as_of(ds, "2026-11-10T00:00:00Z"))  # nothing published yet
        self.s.set_status(v1, "PUBLISHED", "ok", "t")
        self.s.set_status(v2, "PUBLISHED", "ok", "t")
        self.assertEqual(self.s.version_as_of(ds, "2026-11-03T00:00:00Z"), v1)
        self.assertEqual(self.s.version_as_of(ds, "2026-11-06T00:00:00Z"), v2)
        self.s.set_status(v2, "RETRACTED", "bad source", "t")
        self.assertEqual(self.s.version_as_of(ds, "2026-11-06T00:00:00Z"), v1)
        self.assertEqual(self.s.status(v2), "RETRACTED")

    def test_same_label_different_bytes_is_refused(self):
        ds = f"t/x/{self.uid}"
        self.s.ensure_dataset(ds, "reference", None, "test")
        self.s.import_version(ds, "v1", self.reg(CSV + self.uid.encode() + b",,,\n"), "csv", "t")
        with self.assertRaises(ModelDataError):
            self.s.import_version(ds, "v1", self.reg(CSV + b"z,,,\n" + self.uid.encode() + b",,,\n"), "csv", "t")

    def test_account_exports_are_rejected(self):
        sha = self.reg(b"id,aggregate.wallet.balance.total,stake\n1,10,5\n" + self.uid.encode() + b",,\n",
                       f"acct-{self.uid}.csv", "MODEL_INTERNAL")
        self.s.ensure_dataset(f"t/acct/{self.uid}", "reference", None, "test")
        with self.assertRaisesRegex(ModelDataError, "accounts database"):
            self.s.import_version(f"t/acct/{self.uid}", "v1", sha, "csv", "t")

    def test_user_flags_need_classification_or_review(self):
        data = b"game,actual_bet_status,stake_eligible\n1,No bet,False\n" + self.uid.encode() + b",,\n"
        ds = f"t/flag/{self.uid}"
        self.s.ensure_dataset(ds, "games", None, "test")
        with self.assertRaisesRegex(ModelDataError, "user observation"):
            self.s.import_version(ds, "v1", self.reg(data, f"f-{self.uid}.csv", "MODEL_INTERNAL"), "csv", "t",
                                  reviewed_columns={"stake_eligible": "model eligibility flag"})
        sha2 = self.reg(data + b"2,,\n", f"g-{self.uid}.csv", "CONTAINS_USER_OBSERVATION_FLAGS")
        vid = self.s.import_version(ds, "v2", sha2, "csv", "t", reviewed_columns={"stake_eligible": "model flag"})
        flags = dict(self.s.fetchall("SELECT name, flagged FROM dataset_columns WHERE version_id = ?", (vid,)))
        self.assertEqual(flags, {"game": None, "actual_bet_status": "USER_OBSERVATION_FLAG",
                                 "stake_eligible": "REVIEWED_MODEL_FIELD"})

    def test_evidence_tables_are_append_only(self):
        sha = self.reg(CSV + self.uid.encode() + b",,,\n")
        for sql in ("UPDATE source_files SET provenance = 'x' WHERE sha256 = ?",
                    "DELETE FROM source_file_chunks WHERE sha256 = ?"):
            with self.subTest(sql=sql):
                with self.assertRaises(Exception):
                    self.s.execute(sql, (sha,))
                self.s.con.rollback()

    def test_run_pins_reproduce_exact_files(self):
        a = self.reg(CSV + self.uid.encode() + b",,,\n", f"a-{self.uid}.csv")
        b = self.reg(b"\x00binary" + self.uid.encode(), f"b-{self.uid}.bin", "MODEL_INTERNAL")
        run = f"run-{self.uid}"
        self.s.register_run(run, "REPLAY", ["R1"], {"python": "3.13"}, [{"location": "x.py", "sha256": "0"}])
        self.s.pin_input(run, "inputs/a.csv", "INPUT", a)
        self.s.pin_input(run, "inputs/deep/b.bin", "INPUT", b)
        with self.assertRaises(ModelDataError):
            self.s.pin_input(run, "inputs/a.csv", "INPUT", b)
        with tempfile.TemporaryDirectory() as d:
            files = self.s.materialize_run(run, Path(d))
            self.assertEqual(sorted(sha256_bytes(p.read_bytes()) for p in files), sorted([a, b]))
            self.assertTrue((Path(d) / "inputs/deep/b.bin").exists())


class SqliteStoreTests(StoreContract, unittest.TestCase):
    def new_store(self):
        return connect("sqlite:///:memory:")

    def test_changed_applied_schema_is_refused(self):
        self.s.execute("DROP TRIGGER IF EXISTS schema_guard")  # no-op; schema_versions is not append-only
        self.s.execute("UPDATE schema_versions SET sha256 = 'x'")
        self.s.commit()
        with self.assertRaisesRegex(ModelDataError, "changed after it was applied"):
            self.s.migrate()

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


@unittest.skipUnless(MYSQL_URL, "set GAMBLING_MODELDATA_TEST_URL to run against MySQL")
class MysqlStoreTests(StoreContract, unittest.TestCase):
    def new_store(self):
        return connect(MYSQL_URL)


@unittest.skipIf(any(importlib.util.find_spec(m) is None for m in ("pandas", "numpy", "scipy")),
                 "model environment not installed (requirements-models.txt)")
class GoldenFromDatabaseTests(unittest.TestCase):
    def test_golden_fixtures_replay_from_sqlite_model_data(self):
        from gambling.modeldata.golden import import_golden, prove_golden
        ext = os.environ.get("GOLDEN_EXTERNAL_DIR")
        with tempfile.TemporaryDirectory() as d:
            store = connect(f"sqlite:///{d}/md.sqlite")
            store.migrate()
            import_golden(store, Path(ext) if ext else None)
            reports = {r["fixture_id"]: r for r in prove_golden(store)}
            store.con.close()
        for fid in ("NFL_20261110_072712CST", "NHL_DAY0_20261112", "NCAAFB_20261102", "NBA_R4_20261112"):
            self.assertEqual(reports[fid]["status"], "PASSED", reports[fid])
        self.assertIn(reports["NCAABB_V4_20261101"]["status"], ("PASSED", "SKIPPED"))


if __name__ == "__main__":
    unittest.main()
