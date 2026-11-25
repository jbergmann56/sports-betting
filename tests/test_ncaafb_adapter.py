"""NCAAFB Week 8+ frozen-replay adapter: parity with golden fixture NCAAFB_20261102.

The fixture's archived ``ALL_62_GAMES_BOTH_MODEL_TIERS.csv`` is the reference (the user database
has no Nov 2 NCAAFB score batch). Original probabilities, tiers and EV must be unchanged;
wager eligibility comes only from the registry at quote time.
"""
from __future__ import annotations

import copy
import dataclasses
import csv
import hashlib
import importlib.util
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gambling.betsheets.export import write_csv
from gambling.betsheets.ncaafb import build_frozen_sheet
from gambling.db import apply_migrations, connect
from gambling.models.ncaafb.w8plus_legacy import (
    ML_RULE, MARKET_RELEASES, OU_RESEARCH, SPREAD_CHALLENGER, SPREAD_CHAMPION, adapt, check_against_quoted_lines,
    load_frozen_board, run_frozen_scorer,
)
from gambling.scoring.sheet import Authority

REGRESSION_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NCAAFB_20261102_betsheet.csv"
REGRESSION_SHA = REGRESSION_SHEET.with_suffix(".sha256")
MODEL_ENV = all(importlib.util.find_spec(m) for m in ("pandas", "numpy", "scipy"))


def registry_authority() -> Authority:
    with tempfile.TemporaryDirectory() as d:
        con = connect(Path(d) / "registry.sqlite")
        apply_migrations(con)
        auth = Authority.from_connection(con)
        con.close()
    return auth


def _same(tc, x, y):
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        tc.assertEqual(x, y)
        return
    tc.assertLessEqual(abs(fx - fy), 1e-9, (x, y))


def _f(v):
    return None if v in (None, "") else float(v)


class NcaafbAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_frozen_board()
        cls.sheet = build_frozen_sheet(registry_authority())

    def rows_for(self, archived, release):
        market = {"ML": "Moneyline"}.get(archived["Market"], archived["Market"])
        return [r for r in self.sheet if str(r["event_id"]) == archived["EventID"] and r["market"] == market
                and r["model_release_id"] == release]

    def test_shape_one_row_per_side_per_market_release(self):
        self.assertEqual(len(self.board["sheet"]), 186)
        self.assertEqual(len(self.sheet), 62 * (2 * 2 + 2 + 2))
        for r in self.sheet:
            self.assertIn(r["model_release_id"], MARKET_RELEASES[r["market"]])

    def test_every_archived_tier_probability_and_ev_is_unchanged(self):
        for a in self.board["sheet"]:
            pairs = [(SPREAD_CHAMPION, "Champion"), (SPREAD_CHALLENGER, "Challenger")] if a["Market"] == "Spread" \
                else [(ML_RULE if a["Market"] == "ML" else OU_RESEARCH, "Champion")]
            for release, prefix in pairs:
                rows = self.rows_for(a, release)
                evaluated = [r for r in rows if r["model_status"] != "NOT_EVALUATED_BY_MODEL"]
                with self.subTest(event=a["EventID"], market=a["Market"], release=release):
                    self.assertEqual(len(rows), 2)
                    self.assertEqual(len(evaluated), 1)
                    r = evaluated[0]
                    self.assertEqual(r["original_tier"], a[prefix + "Tier"])
                    p = _f(a[prefix + "P"])
                    if p is None:
                        self.assertIsNone(r["ev"])
                        self.assertIn(r["model_status"], ("EVALUATED", "UNSCORED"))
                    else:
                        if a["Selection"]:
                            self.assertEqual(r["selection"].split(" (#")[0], a["Selection"].split(" (#")[0])
                        self.assertEqual(r["p_win"] if r["p_win"] is not None else r["p_win_given_decisive"], p)
                        self.assertAlmostEqual(r["ev"], float(a[prefix + "EV"]), places=12)
                        self.assertAlmostEqual(r["full_kelly"], float(a[prefix + "FullKelly"]), places=12)

    def test_wager_eligibility_comes_from_the_registry(self):
        status = Counter((r["model_release_id"], r["status"]) for r in self.sheet)
        self.assertEqual(status[(SPREAD_CHAMPION, "PRODUCTION_QUALIFIED")], 1)       # Texas State +6.5 (B+)
        self.assertEqual(status[(ML_RULE, "PRODUCTION_QUALIFIED")], 5)               # five A existing dogs
        self.assertEqual(status[(SPREAD_CHALLENGER, "QUALIFIED_NOT_WAGER_AUTHORIZED")], 6)
        self.assertEqual(status[(SPREAD_CHALLENGER, "PRODUCTION_QUALIFIED")], 0)
        self.assertEqual({r["status"] for r in self.sheet if r["model_release_id"] == OU_RESEARCH},
                         {"LEAN", "PASS", "NOT_EVALUATED_BY_MODEL"})
        for r in self.sheet:
            if r["status"] == "PRODUCTION_QUALIFIED":
                self.assertTrue(r["release_wager_authorized"])
                self.assertGreater(r["ev"], 0)

    def test_integer_lines_are_conditional_and_half_points_unconditional(self):
        for r in self.sheet:
            if r["model_status"] == "CONDITIONAL_SCORED":
                self.assertEqual(r["line"], round(r["line"]))
                self.assertEqual(r["push_probability_status"], "UNKNOWN")
                self.assertIsNone(r["p_push"])
            elif r["model_status"] == "SCORED":
                self.assertTrue(r["market"] == "Moneyline" or r["line"] != round(r["line"]))
                self.assertEqual(r["p_push"], 0.0)

    def test_unscored_srs_gate_keeps_hypothetical_out_of_probability(self):
        rows = [r for r in self.sheet if r["model_status"] == "UNSCORED"]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["p_win"])
        self.assertTrue(rows[0]["status_reason"].startswith("Unscored: SRS gate"))

    def test_adjusted_kelly(self):
        ou = [r for r in self.sheet if r["model_release_id"] == OU_RESEARCH and r["status"] == "LEAN"]
        self.assertEqual(len(ou), 2)
        self.assertTrue(all(r["adjusted_kelly"] == 0.0 and r["adjusted_kelly_method"] for r in ou))
        sized = [r for r in self.sheet if r["model_release_id"] != OU_RESEARCH and r["ev"] is not None]
        self.assertTrue(all(r["adjusted_kelly"] is None and "Joint sizing not run" in r["adjusted_kelly_null_reason"]
                            for r in sized))

    def test_complements_are_labelled_never_eligible(self):
        derived = [r for r in self.sheet if r["derived_p_win"] is not None]
        self.assertTrue(derived)
        for r in derived:
            self.assertEqual(r["model_status"], "NOT_EVALUATED_BY_MODEL")
            self.assertEqual(r["status"], "NOT_EVALUATED_BY_MODEL")
            self.assertIsNone(r["original_tier"] if r["original_tier"] != "NONE" else None)

    def test_quote_ids_come_from_bovada_outcomes(self):
        self.assertTrue(all(r["quote_id"].startswith("BOVADA:") and r["quote_id"][7:].isdigit() for r in self.sheet))
        lines = copy.deepcopy(self.board["quoted_lines"])
        lines[0]["AwayML"] = "+999"
        with self.assertRaisesRegex(ValueError, "raw Bovada outcome"):
            check_against_quoted_lines(self.board["quotes"], lines)

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
        fresh = adapt(run_frozen_scorer(), self.board["quotes"])
        archived = adapt(self.board["sheet"], self.board["quotes"])
        key = lambda s: (s.release_id, s.quote_id)
        self.assertEqual(len(fresh), len(archived))
        for f, a in zip(sorted(fresh, key=key), sorted(archived, key=key)):
            fd, ad = dataclasses.asdict(f), dataclasses.asdict(a)
            with self.subTest(release=a.release_id, quote=a.quote_id):
                self.assertEqual(set(fd["diagnostics"]), set(ad["diagnostics"]))
                for k in fd:
                    pairs = ([(fd["diagnostics"][d], ad["diagnostics"][d]) for d in ad["diagnostics"]]
                             if k == "diagnostics" else [(fd[k], ad[k])])
                    for x, y in pairs:
                        _same(self, x, y)  # golden rule: numbers within 1e-9, everything else exact


if __name__ == "__main__":
    unittest.main()
