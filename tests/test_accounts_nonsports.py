"""DQ-14 raw non-sports ledger (SYNTHETIC data only)."""
import unittest
from datetime import datetime, timedelta, timezone

from gambling.accounts.cleanse import Issues
from gambling.accounts.nonsports import build_non_sports

T = datetime(2026, 10, 2, tzinfo=timezone.utc)


def it(i, hours, cat, delta, refs=None):
    return {"__id": i, "timestamp": (T + timedelta(hours=hours)).isoformat(),
            "aggregate": {"wallet": {"category": cat, "delta": {"total": delta, "byType": {}},
                                     "references": refs or []}}}


def brow(i, cat, rec):
    return {"transaction_row_id": f"B-{i}", "bovada_transaction_id": i, "category": cat, "recognized_pnl_cents": rec,
            "timestamp_utc": "ignored"}


RAW = [
    # baseline evidence
    it("c1", 1, "CA-PL", -5.0), it("d1", 2, "FN-DP-ETH", 100.0), it("p1", 3, "PK-PC-MTT", -11.0, ["T1"]),
    it("p2", 4, "PK-CC-MTT", 20.0, ["T1"]), it("z1", 5, "PT-BN", 0), it("b1", 6, "BN-BG", 7.5),
    # after the baseline
    it("c2", 10, "CA-PL", -3.0), it("d2", 11, "FN-DP-BTC", 50.0), it("p3", 12, "PK-PC-MTT", -5.5, ["T2"]),
    it("p4", 13, "PK-PC-MTT", -2.0, ["T3"]), it("p5", 14, "PK-CC-MTT", 0, ["T3"]), it("f1", 15, "BN-FT", -1.25),
    it("s1", 16, "BGS-SB-PL", -1.0),
]
BASE = [brow("c1", "Casino", -500), brow("d1", "Deposits and withdrawals", 0), brow("p1", "Poker", -1100),
        brow("p2", "Poker", 2000), brow("z1", "Internal transfer / zero-P&L", 0), brow("b1", "Bonuses and rewards", 750)]


class NonSportsTests(unittest.TestCase):
    def run_it(self, base=BASE):
        iss = Issues()
        rows, gates, summary = build_non_sports(RAW, base, iss)
        return rows, gates, summary, iss

    def test_rules_learned_and_baseline_reproduced(self):
        rows, gates, _, _ = self.run_it()
        self.assertEqual(gates, {"non_sports_rule_conflicts": (0, 0), "non_sports_baseline_rows_not_reproduced": (0, 0)})
        self.assertNotIn("s1", rows)                      # sportsbook stays in the ticket ledger
        self.assertEqual({k: rows[k]["period"] for k in ("c1", "c2")}, {"c1": "BASELINE_MATCHED", "c2": "AFTER_BASELINE"})
        self.assertEqual((rows["c2"]["treatment"], rows["c2"]["recognized_pnl_cents"], rows["c2"]["rule_provenance"]),
                         ("RECOGNIZED", -300, "BASELINE_RULE"))

    def test_analogy_open_poker_and_unclassified(self):
        rows, _, summary, iss = self.run_it()
        self.assertEqual((rows["d2"]["treatment"], rows["d2"]["recognized_pnl_cents"], rows["d2"]["rule_provenance"]),
                         ("NON_PNL", 0, "ANALOGY"))
        self.assertEqual((rows["p3"]["treatment"], rows["p3"]["recognized_pnl_cents"]), ("OPEN_POKER_STAKE", 0))
        self.assertEqual((rows["p4"]["treatment"], rows["p4"]["recognized_pnl_cents"]), ("RECOGNIZED", -200))
        self.assertEqual((rows["f1"]["treatment"], rows["f1"]["recognized_pnl_cents"]), ("UNCLASSIFIED", None))
        a = summary["after_baseline"]
        self.assertEqual(a["Poker (open buy-ins)"]["delta_cents"], -550)
        self.assertIsNone(a["UNCLASSIFIED"]["recognized_pnl_cents"])
        self.assertEqual(a["Casino"]["recognized_pnl_cents"], -300)
        self.assertIn("UNCLASSIFIED_NO_BASELINE_EVIDENCE", [i["action"] for i in iss.rows])

    def test_conflicting_baseline_treatment_fails_gate(self):
        _, gates, _, _ = self.run_it(BASE + [brow("c2", "Casino", 0)])   # CA-PL both recognized and not
        self.assertEqual(gates["non_sports_rule_conflicts"], (1, 0))
        self.assertEqual(gates["non_sports_baseline_rows_not_reproduced"][0] > 0, True)


    def test_zero_pnl_label_disagreement_is_not_a_conflict(self):
        raw = RAW + [it("z2", 5.5, "PT-BN", 0), it("z3", 5.6, "PT-BN", 0)]
        base = BASE + [brow("z2", "Bonuses and rewards", 0), brow("z3", "Bonuses and rewards", 0)]
        iss = Issues()
        rows, gates, _ = build_non_sports(raw, base, iss)
        self.assertEqual(gates, {"non_sports_rule_conflicts": (0, 0), "non_sports_baseline_rows_not_reproduced": (0, 0)})
        self.assertEqual(rows["z1"]["ledger_category"], "Internal transfer / zero-P&L")   # baseline label kept per row
        self.assertIn("BASELINE_LABELS_DIFFER_ZERO_PNL", [i["action"] for i in iss.rows])

    def test_money_disagreement_with_zero_delta_still_fails(self):
        raw = RAW + [it("z2", 5.5, "PT-BN", 0)]
        base = BASE + [brow("z2", "Bonuses and rewards", 100)]   # recognized P&L on a zero-delta row
        _, gates, _ = build_non_sports(raw, base, Issues())
        self.assertEqual(gates["non_sports_rule_conflicts"], (1, 0))


if __name__ == "__main__":
    unittest.main()
