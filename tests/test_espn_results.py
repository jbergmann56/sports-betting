"""ESPN results collector (migration 0007).

Uses archived ESPN responses from the golden fixtures (NCAABB Nov 1-2 scoreboards and the NCAAFB
Oct 27 scoreboard) served through a stub getter; the sandbox has no network. The NBA history
test uses a SYNTHETIC payload built here (fictitious scores, never written to a real database).
"""
from __future__ import annotations

import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gambling.db import apply_migrations, connect
from gambling.results import espn

FX = Path(__file__).parent / "golden" / "fixtures"
NCAABB_1101 = FX / "NCAABB_V4_20261101" / "inputs" / "espn_20261101.json"
NCAABB_1102 = FX / "NCAABB_V4_20261101" / "inputs" / "espn_20261102.json"
NCAAFB_1027 = FX / "NCAAFB_20261102" / "inputs" / "oct27_scoreboard.json"
NBA_HISTORY = FX / "NBA_R4_20261112" / "inputs" / "nba_history_through_2026-11-11.csv"


def clock(iso):
    return lambda: datetime.fromisoformat(iso)


def synthetic_nba(games, day="2026-11-12"):
    """SYNTHETIC ESPN-shaped NBA scoreboard for code-path tests only (not real results)."""
    events = []
    for n, (away, home, a_s, h_s, done) in enumerate(games):
        events.append({"id": f"9990000{n}", "date": f"{day}T23:30Z", "competitions": [{
            "neutralSite": False, "status": {"type": {"name": "STATUS_FINAL" if done else "STATUS_SCHEDULED",
                                                      "state": "post" if done else "pre", "completed": done}},
            "competitors": [{"homeAway": "home", "team": {"id": f"h{n}", "displayName": home}, "score": str(h_s)},
                            {"homeAway": "away", "team": {"id": f"a{n}", "displayName": away}, "score": str(a_s)}]}]})
    return json.dumps({"events": events}).encode()


class EspnCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = connect(Path(self.tmp.name) / "gambling.sqlite")
        apply_migrations(self.con)
        self.addCleanup(self.con.close)

    def capture(self, sport, day, path_or_bytes, at="2026-11-03T12:00:00+00:00"):
        body = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
        return espn.fetch(sport, day, getter=lambda url: body, now=clock(at))

    def test_urls(self):
        self.assertEqual(espn.scoreboard_url("NBA", "2026-11-12"),
                         "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261112")
        self.assertIn("groups=50", espn.scoreboard_url("NCAABB", "2026-11-01"))
        self.assertIn("groups=80", espn.scoreboard_url("NCAAFB", "2026-10-27"))
        with self.assertRaises(espn.ResultsError):
            espn.scoreboard_url("MLB", "2026-11-01")

    def test_raw_response_is_kept_byte_for_byte(self):
        cap = self.capture("NCAABB", "2026-11-01", NCAABB_1101)
        espn.record(self.con, cap)
        body, sha, url = self.con.execute("SELECT body, body_sha256, url FROM espn_result_captures").fetchone()
        self.assertEqual(body, NCAABB_1101.read_bytes())
        self.assertEqual(sha, cap.body_sha256)
        self.assertEqual(url, espn.scoreboard_url("NCAABB", "2026-11-01"))

    def test_finals_recorded_once_with_eastern_date(self):
        counts = espn.record(self.con, self.capture("NCAABB", "2026-11-01", NCAABB_1101))
        data = json.loads(NCAABB_1101.read_bytes())
        finals = sum(1 for e in data["events"] if e["competitions"][0]["status"]["type"]["completed"])
        self.assertEqual(counts["events"], len(data["events"]))
        self.assertEqual(counts["finals_recorded"], finals)
        row = dict(self.con.execute("SELECT * FROM official_game_results WHERE espn_game_id = '401920982'").fetchone())
        self.assertEqual((row["home_team"], row["home_score"], row["away_team"], row["away_score"]),
                         ("Villanova Wildcats", 72, "Notre Dame Fighting Irish", 74))
        self.assertEqual(row["game_date"], "2026-11-01")
        self.assertTrue(row["source_file"].startswith("espn:"))
        again = espn.record(self.con, self.capture("NCAABB", "2026-11-01", NCAABB_1101, "2026-11-03T13:00:00+00:00"))
        self.assertEqual((again["finals_recorded"], again["finals_already_recorded"]), (0, finals))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM espn_result_captures").fetchone()[0], 2)

    def test_changed_score_is_a_conflict_not_an_overwrite(self):
        espn.record(self.con, self.capture("NCAAFB", "2026-10-27", NCAAFB_1027))
        data = json.loads(NCAAFB_1027.read_bytes())
        changed = copy.deepcopy(data)
        comp = changed["events"][0]["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        home["score"] = str(int(home["score"]) + 7)
        counts = espn.record(self.con, self.capture("NCAAFB", "2026-10-27", json.dumps(changed).encode(),
                                                    "2026-10-29T00:00:00+00:00"))
        self.assertEqual(counts["conflicts"], 1)
        gid = changed["events"][0]["id"]
        recorded = self.con.execute("SELECT home_score FROM official_game_results WHERE espn_game_id = ?",
                                    (gid,)).fetchone()[0]
        self.assertEqual(recorded, int(home["score"]) - 7)  # unchanged
        conflict = dict(self.con.execute("SELECT * FROM espn_result_conflicts").fetchone())
        self.assertEqual((conflict["recorded_home_score"], conflict["observed_home_score"]), (recorded, recorded + 7))

    def test_unfinished_games_are_observed_not_recorded(self):
        body = synthetic_nba([("Boston Celtics", "Miami Heat", 0, 0, False)])
        counts = espn.record(self.con, self.capture("NBA", "2026-11-12", body))
        self.assertEqual((counts["events"], counts["finals_recorded"]), (1, 0))
        obs = dict(self.con.execute("SELECT * FROM espn_result_observations").fetchone())
        self.assertEqual((obs["status_name"], obs["completed"], obs["home_score"]), ("STATUS_SCHEDULED", 0, None))

    def test_late_eastern_game_keeps_its_eastern_date(self):
        body = json.loads(synthetic_nba([("Denver Nuggets", "Phoenix Suns", 100, 101, True)]))
        body["events"][0]["date"] = "2026-11-13T03:00Z"  # 10pm ET on Nov 12
        espn.record(self.con, self.capture("NBA", "2026-11-12", json.dumps(body).encode()))
        self.assertEqual(self.con.execute("SELECT game_date FROM official_game_results").fetchone()[0], "2026-11-12")

    def test_evidence_is_append_only(self):
        espn.record(self.con, self.capture("NCAABB", "2026-11-02", NCAABB_1102))
        for sql in ("UPDATE espn_result_captures SET url = 'x'", "DELETE FROM espn_result_observations"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                self.con.execute(sql)

    def test_failed_record_leaves_nothing(self):
        bad = json.dumps({"events": [{"id": "1", "competitions": [{"competitors": [{"homeAway": "home",
                                                                                    "team": {}}]}]}]}).encode()
        with self.assertRaises(espn.ResultsError):
            espn.record(self.con, self.capture("NBA", "2026-11-12", bad))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM espn_result_captures").fetchone()[0], 0)

    def test_nba_history_feed(self):
        body = synthetic_nba([("LA Clippers", "Sacramento Kings", 111, 104, True),
                              ("LA Lakers", "Utah Jazz", 99, 98, True),         # name the history never used
                              ("Miami Heat", "Chicago Bulls", 0, 0, False)])
        espn.record(self.con, self.capture("NBA", "2026-11-12", body))
        feed = espn.nba_history_rows(self.con, NBA_HISTORY, through="2026-11-12")
        self.assertEqual(feed["base_last_date"], "2026-11-11")
        self.assertEqual([r["game_key"] for r in feed["rows"]],
                         ["2026-11-12|LA Clippers|Sacramento Kings", "2026-11-12|LA Lakers|Utah Jazz"])
        self.assertEqual(feed["unknown_teams"], ["LA Lakers"])
        self.assertEqual(feed["rows"][0]["season"], "2026/2027")
        self.assertEqual(espn.nba_history_rows(self.con, NBA_HISTORY, through="2026-11-11")["rows"], [])
        out = Path(self.tmp.name) / "history_through_2026-11-12.csv"
        espn.write_nba_history(NBA_HISTORY, feed["rows"][:1], out)
        written = out.read_bytes()
        self.assertTrue(written.startswith(NBA_HISTORY.read_bytes()))  # base rows untouched
        with open(out, newline="") as f:
            last = list(csv.DictReader(f))[-1]
        self.assertEqual((last["away"], last["away_score"], last["original_game_id"]), ("LA Clippers", "111", "ESPN-99900000"))
        with self.assertRaises(FileExistsError):
            espn.write_nba_history(NBA_HISTORY, feed["rows"], out)


class ResultsCliTests(unittest.TestCase):
    def test_fetch_and_conflicts_through_cli(self):
        from unittest import mock
        from gambling.cli import main
        from gambling.config import Paths
        with tempfile.TemporaryDirectory() as d:
            paths = Paths(Path(d))
            con = connect(paths.database)
            apply_migrations(con)
            con.close()
            with mock.patch.object(espn, "_http_get", lambda url: NCAABB_1101.read_bytes()):
                self.assertEqual(main(["results", "fetch", "--sport", "NCAABB", "--date", "2026-11-01"], paths), 0)
            self.assertEqual(main(["results", "conflicts"], paths), 0)
            con = connect(paths.database)
            self.assertGreater(con.execute("SELECT COUNT(*) FROM official_game_results").fetchone()[0], 0)
            con.close()


if __name__ == "__main__":
    unittest.main()
