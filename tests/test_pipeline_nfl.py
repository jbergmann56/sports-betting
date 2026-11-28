"""NFL live scoring: converter, week driver and daily pipeline against the archived Nov 10 board."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from gambling.bovada.parse import parse_feed
from gambling.models.nfl import live
from gambling.models.nfl.rev2_legacy import FROZEN_ZIP, NOV10_PREFIX
from gambling.pipeline.common import PipelineError
from gambling.pipeline.nfl import run_nfl_daily
from tests.test_nba_adapter import MODEL_ENV, registry_authority

NOW = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)
AS_OF = datetime(2026, 11, 10, 13, 27, 12, tzinfo=timezone.utc)
COLUMNS = ["sport", "event_id", "description", "start_utc", "market", "side", "selection", "line",
           "odds_american", "quote_status", "price_id", "snapshot_as_of_utc", "source_attempt_id"]


def z():
    return zipfile.ZipFile(FROZEN_ZIP)


def nov10_capture(dest: Path) -> Path:
    """The archived Nov 10 raw Bovada payload in `gambling fetch` quotes.csv layout."""
    with z() as f:
        raw = json.loads(f.read(NOV10_PREFIX + "snapshot/raw.json"))
    with open(dest, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, COLUMNS, lineterminator="\n")
        w.writeheader()
        for e in parse_feed(raw, "NFL", AS_OF):
            if not e.physical_game or e.live:
                continue
            for q in e.quotes:
                w.writerow(dict(sport="NFL", event_id=e.event_id, description=e.description, start_utc=e.start_utc,
                                market=q.market, side=q.side, selection=q.selection, line=q.line,
                                odds_american=q.odds_american, quote_status=q.quote_status, price_id=q.price_id,
                                snapshot_as_of_utc=AS_OF.isoformat(), source_attempt_id="nov10"))
    return dest


class NflLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with z() as f:
            (self.root / "games.csv").write_bytes(f.read(NOV10_PREFIX + "scoring/games_snapshot.csv"))
            self.frozen_board = json.loads(f.read(NOV10_PREFIX + "scoring/board.json"))
            self.archived = list(csv.DictReader(io.StringIO(
                f.read(NOV10_PREFIX + "scoring/dual_model_bet_sheet.csv").decode("utf-8"))))

    def test_driver_for_week_10_is_the_frozen_file(self):
        self.assertEqual(live.driver_text(10, "2026-11-12", 15), live.frozen_score_py())
        self.assertIn("(raw.week<13)&(raw.gameday<'2026-12-03')", live.driver_text(13, "2026-12-03", 16))

    def test_converter_reproduces_the_archived_board(self):
        from gambling.core.quotes import from_capture_csv
        quotes = live.coded(from_capture_csv(nov10_capture(self.root / "q.csv"), sport="NFL"))
        rows, skipped = live.board_rows(quotes)
        self.assertEqual(json.loads(json.dumps(live._jsonable(rows))), self.frozen_board)
        self.assertEqual(len(skipped), 2)

    def test_week_inputs(self):
        games = live.read_games(self.root / "games.csv")
        self.assertEqual(live.week_inputs(games, 10), {"cutoff": "2026-11-12", "prev_games": 15, "prev_complete": 15})
        self.assertEqual(live.week_of(games, [("WAS", "NYG")], "2026-11-12"), 10)
        with self.assertRaises(live.NflInputError):
            live.week_of(games, [("WAS", "DAL")], "2026-11-12")

    def test_stale_prior_week_blocks(self):
        with open(self.root / "games.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["season"] == "2026" and r["week"] == "9" and r["home_team"] == "NYJ" or (
                    r["season"] == "2026" and r["week"] == "9" and r["away_team"] == "NYJ"):
                r["away_score"] = r["home_score"] = ""
        with open(self.root / "stale.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        with self.assertRaisesRegex(PipelineError, "Week 9 has 14/15 final games"):
            run_nfl_daily("2026-11-12", nov10_capture(self.root / "q.csv"), self.root, None, self.root / "stale.csv",
                          authority=registry_authority(), now=NOW)

    @unittest.skipUnless(MODEL_ENV, "model environment not installed (requirements-models.txt)")
    def test_daily_runs_reproduce_the_archived_week_10_rows(self):
        cap = nov10_capture(self.root / "q.csv")
        got = []
        for n, slate in enumerate(("2026-11-12", "2026-11-15", "2026-11-16")):
            m = run_nfl_daily(slate, cap, self.root, None, self.root / "games.csv", authority=registry_authority(),
                              now=NOW.replace(minute=n))
            self.assertEqual(m["inputs"]["schedule"]["week"], 10)
            with open(Path(m["run_dir"]) / "dual_model_bet_sheet.csv", newline="", encoding="utf-8") as f:
                got += list(csv.DictReader(f))
        key = lambda r: (r["away"], r["home"], r["market"])
        want = {key(r): r for r in self.archived}
        self.assertEqual(sorted(map(key, got)), sorted(want))
        for r in got:   # same model, inputs and week: equal to the archived output within 1e-12
            for k, v in r.items():
                w = want[key(r)][k]
                if v != w:
                    self.assertAlmostEqual(float(v), float(w), delta=1e-12, msg=(key(r), k))


if __name__ == "__main__":
    unittest.main()
