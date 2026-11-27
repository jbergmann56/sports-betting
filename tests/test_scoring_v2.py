"""Adapter interface v2, push-aware pricing, complements, assembly and exports."""
from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

from gambling.core.quotes import QuoteSide, complete_board
from gambling.models.base import (
    CONDITIONAL_SCORED, EVALUATED, NOT_EVALUATED_BY_MODEL, PUSH_UNKNOWN, PUSH_ZERO_BY_LINE, QUALIFIED, SCORED,
    UNSCORED, ScoreRow, binary_probability_row, push_possible,
)
from gambling.scoring.pricing import FK_CONDITIONAL, kelly_adjusted, net_multiple, price
from gambling.scoring.sheet import COLUMNS, Authority, assemble, derive_complement, mark_new_vs_previous
from gambling.betsheets.export import champion_challenger_view, write_csv, write_excel

R = "TEST_RELEASE"


def quote(market, side, line, odds, start="2026-11-15T18:00:00+00:00", event="E1", status="OFFERED_PREGAME"):
    sel = {"Away": "Visitors", "Home": "Hosts"}.get(side, side)
    return QuoteSide("NFL", event, start, "Visitors", "Hosts", market, side, sel, line, odds,
                     f"Q:{event}:{market}:{side}", "2026-11-15T13:00:00+00:00", status)


def board(event="E1", start="2026-11-15T18:00:00+00:00"):
    return [quote("Moneyline", "Away", None, 130, start, event), quote("Moneyline", "Home", None, -150, start, event),
            quote("Spread", "Away", 3.0, -110, start, event), quote("Spread", "Home", -3.0, -110, start, event),
            quote("Total", "Over", 44.5, -105, start, event), quote("Total", "Under", 44.5, -115, start, event)]


class ScoreRowV2Tests(unittest.TestCase):
    def test_v1_positional_construction_still_works(self):
        ScoreRow(R, "q", SCORED, 0.5, 0.45, 0.05)
        ScoreRow(R, "q", UNSCORED, reason="NO_FEATURES")

    def test_conditional_requires_unknown_push_and_no_unconditional_probs(self):
        ScoreRow(R, "q", CONDITIONAL_SCORED, p_win_given_decisive=0.55,
                 probability_basis="CONDITIONAL_DECISIVE", push_probability_status=PUSH_UNKNOWN)
        with self.assertRaises(ValueError):
            ScoreRow(R, "q", CONDITIONAL_SCORED, 0.55, 0.45, 0.0, p_win_given_decisive=0.55,
                     probability_basis="CONDITIONAL_DECISIVE", push_probability_status=PUSH_UNKNOWN)
        with self.assertRaises(ValueError):
            ScoreRow(R, "q", CONDITIONAL_SCORED, p_win_given_decisive=0.55,
                     probability_basis="CONDITIONAL_DECISIVE", push_probability_status="ZERO_BY_LINE")

    def test_not_evaluated_cannot_carry_tier_probability_or_action(self):
        ScoreRow(R, "q", NOT_EVALUATED_BY_MODEL, reason="MODEL_SELECTED_OPPOSITE_SIDE")
        for kwargs in (dict(original_tier="Pass"), dict(action_class="PASS")):
            with self.assertRaises(ValueError):
                ScoreRow(R, "q", NOT_EVALUATED_BY_MODEL, reason="x", **kwargs)
        with self.assertRaises(ValueError):
            ScoreRow(R, "q", NOT_EVALUATED_BY_MODEL, 0.5, 0.5, 0.0, reason="x")

    def test_evaluated_needs_model_decision_and_no_probability(self):
        ScoreRow(R, "q", EVALUATED, original_tier="Pass", action_class="PASS")
        with self.assertRaises(ValueError):
            ScoreRow(R, "q", EVALUATED)

    def test_adjusted_kelly_requires_method(self):
        with self.assertRaises(ValueError):
            ScoreRow(R, "q", SCORED, 0.5, 0.5, 0.0, adjusted_kelly=0.01)

    def test_binary_probability_row_push_rules(self):
        half = binary_probability_row(release_id=R, quote_id="q", p_win=0.55, push_possible=push_possible("Spread", 3.5))
        self.assertEqual((half.status, half.p_push, half.push_probability_status), (SCORED, 0.0, PUSH_ZERO_BY_LINE))
        whole = binary_probability_row(release_id=R, quote_id="q", p_win=0.55, push_possible=push_possible("Spread", 3.0))
        self.assertEqual((whole.status, whole.p_win_given_decisive, whole.p_win), (CONDITIONAL_SCORED, 0.55, None))
        self.assertFalse(push_possible("Moneyline", None))
        self.assertTrue(push_possible("Total", None))


class PricingTests(unittest.TestCase):
    def test_hand_checked_unconditional_no_push(self):
        p = price(ScoreRow(R, "q", SCORED, 0.55, 0.45, 0.0), -110)
        b = 100 / 110
        self.assertAlmostEqual(p.ev, b * 0.55 - 0.45)
        self.assertAlmostEqual(p.full_kelly, (b * 0.55 - 0.45) / b)
        self.assertAlmostEqual(p.break_even, 110 / 210)

    def test_hand_checked_push_refund(self):
        p = price(ScoreRow(R, "q", SCORED, 0.5, 0.4, 0.1), 100)
        self.assertAlmostEqual(p.ev, 0.1)
        self.assertAlmostEqual(p.full_kelly, 0.1 / 0.9)

    def test_negative_ev_kelly_is_zero_not_null(self):
        p = price(ScoreRow(R, "q", SCORED, 0.4, 0.6, 0.0), -110)
        self.assertLess(p.ev, 0)
        self.assertEqual(p.full_kelly, 0.0)

    def test_conditional_matches_legacy_binary_kelly(self):
        # NFL/NCAAFB legacy: kelly = max(0, p - (1-p)/b); EV = p*b - (1-p)
        row = binary_probability_row(release_id=R, quote_id="q", p_win=0.5253, push_possible=True)
        for odds in (-117, -110, 105, 150):
            b = net_multiple(odds)
            p = price(row, odds)
            self.assertEqual(p.full_kelly_basis, FK_CONDITIONAL)
            self.assertAlmostEqual(p.ev, 0.5253 * b - 0.4747, places=12)
            self.assertAlmostEqual(p.full_kelly, max(0.0, 0.5253 - 0.4747 / b), places=12)

    def test_null_reasons(self):
        self.assertEqual(price(ScoreRow(R, "q", SCORED, 0.5, 0.5, 0.0), None).ev_null_reason, "NO_OFFERED_PRICE")
        ev = price(ScoreRow(R, "q", EVALUATED, original_tier="Pass"), -110)
        self.assertEqual((ev.ev, ev.full_kelly_null_reason), (None, "MODEL_ASSIGNS_NO_PROBABILITY"))

    def test_adjusted_kelly_passthrough_never_zero_filled(self):
        a = kelly_adjusted(ScoreRow(R, "q", SCORED, 0.5, 0.5, 0.0))
        self.assertEqual((a.value, a.null_reason), (None, "NOT_SUPPLIED_BY_RELEASE"))
        a = kelly_adjusted(ScoreRow(R, "q", SCORED, 0.5, 0.5, 0.0, adjusted_kelly=0.02,
                                    adjusted_kelly_method="V4_EVIDENCE_FACTOR_HEURISTIC",
                                    adjusted_kelly_certification="LEGACY_NOT_PORTFOLIO_CERTIFIED"))
        self.assertEqual((a.value, a.method), (0.02, "V4_EVIDENCE_FACTOR_HEURISTIC"))


class ComplementAndAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.q = board()
        qid = {(q.market, q.side): q.quote_id for q in self.q}
        self.scores = [
            binary_probability_row(release_id=R, quote_id=qid["Spread", "Away"], p_win=0.56, push_possible=True,
                                   original_tier="B+", action_class=QUALIFIED, recorded_role="CHAMPION"),
            ScoreRow(R, qid["Spread", "Home"], NOT_EVALUATED_BY_MODEL, reason="MODEL_SELECTED_OPPOSITE_SIDE"),
            ScoreRow(R, qid["Moneyline", "Away"], SCORED, 0.42, 0.58, 0.0, probability_basis="UNCONDITIONAL",
                     push_probability_status=PUSH_ZERO_BY_LINE, original_tier="Pass", action_class="PASS"),
            ScoreRow(R, qid["Moneyline", "Home"], NOT_EVALUATED_BY_MODEL, reason="MODEL_SELECTED_OPPOSITE_SIDE"),
            ScoreRow(R, qid["Total", "Over"], EVALUATED, original_tier="Pass", action_class="PASS"),
        ]  # Total Under deliberately missing -> must appear as UNSCORED

    def rows(self, authority=None):
        return assemble(self.q, self.scores, authority, releases=[R])

    def test_every_quote_side_appears_exactly_once(self):
        rows = self.rows()
        self.assertEqual(len(rows), 6)
        under = [r for r in rows if r["side"] == "Under"][0]
        self.assertEqual((under["model_status"], under["status_reason"]), (UNSCORED, "NO_ADAPTER_ROW_FOR_QUOTE"))

    def test_complements_are_labelled_and_carry_no_signal(self):
        rows = {(r["market"], r["side"]): r for r in self.rows()}
        home_spread = rows["Spread", "Home"]
        self.assertAlmostEqual(home_spread["derived_p_win_given_decisive"], 0.44)
        self.assertEqual(home_spread["derived_probability_basis"], "CONDITIONAL_DECISIVE")
        self.assertEqual((home_spread["original_tier"], home_spread["ev"], home_spread["full_kelly"]), ("NONE", None, None))
        self.assertEqual(home_spread["status"], NOT_EVALUATED_BY_MODEL)
        home_ml = rows["Moneyline", "Home"]
        self.assertEqual((home_ml["derived_p_win"], home_ml["derived_p_loss"], home_ml["derived_p_push"]), (0.58, 0.42, 0.0))
        # Over was evaluated without a probability -> no complement for Under
        self.assertIsNone(rows["Total", "Under"]["derived_p_win"])

    def test_no_complement_when_lines_are_not_mirrored(self):
        sel = binary_probability_row(release_id=R, quote_id="a", p_win=0.6, push_possible=True)
        a, b = quote("Spread", "Away", 3.0, -110), quote("Spread", "Home", -2.5, -110)
        self.assertIsNone(derive_complement(sel, a, b))

    def test_status_uses_registry_authority_at_quote_time(self):
        hist = [dict(release_id=R, role="CHAMPION", scoring_authority=1, wagering_authorized=1,
                     effective_from_utc="2026-10-01", effective_until_utc="2026-11-15T12:00:00+00:00"),
                dict(release_id=R, role="CHAMPION", scoring_authority=1, wagering_authorized=0,
                     effective_from_utc="2026-11-15T12:00:00+00:00", effective_until_utc=None)]
        away = [r for r in self.rows(Authority(hist)) if (r["market"], r["side"]) == ("Spread", "Away")][0]
        self.assertEqual(away["status"], "QUALIFIED_NOT_WAGER_AUTHORIZED")  # quote 13:00 is after the change
        hist[1]["effective_from_utc"] = "2026-11-16"
        hist[0]["effective_until_utc"] = "2026-11-16"
        away = [r for r in self.rows(Authority(hist)) if (r["market"], r["side"]) == ("Spread", "Away")][0]
        self.assertEqual((away["status"], away["original_tier"]), ("PRODUCTION_QUALIFIED", "B+"))

    def test_not_offered_side_is_explicit(self):
        q = [x for x in self.q if not (x.market == "Total" and x.side == "Under")]
        rows = assemble(complete_board(q), self.scores, releases=[R])
        under = [r for r in rows if r["side"] == "Under"][0]
        self.assertEqual((under["quote_status"], under["status"]), ("NOT_OFFERED", "QUOTE_NOT_OFFERED"))

    def test_chronological_order(self):
        early = board("E0", "2026-11-14T01:00:00+00:00")
        rows = assemble(early + self.q, self.scores, releases=[R])
        self.assertEqual([r["event_id"] for r in rows[:6]], ["E0"] * 6)
        self.assertEqual([r["market"] for r in rows[:6]], ["Moneyline"] * 2 + ["Spread"] * 2 + ["Total"] * 2)
        self.assertTrue(rows[0]["start_time_ct"].endswith("CT"))

    def test_new_vs_previous(self):
        rows = self.rows()
        prev = [dict(r) for r in rows]
        prev[0]["american_odds"] = 999
        rows = mark_new_vs_previous(self.rows(), prev[:-1])
        labels = [r["new_vs_previous"] for r in rows]
        self.assertEqual(labels[0], "PRICE_CHANGED")
        self.assertEqual(labels[-1], "NEW")
        self.assertIn("UNCHANGED", labels)


class ExportTests(unittest.TestCase):
    def test_csv_keeps_every_row_and_column(self):
        rows = assemble(board(), [], releases=[R])
        with tempfile.TemporaryDirectory() as d:
            write_csv(rows, Path(d) / "s.csv")
            with open(Path(d) / "s.csv", newline="") as f:
                got = list(csv.DictReader(f))
            self.assertEqual(len(got), 6)
            self.assertEqual(list(got[0]), COLUMNS)

    def test_champion_challenger_view_pairs_releases(self):
        rows = assemble(board(), [], releases=["A", "B"])
        for r in rows:
            r["release_role"] = "CHAMPION" if r["model_release_id"] == "A" else "CHALLENGER"
        header, body = champion_challenger_view(rows)
        self.assertEqual(len(body), 6)
        self.assertIn("challenger1_model_release_id", header)

    @unittest.skipIf(importlib.util.find_spec("openpyxl") is None, "openpyxl not installed")
    def test_excel_workbook_sheets(self):
        from openpyxl import load_workbook
        rows = assemble(board(), [], releases=[R])
        with tempfile.TemporaryDirectory() as d:
            write_excel(rows, Path(d) / "s.xlsx", {"fixture": "unit"})
            wb = load_workbook(Path(d) / "s.xlsx")
            try:
                self.assertEqual(wb.sheetnames, ["All rows", "Champion vs Challenger", "Positive EV view",
                                                 "Provenance & Legend"])
                self.assertEqual(wb["All rows"].max_row, 7)
            finally:
                wb.close()  # Windows cannot delete the temp folder while the workbook is open


if __name__ == "__main__":
    unittest.main()
