"""DQ-13 raw ticket ledger and DQ-05 settlement-time check.

SYNTHETIC data only: exporter-format sportsbook transactions (BGS-SB-PL/ST/US/VD with bet references) and
a miniature P&L baseline. No real account data is used or committed.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from gambling.accounts.cleanse import run_cleanse
from gambling.accounts.importer import import_exports
from tests import test_accounts_cleanse as base
from tests.test_accounts_profile import T0, write_run

D = T0 + timedelta(days=1)          # baseline period (2026-10-02)
AFTER = T0 + timedelta(days=5)      # after the baseline cut-off (2026-10-06)


def sb(i, at, cat, ref, delta, risk, win, sel="Home Team", market="Head To Head", price="-110", bet="Single",
       period="Game", path="Hockey - NHL/*BR:TNMNT:142*/", txid=None, legs=None):
    selections = legs or [{"description": sel + "/*LS:OPP:1*/", "price": price, "period": period,
                           "market": {"description": market},
                           "event": {"id": 7, "description": " (1) Away Team/*X*/ @ (2) Home Team/*Y*/",
                                     "path": path, "date": "2026-10-03T00:00:00Z"}}]
    return {"id": str(i), "timestamp": at.isoformat().replace("+00:00", "Z"), "productGroupId": f"g{i}",
            "aggregate": {"wallet": {"category": cat, "currency": "USD", "delta": {"total": delta,
                                                                                 "byType": {"BonusFunds": {"total": delta}}},
                                     "balance": {"total": 0}, "references": [ref],
                                     "transactions": [txid or f"BGSS_{ref}_{cat[-2:]}"]},
                          "sports": {"txType": "x", "betDescription": bet, "risk": risk, "win": win,
                                     "selections": selections, "price": price}}}


def items():
    ev = [
        # in the baseline as R1: win 11 -> +10 (placed + settled inside the baseline period)
        sb(1, D + timedelta(hours=1, seconds=5), "BGS-SB-PL", "R1", -11.0, 11.0, 10.0),
        sb(2, D + timedelta(hours=4), "BGS-SB-ST", "R1", 21.0, 11.0, 10.0),
        # baseline-open R9 (risk 2) now settled: loss
        sb(3, D + timedelta(hours=8), "BGS-SB-PL", "R9", -2.0, 2.0, 1.8),
        sb(4, AFTER + timedelta(hours=1), "BGS-SB-ST", "R9", 0, 2.0, 1.8),
        # new ticket N1: settled, unsettled, resettled as a win of +9.09 on 10
        sb(5, AFTER + timedelta(hours=2), "BGS-SB-PL", "N1", -10.0, 10.0, 9.09, sel="Over 5.5",
           market="Main Dynamic Over/Under"),
        sb(6, AFTER + timedelta(hours=5), "BGS-SB-ST", "N1", 0, 10.0, 9.09, sel="Over 5.5", market="Main Dynamic Over/Under"),
        sb(7, AFTER + timedelta(hours=5, minutes=1), "BGS-SB-US", "N1", 0, 10.0, 9.09, sel="Over 5.5",
           market="Main Dynamic Over/Under"),
        sb(8, AFTER + timedelta(hours=5, minutes=2), "BGS-SB-ST", "N1", 19.09, 10.0, 9.09, sel="Over 5.5",
           market="Main Dynamic Over/Under"),
        # new ticket N2: void
        sb(9, AFTER + timedelta(hours=3), "BGS-SB-PL", "N2", -4.0, 4.0, 3.6),
        sb(10, AFTER + timedelta(hours=6), "BGS-SB-VD", "N2", 4.0, 4.0, 3.6),
        # new live ticket N3, still open
        sb(11, AFTER + timedelta(hours=7), "BGS-SB-PL", "N3", -5.0, 5.0, 4.5, period="Live Game"),
        # new parlay N4 (two legs), lost
        sb(12, AFTER + timedelta(hours=8), "BGS-SB-PL", "N4", -1.0, 1.0, 2.65, bet="Double", price="+265",
           legs=[{"description": "Away Team +5", "price": "-105", "period": "Game",
                  "market": {"description": "Main Dynamic Asian Handicap"},
                  "event": {"id": 8, "description": "A @ B", "path": "Basketball - NCAA Men/*T*/ - ", "date": "x"}},
                 {"description": "Home Team -1.5", "price": "-115", "period": "Game",
                  "market": {"description": "Main Dynamic Asian Puck Line"},
                  "event": {"id": 9, "description": "C @ D", "path": "Hockey - NHL", "date": "x"}}]),
        sb(13, AFTER + timedelta(hours=11), "BGS-SB-ST", "N4", 0, 1.0, 2.65, bet="Double", price="+265"),
        # placement before the covered raw time; only the settlement is in the exports
        sb(14, AFTER + timedelta(hours=12), "BGS-SB-ST", "N5", 7.0, 5.0, 2.0),
    ]
    bal = 100.0
    for it in sorted(ev, key=lambda x: x["timestamp"]):
        bal = round(bal + it["aggregate"]["wallet"]["delta"]["total"], 2)
        it["aggregate"]["wallet"]["balance"]["total"] = bal
    return ev


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        ex = d / "exports"
        ex.mkdir()
        write_run(ex, T0, T0 + timedelta(days=10), [items()])
        self.baseline = d / "baseline.sqlite"
        self.make_baseline()
        self.db = d / "accounts.sqlite"
        import_exports(self.db, ex, baseline=self.baseline)

    def make_baseline(self, r1_pnl=1000):
        w = [base.wager("W1", "R1", "Win", 1100, r1_pnl, base.z(D + timedelta(hours=1, seconds=5) - timedelta(hours=5)),
                        odds=-110, settled=base.z(D + timedelta(hours=4) - timedelta(hours=5)))]
        meta = dict(sportsbook_stakes_cents=1100, sportsbook_itemized_pnl_cents=r1_pnl,
                    sportsbook_prior_adjustment_cents=0, sportsbook_account_pnl_cents=r1_pnl, casino_pnl_cents=0,
                    poker_pnl_cents=0, bonuses_rewards_cents=0, all_gambling_net_pnl_cents=r1_pnl,
                    data_through_date="2026-10-02")
        con = sqlite3.connect(self.baseline)
        for name, cols, rows in (
                ("sportsbook_wagers", base.W_COLS, w),
                ("sportsbook_open_wagers", base.O_COLS, [dict(wager_id="O1", bovada_reference="R9", sport="NHL",
                                                              risk_cents=200,
                                                              placed_timestamp_source=base.z(D + timedelta(hours=3)))]),
                ("accounting_adjustments", base.A_COLS, []), ("non_sports_transactions", base.N_COLS, []),
                ("score_to_wager_evidence_matches", base.M_COLS, []), ("model_scoring_history", base.S_COLS, [])):
            con.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
            con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(cols))})",
                            [[r.get(c) for c in cols] for r in rows])
        con.execute("CREATE TABLE export_metadata (key, json_value)")
        con.executemany("INSERT INTO export_metadata VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
        con.commit()
        con.close()

    def tickets(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            return {r["bovada_reference"]: dict(r) for r in con.execute("SELECT * FROM raw_tickets")}
        finally:
            con.close()

    def test_lifecycles(self):
        r = run_cleanse(self.db)
        self.assertEqual(r["status"], "PASSED", r["gates"])
        t = self.tickets()
        self.assertEqual((t["R1"]["result"], t["R1"]["net_pnl_cents"], t["R1"]["baseline_status"]),
                         ("WIN", 1000, "BASELINE_SETTLED"))
        self.assertEqual((t["R9"]["result"], t["R9"]["net_pnl_cents"], t["R9"]["baseline_status"]),
                         ("LOSS", -200, "BASELINE_OPEN"))
        self.assertEqual((t["N1"]["result"], t["N1"]["net_pnl_cents"], json.loads(t["N1"]["lifecycle"])),
                         ("WIN", 909, ["PL", "ST", "US", "ST"]))
        self.assertEqual((t["N1"]["market"], t["N1"]["direction"]), ("Total", "Over"))
        self.assertEqual((t["N2"]["ticket_status"], t["N2"]["result"], t["N2"]["net_pnl_cents"]), ("VOID", "VOID", 0))
        self.assertEqual((t["N3"]["ticket_status"], t["N3"]["net_pnl_cents"], t["N3"]["market_scope"]),
                         ("OPEN", None, "OUT_OF_MODEL_SCOPE"))
        self.assertEqual((t["N4"]["sport"], t["N4"]["legs"], t["N4"]["market_scope"]), ("MULTI", 2, "OUT_OF_MODEL_SCOPE"))
        self.assertEqual(json.loads(t["N4"]["legs_json"])[0]["sport"], "NCAABB")
        self.assertEqual((t["N5"]["ticket_status"], t["N5"]["net_pnl_basis"], t["N5"]["net_pnl_cents"]),
                         ("PLACEMENT_NOT_COVERED", "SETTLEMENT_MINUS_RISK", 200))
        self.assertEqual((t["R1"]["sport"], t["R1"]["matchup"], t["R1"]["direction"]),
                         ("NHL", "Away Team @ Home Team", "Home"))

    def test_after_baseline_summary_never_double_counts(self):
        r = run_cleanse(self.db)
        self.assertEqual(r["after_baseline"], {
            "BASELINE_OPEN": {"tickets": 1, "stake_cents": 200, "net_pnl_cents": -200},
            "NOT_IN_BASELINE": {"tickets": 4, "stake_cents": 2000, "net_pnl_cents": 909 + 0 - 100 + 200}})
        con = sqlite3.connect(self.db)
        refs = sorted(x[0] for x in con.execute("SELECT bovada_reference FROM tickets_after_baseline"))
        con.close()
        self.assertEqual(refs, ["N1", "N2", "N3", "N4", "N5", "R9"])  # N3 is open: listed, no P&L

    def test_baseline_times_corrected_from_raw(self):
        run_cleanse(self.db)
        con = sqlite3.connect(self.db)
        row = con.execute("SELECT placed_utc, placed_time_basis, settled_utc, settled_time_basis FROM wagers").fetchone()
        con.close()
        self.assertEqual(row, ("2026-10-02T01:00:05+00:00", "RAW_API_CORRECTED",
                               "2026-10-02T04:00:00+00:00", "RAW_API_CORRECTED"))

    def test_raw_baseline_disagreement_fails_the_gate(self):
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)
        self.baseline = Path(self.tmp2.name) / "b.sqlite"
        self.make_baseline(r1_pnl=999)
        db = Path(self.tmp2.name) / "a.sqlite"
        ex = Path(self.tmp2.name) / "ex"
        ex.mkdir()
        write_run(ex, T0, T0 + timedelta(days=10), [items()])
        import_exports(db, ex, baseline=self.baseline)
        r = run_cleanse(db)
        self.assertEqual(r["status"], "FAILED")
        self.assertEqual(r["gates"]["raw_vs_baseline_pnl_mismatches"]["actual"], 1)
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM c_raw_tickets").fetchone(), (0,))
        con.close()


if __name__ == "__main__":
    unittest.main()
