"""Raw import of Bovada exports into the separate accounts database (synthetic exports only)."""
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from gambling.accounts.importer import ImportRefused, import_exports, open_accounts_db
from tests.test_accounts_profile import T0, item, write_run


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exports = self.root / "bovada_export"
        self.exports.mkdir()
        self.db = self.root / "data" / "accounts" / "accounts.sqlite"
        pending = item(2, T0 + timedelta(days=2), "25", "115", status="PENDING")
        settled = item(2, T0 + timedelta(days=2), "25", "115", status="SETTLED")
        write_run(self.exports, T0, T0 + timedelta(days=15),
                  [[item(1, T0 + timedelta(days=1), "-10", "90"), pending], [pending]])
        write_run(self.exports, T0 + timedelta(days=10), T0 + timedelta(days=30),
                  [[settled, item(3, T0 + timedelta(days=20), "-15", "100")]])
        # a failed attempt: run log, no pages
        stem = "bovada_transactions_2026-10-05_to_2026-10-06"
        (self.exports / f"{stem}_run.json").write_text(json.dumps(
            {"created_at_from": "2026-10-05T00:00:00Z", "started_at_utc": "2026-10-06T00:00:00+00:00",
             "finished_at_utc": "2026-10-06T00:01:00+00:00", "stopped_because": "browser error", "pages": []}))

    def q(self, sql, *a):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, a).fetchall()
        finally:
            con.close()

    def test_raw_layer_is_complete_and_verbatim(self):
        r = import_exports(self.db, self.exports)
        self.assertEqual((r["runs_imported"], r["pages"], r["sightings"]), (3, 3, 5))  # pending version sighted on two pages
        self.assertEqual(r["transactions_in_database"], 3)
        # both versions of transaction 2 are kept, with their sightings
        versions = self.q("SELECT json_extract(item_json, '$.status') FROM raw_transactions "
                          "WHERE transaction_id = '2' ORDER BY 1")
        self.assertEqual(versions, [("PENDING",), ("SETTLED",)])
        self.assertEqual(self.q("SELECT json_extract(item_json, '$.status') FROM latest_transactions "
                                "WHERE transaction_id = '2'"), [("SETTLED",)])
        # files kept byte for byte
        for stem, role, content in self.q("SELECT stem, role, content FROM export_files"):
            suffix = {"pages": "_pages.jsonl", "run": "_run.json", "json": ".json", "csv": ".csv"}[role]
            self.assertEqual(content, (self.exports / f"{stem}{suffix}").read_bytes())
        lines = self.q("SELECT line_text FROM raw_pages ORDER BY stem, line_no")
        self.assertEqual(len(lines), 3)
        # money kept as received strings, never floats
        self.assertEqual(self.q("SELECT delta_total, balance_total FROM raw_transactions WHERE transaction_id = '1'"),
                         [("-10", "90")])

    def test_coverage_windows_mark_failed_attempt(self):
        import_exports(self.db, self.exports)
        rows = dict((s, (c, st)) for s, c, st in self.q("SELECT stem, covers, status FROM coverage_windows"))
        self.assertEqual(rows["bovada_transactions_2026-10-05_to_2026-10-06"], (0, "FAILED_NO_DATA"))
        self.assertEqual(sum(c for c, _ in rows.values()), 2)

    def test_reimport_is_idempotent_and_changed_files_conflict(self):
        import_exports(self.db, self.exports)
        again = import_exports(self.db, self.exports)
        self.assertEqual((again["runs_imported"], again["runs_already_imported"], again["sightings"]), (0, 3, 0))
        self.assertEqual(self.q("SELECT COUNT(*) FROM transaction_sightings"), [(5,)])
        csv_file = next(self.exports.glob("*_to_2026-10-16.csv"))
        csv_file.write_text(csv_file.read_text() + "999\n")
        with self.assertRaisesRegex(ImportRefused, "immutable"):
            import_exports(self.db, self.exports)
        self.assertEqual(self.q("SELECT COUNT(*) FROM import_runs"), [(2,)])  # failed import left nothing

    def test_raw_layer_is_append_only(self):
        import_exports(self.db, self.exports)
        con = sqlite3.connect(self.db)
        try:
            for sql in ("UPDATE raw_transactions SET delta_total = '0'", "DELETE FROM export_files",
                        "UPDATE import_runs SET tool = 'x'"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    con.execute(sql)
        finally:
            con.close()

    def test_refuses_when_profile_not_ready(self):
        write_run(self.exports, T0 + timedelta(days=60), T0 + timedelta(days=61),
                  [[item(9, T0 + timedelta(days=60), "-1", "1")]], stopped="browser error: closed")
        with self.assertRaisesRegex(ImportRefused, "not import-ready"):
            import_exports(self.db, self.exports)
        self.assertFalse(self.db.exists())

    def test_never_the_scoring_database(self):
        with self.assertRaises(ImportRefused):
            open_accounts_db(self.root / "gambling.sqlite")
        with self.assertRaises(ImportRefused):
            open_accounts_db(self.root / "x.sqlite", scoring_db=self.root / "x.sqlite")

    def test_baseline_copied_verbatim_once(self):
        base = self.root / "gambling_pnl.sqlite"
        con = sqlite3.connect(base)
        con.execute("CREATE TABLE sportsbook_wagers (wager_id TEXT, bovada_reference TEXT, source_transaction_id TEXT, "
                    "placed_at_utc TEXT, settled_at_utc TEXT, net_pnl_cents INTEGER)")
        con.execute("INSERT INTO sportsbook_wagers VALUES ('w1', '1', NULL, '2026-10-02', '2026-10-02', -1000)")
        con.execute("CREATE TABLE summary (k TEXT, v TEXT)")
        con.execute("INSERT INTO summary VALUES ('total', '-10.00')")
        con.commit()
        con.close()
        r = import_exports(self.db, self.exports, baseline=base)
        self.assertEqual(r["baseline"]["tables"], {"sportsbook_wagers": 1, "summary": 1})
        self.assertEqual(self.q("SELECT * FROM pnl_baseline_sportsbook_wagers"),
                         [("w1", "1", None, "2026-10-02", "2026-10-02", -1000)])
        self.assertEqual(import_exports(self.db, self.exports, baseline=base)["baseline"], "already imported")
        other = self.root / "other.sqlite"
        other.write_bytes(base.read_bytes() + b"\0")
        with self.assertRaisesRegex(ImportRefused, "different P&L baseline"):
            import_exports(self.db, self.exports, baseline=other)

    def test_cli_imports_to_separate_default_path(self):
        from gambling.cli import main
        from gambling.config import Paths
        paths = Paths(self.root / "data")
        self.assertEqual(main(["accounts", "import", "--export-dir", str(self.exports)], paths), 0)
        self.assertTrue((self.root / "data" / "accounts" / "accounts.sqlite").exists())
        self.assertFalse(paths.database.exists())  # the scoring database was not touched or created


if __name__ == "__main__":
    unittest.main()
