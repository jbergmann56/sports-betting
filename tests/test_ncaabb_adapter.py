"""NCAABB V4 frozen-replay adapter and master append: parity with golden fixture NCAABB_V4_20261101.

The archived ``V4_scored_markets.csv`` is the reference. The full rerun and the real-master append
need the pinned model environment and the reproducibility package (``GOLDEN_EXTERNAL_DIR``).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gambling.betsheets.export import write_csv
from gambling.betsheets.ncaabb import build_frozen_sheet
from gambling.db import apply_migrations, connect
from gambling.models.ncaabb.v4_legacy import (
    CHAMPION, MASTER_DATASET, adapt, append_run_to_master, load_frozen_board, master_records_from_inputs,
    score_frozen_board,
)
from gambling.scoring.sheet import Authority

REGRESSION_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NCAABB_V4_20261101_betsheet.csv"
REGRESSION_SHA = REGRESSION_SHEET.with_suffix(".sha256")
EXTERNAL = os.environ.get("GOLDEN_EXTERNAL_DIR")
MASTER_REL = "NCAABB/basketball_audit/v4/NCAABB_DB_CLEAN_REBUILT_2021_2025.csv"


def _sklearn_18() -> bool:
    if importlib.util.find_spec("sklearn") is None or importlib.util.find_spec("pandas") is None:
        return False
    import sklearn
    return sklearn.__version__ == "1.8.0"


def registry_authority() -> Authority:
    with tempfile.TemporaryDirectory() as d:
        con = connect(Path(d) / "registry.sqlite")
        apply_migrations(con)
        auth = Authority.from_connection(con)
        con.close()
    return auth


class NcaabbAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_frozen_board()
        cls.sheet = build_frozen_sheet(registry_authority())

    def test_shape(self):
        self.assertEqual(len(self.board["scored"]), 35)
        self.assertEqual(len(self.board["quotes"]), 76)  # 14 events: 14 ML + 14 spread + 10 totals, 2 sides
        self.assertEqual(len(self.sheet), 76)
        self.assertEqual({r["model_release_id"] for r in self.sheet}, {CHAMPION})

    def test_every_archived_row_is_unchanged(self):
        for a in self.board["scored"]:
            event = a["game_id"].removeprefix("BOVADA_")
            rows = [r for r in self.sheet if r["event_id"] == event and r["market"] == a["market"]
                    and r["side"] == a["selected_side"]]
            with self.subTest(game=a["game_id"], market=a["market"]):
                self.assertEqual(len(rows), 1)
                r = rows[0]
                push = float(a["estimated_push_probability"])
                self.assertAlmostEqual(r["p_win"], (1 - push) * float(a["selected_probability"]), places=15)
                self.assertEqual(r["p_push"], push)
                self.assertEqual(r["original_tier"], a["tier"])
                self.assertEqual(r["american_odds"], float(a["quoted_odds"]))
                self.assertAlmostEqual(r["ev"], float(a["expected_unit_net_at_quote"]), places=12)
                self.assertAlmostEqual(r["full_kelly"], float(a["full_kelly"]), places=12)
                self.assertEqual(r["adjusted_kelly"], float(a["final_recommended_kelly"]))
                self.assertIn("V4_EVIDENCE_FACTOR_HEURISTIC", r["adjusted_kelly_method"])
                self.assertEqual(r["adjusted_kelly_certification"], "LEGACY_NOT_PORTFOLIO_CERTIFIED")

    def test_eligibility_follows_recorded_stake_eligible(self):
        eligible = {(a["game_id"].removeprefix("BOVADA_"), a["market"], a["selected_side"])
                    for a in self.board["scored"] if a["stake_eligible"] == "True"}
        qualified = {(r["event_id"], r["market"], r["side"]) for r in self.sheet if r["status"] == "PRODUCTION_QUALIFIED"}
        self.assertEqual(qualified, eligible)
        self.assertEqual(Counter(r["original_tier"] for r in self.sheet if r["status"] == "PRODUCTION_QUALIFIED"),
                         Counter({"Lean": 7, "B": 2}))
        self.assertTrue(all(r["ev"] > 0 for r in self.sheet if r["status"] == "PRODUCTION_QUALIFIED"))

    def test_blocked_event_is_shown(self):
        blocked = [r for r in self.sheet if r["model_status"] == "BLOCKED"]
        self.assertEqual({(r["away"], r["home"]) for r in blocked}, {("Villanova", "Notre Dame")})
        self.assertEqual(len(blocked), 6)
        self.assertTrue(all(r["quote_status"] == "NOT_PREGAME" for r in blocked))

    def test_blocked_reason_comes_from_the_preparer_when_available(self):
        quotes = self.board["quotes"]
        rows = adapt(self.board["scored"], quotes, [{"game_id": "BOVADA_32737776",
                                                     "input_status": "BLOCKED: Captured after scheduled tip / not a pregame quote"}])
        reasons = {r.reason for r in rows if r.status == "BLOCKED"}
        self.assertEqual(reasons, {"PREPARER_BLOCKED: Captured after scheduled tip / not a pregame quote"})

    def test_integer_line_uses_v4_push_estimate(self):
        a = dict(next(r for r in self.board["scored"] if r["market"] == "Spread"))
        q = next(q for q in self.board["quotes"] if q.event_id == a["game_id"].removeprefix("BOVADA_")
                 and q.market == "Spread" and q.side == a["selected_side"])
        object.__setattr__(q, "line", float(round(q.line)) or 1.0)  # synthetic integer line
        a["away_spread"] = str(q.line if a["selected_side"] == "Away" else -q.line)
        a["estimated_push_probability"] = "0.04"
        opp = next(x for x in self.board["quotes"] if x.event_id == q.event_id and x.market == "Spread" and x is not q)
        row = [r for r in adapt([a], [q, opp]) if r.quote_id == q.quote_id][0]
        p = float(a["selected_probability"])
        self.assertAlmostEqual(row.p_win, 0.96 * p)
        self.assertAlmostEqual(row.p_loss, 0.96 * (1 - p))
        self.assertEqual(row.push_probability_status, "MODEL")

    def test_master_records_copy_shared_columns_only(self):
        cols = ["game_id", "season", "game_date", "away_team", "home_team", "away_spread", "away_score",
                "record_origin", "notes", "away_spread_result", "actual_bet_status"]
        recs = master_records_from_inputs(self.board["inputs"], cols, "run-1")
        self.assertEqual(len(recs), 13)
        r0, i0 = recs[0], self.board["inputs"][0]
        self.assertEqual(r0["game_id"], i0["espn_game_id"])
        self.assertEqual((r0["away_team"], r0["away_spread"], r0["away_score"]),
                         (i0["away_team"], i0["away_spread"], i0["away_score"]))
        self.assertEqual((r0["away_spread_result"], r0["actual_bet_status"]), ("", ""))  # never invented
        self.assertNotIn("run-1", r0["notes"])  # deterministic: reruns append nothing
        self.assertEqual(recs, master_records_from_inputs(self.board["inputs"], cols, "run-2"))
        self.assertEqual(set(r0), set(cols))

    def test_regression_sheet_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            digest = write_csv(self.sheet, Path(d) / "sheet.csv")
            produced = (Path(d) / "sheet.csv").read_bytes()
        self.assertEqual(produced, REGRESSION_SHEET.read_bytes())
        self.assertEqual(REGRESSION_SHA.read_text().split()[0], digest)
        self.assertEqual(hashlib.sha256(produced).hexdigest(), digest)

    def test_chronological(self):
        starts = [r["start_time_utc"] for r in self.sheet]
        self.assertEqual(starts, sorted(starts))


@unittest.skipUnless(EXTERNAL and _sklearn_18(), "needs GOLDEN_EXTERNAL_DIR and the pinned model environment")
class NcaabbExternalTests(unittest.TestCase):
    def test_full_rerun_reproduces_rows_and_preparer_reason(self):
        quotes, rows, board = score_frozen_board(Path(EXTERNAL))
        self.assertTrue(all(r["status"] == "IDENTICAL" for r in board["report"]))
        archived = adapt(load_frozen_board()["scored"], quotes)
        key = lambda s: (s.release_id, s.quote_id)  # noqa: E731
        fresh = {key(s): s for s in rows if s.status != "BLOCKED"}
        for s in archived:
            if s.status != "BLOCKED":
                self.assertEqual(fresh[key(s)].p_win, s.p_win)
                self.assertEqual(fresh[key(s)].adjusted_kelly, s.adjusted_kelly)
        self.assertEqual({s.reason for s in rows if s.status == "BLOCKED"},
                         {"PREPARER_BLOCKED: Captured after scheduled tip / not a pregame quote"})

    def test_run_appends_to_the_real_master_once(self):
        from gambling.modeldata import open_store
        with tempfile.TemporaryDirectory() as d:
            store = open_store(Path(d) / "gambling.sqlite")
            data = (Path(EXTERNAL) / MASTER_REL).read_bytes()
            sha = store.register_source(data, "NCAABB_DB_CLEAN_REBUILT_2021_2025.csv",
                                        "CONTAINS_USER_OBSERVATION_FLAGS", "reproducibility package", "test")
            store.ensure_dataset(MASTER_DATASET, "games", "NCAABB", "NCAABB master")
            base = store.import_version(MASTER_DATASET, "base", sha, "csv", "test", time_column="start_time_utc",
                                        key_columns=["game_id"])
            store.register_run("ncaabb-nov01", "REPLAY", [CHAMPION], {}, [], sport="NCAABB")
            inputs = load_frozen_board()["inputs"]
            vid = append_run_to_master(store, inputs, "ncaabb-nov01")
            self.assertEqual(store.chain(MASTER_DATASET), [base, vid])
            self.assertEqual(store.fetchone("SELECT row_count, produced_by_run FROM md_dataset_versions "
                                            "WHERE version_id = ?", (vid,)), (13, "ncaabb-nov01"))
            master = store.master_rows(MASTER_DATASET)
            self.assertEqual(len(master), 29008 + 13)
            store.register_run("ncaabb-nov01-rerun", "REPLAY", [CHAMPION], {}, [], sport="NCAABB")
            self.assertIsNone(append_run_to_master(store, inputs, "ncaabb-nov01-rerun"))  # nothing new
            with self.assertRaisesRegex(Exception, "not registered"):
                append_run_to_master(store, [dict(inputs[0], away_score="70")], "unregistered-run")
            store.con.close()


if __name__ == "__main__":
    unittest.main()
