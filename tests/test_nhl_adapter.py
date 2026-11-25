"""NHL Day-0 frozen-replay adapter: parity with the golden fixture NHL_DAY0_20261112.

The fixture's archived ``nhl_scores_20261112.csv`` (NHL rows of 20261112_all_model_scores.csv)
is the reference. Original probabilities, EV, Full Kelly, tiers and statuses must be unchanged.
The scorer is stdlib-only, so these tests need no model environment.
"""
from __future__ import annotations

import csv
import hashlib
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gambling.betsheets.export import write_csv
from gambling.betsheets.nhl import build_capture_sheet
from gambling.db import apply_migrations, connect
from gambling.models.nhl.day0_legacy import (
    MARKET_RELEASES, RELEASE_BY_LABEL, RELEASES, Day0Inputs, score_capture,
)
from gambling.scoring.sheet import Authority

FX = Path(__file__).parent / "golden" / "fixtures" / "NHL_DAY0_20261112"
QUOTES = FX / "inputs" / "20261112_quotes.csv"
EXPECTED = FX / "expected" / "nhl_scores_20261112.csv"
REGRESSION_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NHL_DAY0_20261112_betsheet.csv"
REGRESSION_SHA = REGRESSION_SHEET.with_suffix(".sha256")


def registry_authority() -> Authority:
    d = tempfile.mkdtemp()
    con = connect(Path(d) / "registry.sqlite")
    apply_migrations(con)
    con.close()
    return Authority.from_sqlite(str(Path(d) / "registry.sqlite"))


def _f(v):
    return None if v in (None, "") else float(v)


class NhlAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = registry_authority()
        cls.sheet = build_capture_sheet(QUOTES, cls.authority)
        with open(EXPECTED, newline="", encoding="utf-8") as f:
            cls.expected = list(csv.DictReader(f))

    def row(self, event_id, market, side, release):
        hits = [r for r in self.sheet if str(r["event_id"]) == event_id and r["market"] == market
                and r["side"] == side and r["model_release_id"] == release]
        self.assertEqual(len(hits), 1, (event_id, market, side, release))
        return hits[0]

    def test_every_archived_row_is_reproduced_unchanged(self):
        self.assertEqual(len(self.sheet), len(self.expected))
        for e in self.expected:
            r = self.row(e["event_id"], e["market"], e["side"], RELEASE_BY_LABEL[e["model_version"]])
            with self.subTest(event=e["event_id"], market=e["market"], side=e["side"], model=e["model_version"]):
                self.assertEqual(r["recorded_role"], e["model_role"])
                self.assertEqual(r["original_tier"], e["tier"])
                self.assertEqual(r["model_action"], e["status"])
                self.assertEqual(r["american_odds"], float(e["odds"]))
                self.assertEqual(r["line"], _f(e["line"]))
                if e["model_p"] == "":
                    self.assertEqual(r["model_status"], "UNSCORED")
                    self.assertIsNone(r["ev"])
                    self.assertTrue(e["reason"].startswith(r["status_reason"]))
                else:
                    self.assertEqual(r["p_win"], float(e["model_p"]))
                    self.assertAlmostEqual(r["ev"], float(e["ev"]), places=12)          # shared pricing
                    self.assertAlmostEqual(r["full_kelly"], float(e["full_kelly"]), places=12)
                    self.assertEqual(r["legacy_ev"], float(e["ev"]))
                self.assertIsNone(r["adjusted_kelly"])
                self.assertTrue(r["adjusted_kelly_null_reason"])

    def test_original_status_split_and_no_wagering(self):
        self.assertEqual(Counter(r["status"] for r in self.sheet),
                         Counter(e["status"] for e in self.expected))  # 81 PASS / 44 UNSCORED / 7 RESEARCH
        self.assertFalse(any(r["release_wager_authorized"] for r in self.sheet))
        self.assertNotIn("QUALIFIED", {r["action_class"] for r in self.sheet})
        self.assertNotIn("PRODUCTION_QUALIFIED", {r["status"] for r in self.sheet})

    def test_releases_follow_their_market(self):
        for r in self.sheet:
            self.assertIn(r["model_release_id"], MARKET_RELEASES[r["market"]])
        self.assertEqual({r["model_release_id"] for r in self.sheet}, set(RELEASES))
        self.assertEqual(Counter(r["release_role"] for r in self.sheet), Counter(CHAMPION=66, CHALLENGER=66))

    def test_integer_totals_carry_the_models_push_probability(self):
        rows = [r for r in self.sheet if r["market"] == "Total" and r["line"] == 6.0 and r["p_win"] is not None]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["push_probability_status"], "MODEL")
            self.assertGreater(r["p_push"], 0)
            self.assertAlmostEqual(r["p_win"] + r["p_loss"] + r["p_push"], 1.0, places=12)
        half = [r for r in self.sheet if r["p_win"] is not None and r not in rows]
        self.assertTrue(all(r["p_push"] == 0.0 and r["push_probability_status"] == "ZERO_BY_LINE" for r in half))

    def test_chronological_order(self):
        starts = [r["start_time_utc"] for r in self.sheet]
        self.assertEqual(starts, sorted(starts))

    def test_incomplete_board_is_shown_not_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            with open(QUOTES, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            victim = next(r for r in rows if r["sport"] == "NHL")
            kept = [r for r in rows if not (r["event_id"] == victim["event_id"] and r["market"] == "Total"
                                            and r["side"] == "Under")]
            path = Path(d) / "quotes.csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(kept)
            sheet = build_capture_sheet(path, self.authority)
        ev = [r for r in sheet if str(r["event_id"]) == victim["event_id"]]
        self.assertEqual(len(ev), 12)  # 6 sides x 2 releases, the missing side included
        self.assertTrue(all(r["model_status"] == "UNSCORED" for r in ev))
        offered = [r for r in ev if r["quote_status"] == "OFFERED_PREGAME"]
        self.assertTrue(all(r["status_reason"].startswith("INCOMPLETE_OR_NOT_PREGAME_BOARD") for r in offered))
        self.assertEqual(len([r for r in sheet if r["model_status"] == "SCORED"]), 88 - 8)

    def test_frozen_inputs_are_hash_checked(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "controls.csv"
            shutil.copy(Day0Inputs.from_fixture().controls, bad)
            with open(bad, "a") as f:
                f.write("\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                score_capture(QUOTES, Day0Inputs(bad, Day0Inputs.from_fixture().original_adapter))

    def test_regression_sheet_is_stable(self):
        with tempfile.TemporaryDirectory() as d:
            digest = write_csv(self.sheet, Path(d) / "sheet.csv")
            produced = (Path(d) / "sheet.csv").read_bytes()
        self.assertEqual(digest, hashlib.sha256(produced).hexdigest())
        self.assertEqual(produced, REGRESSION_SHEET.read_bytes())
        self.assertEqual(REGRESSION_SHA.read_text().split()[0], digest)


if __name__ == "__main__":
    unittest.main()
