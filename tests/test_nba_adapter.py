"""NBA R4 frozen-replay adapter: parity with golden fixture NBA_R4_20261112.

The fixture's archived ``forecasts.csv`` is the reference (the user database has no Nov 12 NBA
batch). Tiers, probabilities, EV, Full Kelly and the shadow portfolio Adjusted Kelly must be unchanged.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gambling.betsheets.export import write_csv
from gambling.betsheets.nba import build_frozen_sheet
from gambling.db import apply_migrations, connect
from gambling.models.nba.r4_legacy import (
    CAPTURE_20261112, CHALLENGER, CHAMPION, FIXTURE, adapt, load_frozen_board, quotes_json_from_capture,
    run_frozen_scorer,
)
from gambling.scoring.sheet import Authority

REGRESSION_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NBA_R4_20261112_betsheet.csv"
REGRESSION_SHA = REGRESSION_SHEET.with_suffix(".sha256")
MODEL_ENV = all(importlib.util.find_spec(m) for m in ("pandas", "numpy", "scipy"))


def registry_authority() -> Authority:
    with tempfile.TemporaryDirectory() as d:
        con = connect(Path(d) / "registry.sqlite")
        apply_migrations(con)
        auth = Authority.from_connection(con)
        con.close()
    return auth


def _f(v):
    return None if v in (None, "") else float(v)


def _same(tc, x, y):
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        tc.assertEqual(x, y)
        return
    tc.assertLessEqual(abs(fx - fy), 1e-9, (x, y))


class NbaAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_frozen_board()
        cls.sheet = build_frozen_sheet(registry_authority())

    def test_quote_json_is_rebuilt_byte_identically_from_the_capture(self):
        rebuilt = quotes_json_from_capture(CAPTURE_20261112, "2026-11-12")
        self.assertEqual(rebuilt.encode(), (FIXTURE / "inputs" / "2026-11-12_nba_quotes.json").read_bytes())
        self.assertEqual(quotes_json_from_capture(CAPTURE_20261112, "2026-11-13"), "[]")

    def test_shape(self):
        self.assertEqual(len(self.board["sheet"]), 12)
        self.assertEqual(len(self.sheet), 4 * 6 * 2)
        self.assertEqual(Counter(r["model_release_id"] for r in self.sheet), Counter({CHAMPION: 24, CHALLENGER: 24}))

    def test_every_archived_row_is_unchanged(self):
        for a in self.board["sheet"]:
            rows = [r for r in self.sheet if r["away"] == a["Away"] and r["home"] == a["Home"]
                    and r["market"] == a["Market"] and r["model_release_id"] == CHAMPION
                    and r["model_status"] != "NOT_EVALUATED_BY_MODEL"]
            with self.subTest(game=a["Game"], market=a["Market"]):
                self.assertEqual(len(rows), 1)
                r = rows[0]
                self.assertEqual(r["original_tier"], a["Tier"])
                self.assertEqual(r["model_action"], a["Sizing_Status"])
                self.assertEqual(r["american_odds"], float(a["Odds"]))
                p = _f(a["Model_P"])
                if p is None:
                    self.assertEqual(r["model_status"], "EVALUATED")
                    self.assertIsNone(r["ev"])
                    self.assertIsNone(r["adjusted_kelly"])
                else:
                    self.assertEqual(r["p_win"] if r["p_win"] is not None else r["p_win_given_decisive"], p)
                    self.assertAlmostEqual(r["ev"], float(a["EV"]), places=12)
                    self.assertAlmostEqual(r["full_kelly"], float(a["Full_Kelly"]), places=12)
                    self.assertEqual(r["adjusted_kelly"], float(a["Adjusted_Kelly"]))
                    self.assertEqual(r["adjusted_kelly_certification"], "LEGACY_NOT_PORTFOLIO_CERTIFIED")
                    self.assertIn("JOINT_POSTERIOR_PREDICTIVE_EXPECTED_LOG", r["adjusted_kelly_method"])

    def test_statuses_and_authority(self):
        self.assertEqual(Counter(r["status"] for r in self.sheet if r["model_release_id"] == CHAMPION),
                         Counter({"PRODUCTION_QUALIFIED": 2, "PASS": 10, "NOT_EVALUATED_BY_MODEL": 12}))
        for r in self.sheet:
            if r["status"] == "PRODUCTION_QUALIFIED":
                self.assertTrue(r["release_wager_authorized"])
                self.assertGreater(r["ev"], 0)
        r3 = [r for r in self.sheet if r["model_release_id"] == CHALLENGER]
        self.assertTrue(all(r["status"] == "BLOCKED" and r["status_reason"].startswith("ARTIFACTS_MISSING")
                            for r in r3))
        self.assertFalse(any(r["release_wager_authorized"] for r in r3))

    def test_integer_spread_is_conditional(self):
        tor = [r for r in self.sheet if r["selection"] == "Toronto Raptors" and r["market"] == "Spread"
               and r["model_release_id"] == CHAMPION][0]
        self.assertEqual(tor["line"], 9.0)
        self.assertEqual(tor["model_status"], "CONDITIONAL_SCORED")
        self.assertEqual(tor["push_probability_status"], "UNKNOWN")
        was = [r for r in self.sheet if r["selection"] == "Washington Wizards" and r["market"] == "Spread"
               and r["model_release_id"] == CHAMPION][0]
        self.assertEqual(was["model_status"], "SCORED")
        self.assertEqual(was["p_push"], 0.0)

    def test_unevaluated_sides_and_totals_under_only(self):
        for r in self.sheet:
            if r["model_release_id"] == CHAMPION and r["market"] == "Total" and r["side"] == "Over":
                self.assertEqual(r["status_reason"], "RULE_EVALUATES_UNDER_ONLY")

    def test_quote_ids_are_capture_price_ids(self):
        self.assertTrue(all(r["quote_id"].startswith("BOVADA:") and r["quote_id"][7:].isdigit() for r in self.sheet))
        self.assertEqual({r["quote_as_of_utc"] for r in self.sheet}, {"2026-11-12T13:38:23+00:00"})

    def test_chronological(self):
        starts = [r["start_time_utc"] for r in self.sheet]
        self.assertEqual(starts, sorted(starts))

    def test_regression_sheet_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            digest = write_csv(self.sheet, Path(d) / "sheet.csv")
            produced = (Path(d) / "sheet.csv").read_bytes()
        self.assertEqual(produced, REGRESSION_SHEET.read_bytes())
        self.assertEqual(REGRESSION_SHA.read_text().split()[0], digest)
        self.assertEqual(hashlib.sha256(produced).hexdigest(), digest)

    @unittest.skipUnless(MODEL_ENV, "model environment not installed (requirements-models.txt)")
    def test_rerun_of_frozen_scorer_gives_identical_score_rows(self):
        fresh = run_frozen_scorer(self.board["quotes_json"], self.board["history"])
        key = lambda s: (s.release_id, s.quote_id)  # noqa: E731
        a_rows = sorted(adapt(self.board["sheet"], self.board["quotes"]), key=key)
        f_rows = sorted(adapt(fresh, self.board["quotes"]), key=key)
        self.assertEqual(len(a_rows), len(f_rows))
        for f, a in zip(f_rows, a_rows):
            fd, ad = dataclasses.asdict(f), dataclasses.asdict(a)
            for k in fd:
                if k == "score_as_of_utc":
                    continue  # Frozen_UTC is the run timestamp (excluded by the golden comparison too)
                if k == "diagnostics":
                    self.assertEqual(set(fd[k]), set(ad[k]))
                    for d in ad[k]:
                        _same(self, fd[k][d], ad[k][d])
                else:
                    _same(self, fd[k], ad[k])


if __name__ == "__main__":
    unittest.main()
