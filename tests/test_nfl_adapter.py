"""NFL REV2-CAL / W8 frozen-replay adapter: parity with the golden fixture and archive records.

Original probabilities, tiers, actions and statuses must be unchanged. The
archived ``model_scores`` rows for batch NFL_20261110_072712CST (inside the
frozen ZIP) are the independent reference.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import sqlite3
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from gambling.betsheets.export import write_csv
from gambling.betsheets.nfl import build_frozen_sheet
from gambling.db import apply_migrations, connect
from gambling.models.nfl.rev2_legacy import (
    CHALLENGER, CHAMPION, FROZEN_ZIP, NOV10_PREFIX, load_frozen_board, run_frozen_scorer, score_frozen_board,
)
from gambling.scoring.pricing import net_multiple
from gambling.scoring.sheet import Authority

REGRESSION_SHEET = Path(__file__).parent / "fixtures" / "betsheets" / "NFL_20261110_072712CST_betsheet.csv"
REGRESSION_SHA = REGRESSION_SHEET.with_suffix(".sha256")
BATCH = "NFL_20261110_072712CST"
RELEASE_BY_ROLE = {"CHAMPION": CHAMPION, "CHALLENGER": CHALLENGER}


def registry_authority() -> Authority:
    with tempfile.TemporaryDirectory() as d:
        con = connect(Path(d) / "registry.sqlite")
        apply_migrations(con)
        auth = Authority.from_connection(con)
        con.close()
    return auth


def archived_scores() -> list[dict]:
    with zipfile.ZipFile(FROZEN_ZIP) as z, tempfile.TemporaryDirectory() as d:
        path = z.extract("GAMBLING_ROLLING_SCORING_HISTORY.sqlite", d)
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("select * from model_scores where batch_id=?", (BATCH,))]
        con.close()
    return rows


class NflAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_frozen_board()
        cls.quotes, cls.scores = score_frozen_board()
        cls.sheet = build_frozen_sheet(registry_authority())
        cls.archived = archived_scores()

    def test_every_quoted_side_scored_by_both_releases(self):
        self.assertEqual(len(self.quotes), 72)
        self.assertEqual(len({q.event_id for q in self.quotes}), 12)
        self.assertEqual(len(self.scores), 144)
        self.assertEqual(len({(s.release_id, s.quote_id) for s in self.scores}), 144)
        self.assertEqual(len(self.sheet), 144)

    def test_probabilities_tiers_and_legacy_values_unchanged(self):
        by_q = {q.quote_id: q for q in self.quotes}
        checked = 0
        for r in self.board["sheet"]:
            for prefix, release in (("champion", CHAMPION), ("challenger", CHALLENGER)):
                if not r[f"{prefix}_p"]:
                    continue
                rows = [s for s in self.scores if s.release_id == release and s.has_probability
                        and by_q[s.quote_id].away == r["away"] and by_q[s.quote_id].home == r["home"]
                        and by_q[s.quote_id].market == r["market"]]
                self.assertEqual(len(rows), 1)
                s = rows[0]
                p = s.p_win if s.p_win is not None else s.p_win_given_decisive
                self.assertEqual(p, float(r[f"{prefix}_p"]))  # exact, no rounding
                self.assertEqual(s.legacy_ev, float(r[f"{prefix}_ev"]))
                b = net_multiple(by_q[s.quote_id].american_odds)
                self.assertAlmostEqual(b * p - (1 - p), float(r[f"{prefix}_ev"]), places=12)
                self.assertAlmostEqual(max(0.0, p - (1 - p) / b), float(r[f"{prefix}_full_kelly"]), places=12)
                checked += 1
        self.assertEqual(checked, 10)  # 4 champion + 6 challenger probabilities

    def test_sheet_matches_archived_records_row_by_row(self):
        sheet = {(r["event_id"], r["market"], r["side"], r["model_release_id"]): r for r in self.sheet}
        status_map = {"PRODUCTION_QUALIFIED": "PRODUCTION_QUALIFIED", "RESEARCH_POSITIVE_EV": "RESEARCH_POSITIVE_EV",
                      "PASS": "PASS"}
        self.assertEqual(len(self.archived), 72)
        for a in self.archived:
            release = RELEASE_BY_ROLE[a["model_role"]]
            sides = [a["selection_side"]] if a["selection_side"] else \
                (["Over", "Under"] if a["market"] == "Total" else ["Away", "Home"])
            for side in sides:
                row = sheet[(str(a["event_id"]), a["market"], side, release)]
                with self.subTest(event=a["event_id"], market=a["market"], side=side, role=a["model_role"]):
                    self.assertEqual(row["status"], status_map[a["action_status"]])
                    if a["tier"] is not None:
                        self.assertEqual(row["original_tier"], a["tier"])
                    if a["model_probability"] is not None:
                        p = row["p_win"] if row["p_win"] is not None else row["p_win_given_decisive"]
                        self.assertEqual(p, a["model_probability"])
                        self.assertAlmostEqual(row["ev"], a["expected_value"], places=12)
                        self.assertAlmostEqual(row["full_kelly"], a["full_kelly"], places=12)
                        self.assertAlmostEqual(row["american_odds"], a["quoted_odds"])
                        if a["quoted_line"] is not None:
                            self.assertAlmostEqual(row["line"], a["quoted_line"])
                    else:
                        self.assertIsNone(row["p_win"])
                        self.assertIsNone(row["ev"])

    def test_status_counts_match_archive(self):
        archived = Counter(a["action_status"] for a in self.archived)
        self.assertEqual(archived, Counter({"PASS": 70, "PRODUCTION_QUALIFIED": 1, "RESEARCH_POSITIVE_EV": 1}))
        ours = Counter(r["status"] for r in self.sheet)
        self.assertEqual(ours["PRODUCTION_QUALIFIED"], 1)
        self.assertEqual(ours["RESEARCH_POSITIVE_EV"], 1)
        self.assertEqual(ours["NOT_EVALUATED_BY_MODEL"], 42)

    def test_production_qualifier_is_champion_and_wager_authorized_at_quote_time(self):
        pq = [r for r in self.sheet if r["status"] == "PRODUCTION_QUALIFIED"][0]
        self.assertEqual((pq["model_release_id"], pq["release_role"], pq["release_wager_authorized"]),
                         (CHAMPION, "CHAMPION", True))
        self.assertEqual((pq["selection"], pq["line"], pq["original_tier"]), ("BAL", -5.0, "A"))
        research = [r for r in self.sheet if r["status"] == "RESEARCH_POSITIVE_EV"][0]
        self.assertEqual((research["model_release_id"], research["release_wager_authorized"]), (CHALLENGER, False))

    def test_adjusted_kelly_null_with_release_reason(self):
        for r in self.sheet:
            self.assertIsNone(r["adjusted_kelly"])
            self.assertTrue(r["adjusted_kelly_null_reason"])

    def test_complements_only_for_model_probability_sides(self):
        derived = [r for r in self.sheet if r["derived_probability_source"]]
        self.assertTrue(derived)
        for r in derived:
            self.assertEqual((r["model_status"], r["original_tier"], r["ev"]), ("NOT_EVALUATED_BY_MODEL", "NONE", None))

    def test_bet_sheet_regression_file(self):
        with tempfile.TemporaryDirectory() as d:
            digest = write_csv(self.sheet, Path(d) / "sheet.csv")
        self.assertEqual(digest, REGRESSION_SHA.read_text().split()[0],
                         "NFL Nov 10 bet sheet changed; if intended, review and document before updating")


@unittest.skipIf(any(importlib.util.find_spec(m) is None for m in ("pandas", "numpy", "scipy")),
                 "model environment not installed (requirements-models.txt)")
class NflFreshExecutionTests(unittest.TestCase):
    def test_fresh_frozen_execution_gives_identical_adapter_rows(self):
        archived = score_frozen_board()[1]
        fresh = score_frozen_board(rerun=True)[1]
        self.assertEqual(len(fresh), len(archived))
        for a, b in zip(archived, fresh):
            self.assertEqual((a.release_id, a.quote_id, a.status, a.original_tier, a.action_class),
                             (b.release_id, b.quote_id, b.status, b.original_tier, b.action_class))
            for f in ("p_win", "p_win_given_decisive", "legacy_ev", "legacy_full_kelly"):
                x, y = getattr(a, f), getattr(b, f)
                if x is None:
                    self.assertIsNone(y)
                else:
                    self.assertAlmostEqual(x, y, delta=1e-9)


if __name__ == "__main__":
    unittest.main()
