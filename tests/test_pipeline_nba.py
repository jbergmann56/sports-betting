"""NBA daily pipeline: golden replay of Nov 12 through the generalized wrapper, history feed, guards."""
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gambling.db.migrate import apply_migrations, connect
from gambling.models.nba import r4_legacy as r4
from gambling.pipeline.nba import (BASE_HISTORY, VALIDATION_STATUS, PipelineError, latest_capture,
                                   run_nba_daily)
from tests.test_nba_adapter import MODEL_ENV, registry_authority

GOLDEN_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NBA_R4_20261112_betsheet.csv"
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


def archived_forecasts():
    with open(r4.FIXTURE / "expected" / "forecasts.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_csv(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class NbaPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = registry_authority()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seen = {}

    def scorer(self, quotes_json, history):
        self.seen = {"quotes_json": sha(quotes_json), "history": sha(history)}
        return archived_forecasts()

    def run_it(self, slate="2026-11-12", db=None, **kw):
        return run_nba_daily(slate, r4.CAPTURE_20261112, self.root, db, scorer=self.scorer, authority=self.auth,
                             now=NOW, **kw)

    def test_reproduces_the_frozen_sheet_byte_for_byte(self):
        m = self.run_it()
        self.assertEqual(sha(Path(m["run_dir"]) / "betsheet.csv"), sha(GOLDEN_SHEET))
        self.assertEqual(self.seen, {"quotes_json": r4.QUOTES_JSON_SHA, "history": r4.HISTORY_SHA})
        self.assertEqual(m["validation_status"], VALIDATION_STATUS)
        self.assertEqual(m["outputs"]["sheet_status"]["PRODUCTION_QUALIFIED"], 2)
        on_disk = json.loads((Path(m["run_dir"]) / "manifest.json").read_text())
        self.assertEqual(on_disk["inputs"]["capture_quotes_csv"]["sha256"], r4.CAPTURE_20261112_SHA)

    def test_runs_are_new_folders(self):
        self.run_it()
        with self.assertRaises(FileExistsError):
            self.run_it()

    def test_espn_finals_extend_history_and_guards(self):
        db = self.root / "gambling.sqlite"
        con = connect(db)
        apply_migrations(con)
        con.execute("INSERT INTO official_game_results (sport, espn_game_id, game_date, away_team, home_team, "
                    "away_score, home_score, status, source_file) VALUES ('NBA', '1', '2026-11-12', "
                    "'Toronto Raptors', 'Washington Wizards', 110, 104, 'STATUS_FINAL', 'espn:x')")
        con.commit()
        con.close()
        before = sha(db)
        with self.assertRaisesRegex(PipelineError, "no NBA games starting on 2026-11-13"):
            self.run_it(slate="2026-11-13", db=db)
        m = self.run_it(db=db)                     # Nov 12 slate: finals after Nov 11 are not used
        self.assertEqual(m["inputs"]["history"]["espn_rows_added"], 0)
        self.assertEqual(sha(db), before)          # scoring database opened read-only
        con = sqlite3.connect(db)
        con.execute("INSERT INTO official_game_results (sport, espn_game_id, game_date, away_team, home_team, "
                    "away_score, home_score, status, source_file) VALUES ('NBA', '2', '2026-11-11', "
                    "'LA Clippers X', 'Washington Wizards', 99, 98, 'STATUS_FINAL', 'espn:y')")
        con.commit()
        con.close()
        # a final on/before the base history's last date is not added again; the base ends Nov 11
        m = run_nba_daily("2026-11-12", r4.CAPTURE_20261112, self.root, db, scorer=self.scorer,
                          authority=self.auth, now=datetime(2026, 11, 12, 18, 1, tzinfo=timezone.utc))
        self.assertEqual(m["inputs"]["history"]["espn_rows_added"], 0)

    def test_unknown_team_names_stop_the_run(self):
        base = self.root / "base.csv"
        rows = read_csv(BASE_HISTORY)
        with open(base, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(r for r in rows if r["date"] <= "2026-11-10")
        db = self.root / "g.sqlite"
        con = connect(db)
        apply_migrations(con)
        con.execute("INSERT INTO official_game_results (sport, espn_game_id, game_date, away_team, home_team, "
                    "away_score, home_score, status, source_file) VALUES ('NBA', '3', '2026-11-11', "
                    "'Nowhere Comets', 'Washington Wizards', 99, 98, 'STATUS_FINAL', 'espn:z')")
        con.commit()
        con.close()
        with self.assertRaisesRegex(PipelineError, "Nowhere Comets"):
            self.run_it(db=db, base_history=base)
        m = run_nba_daily("2026-11-12", r4.CAPTURE_20261112, self.root, db, base_history=base,
                          allow_new_names=True, scorer=self.scorer, authority=self.auth,
                          now=datetime(2026, 11, 12, 18, 2, tzinfo=timezone.utc))
        self.assertEqual((m["inputs"]["history"]["espn_rows_added"], m["inputs"]["history"]["new_team_names"]),
                         (1, ["Nowhere Comets"]))

    def test_stale_history_stops_the_run(self):
        base = self.root / "old.csv"
        rows = read_csv(BASE_HISTORY)
        with open(base, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(r for r in rows if r["date"] <= "2026-11-01")
        with self.assertRaisesRegex(PipelineError, "days before the slate"):
            self.run_it(base_history=base)

    def test_latest_capture(self):
        caps = self.root / "captures"
        for name, sport in (("20261110T000000Z_a", "NBA"), ("20261111T000000Z_b", "NHL")):
            (caps / name).mkdir(parents=True)
            (caps / name / "quotes.csv").write_text(f"sport,event_id\n{sport},1\n", encoding="utf-8")
        self.assertEqual(latest_capture(caps).parent.name, "20261110T000000Z_a")
        with self.assertRaises(PipelineError):
            latest_capture(caps, "NFL")

    @unittest.skipUnless(MODEL_ENV, "model environment not installed (requirements-models.txt)")
    def test_frozen_scorer_through_the_pipeline(self):
        m = run_nba_daily("2026-11-12", r4.CAPTURE_20261112, self.root, None, authority=self.auth)
        got = read_csv(Path(m["run_dir"]) / "betsheet.csv")
        want = read_csv(GOLDEN_SHEET)
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):   # the scorer stamps its own run time; everything else is identical
            g.pop("score_as_of_utc"), w.pop("score_as_of_utc")
            self.assertEqual(g, w)


if __name__ == "__main__":
    unittest.main()


class RecordRunTests(unittest.TestCase):
    def test_record_is_verified_idempotent_and_append_only(self):
        from gambling.pipeline.record import RecordError, record_run
        # cleanups run last-in-first-out: the connection closes before the folder is removed (Windows locks open files)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        m = run_nba_daily("2026-11-12", r4.CAPTURE_20261112, root, None, scorer=lambda q, h: archived_forecasts(),
                          authority=registry_authority(), now=NOW)
        con = connect(root / "g.sqlite")
        con.row_factory = None
        self.addCleanup(con.close)
        apply_migrations(con)
        r = record_run(con, Path(m["run_dir"]))
        self.assertEqual((r["recorded"], r["rows"]), (True, 48))
        self.assertFalse(record_run(con, Path(m["run_dir"]))["recorded"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM latest_pipeline_sheets WHERE status = "
                                     "'PRODUCTION_QUALIFIED'").fetchone(), (2,))
        m2 = run_nba_daily("2026-11-12", r4.CAPTURE_20261112, root, None, scorer=lambda q, h: archived_forecasts(),
                           authority=registry_authority(), now=datetime(2026, 11, 12, 19, tzinfo=timezone.utc))
        record_run(con, Path(m2["run_dir"]))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone(), (2,))
        self.assertEqual(con.execute("SELECT DISTINCT run_key FROM latest_pipeline_sheets").fetchall(),
                         [(f"NBA:2026-11-12:{m2['run_id']}",)])
        for sql in ("UPDATE pipeline_sheet_rows SET status = 'X'", "DELETE FROM pipeline_runs"):
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute(sql)
        (Path(m2["run_dir"]) / "betsheet.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaises(RecordError):
            record_run(con, Path(m2["run_dir"]))
