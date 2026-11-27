"""DQ-01..DQ-12 cleanse of the accounts database.

Everything here is SYNTHETIC: a miniature P&L baseline with the real baseline's table layout and
fictitious exporter-format raw transactions. No real account data is used or committed.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from gambling.accounts.cleanse import build, run_cleanse
from gambling.accounts.importer import import_exports, open_accounts_db
from tests.test_accounts_profile import T0, item, write_run

W_COLS = ["wager_id", "bovada_reference", "source_transaction_id", "status", "source_cohort", "sport", "market",
          "direction", "matchup", "selection", "odds_raw", "odds_american", "stake_usd", "stake_cents", "net_pnl_usd",
          "net_pnl_cents", "result", "placed_timestamp_source", "placed_at_utc", "placed_at_chicago",
          "placed_date_chicago", "settled_timestamp_source", "settled_at_utc", "settled_at_chicago",
          "settled_date_chicago", "original_attribution", "original_frozen_tier", "champion_model_current",
          "champion_tier_current", "secondary_model_current", "secondary_tier_current", "current_tier_evidence",
          "prebet_evidence_category", "independent_validation_status", "champion_match_quality",
          "champion_score_action_at_quote", "champion_production_at_quote", "saved_score_id", "source_authority",
          "accounted_in_pnl", "frozen_model_p", "forecast_expected_pnl_usd", "forecast_model_version"]
O_COLS = ["wager_id", "bovada_reference", "source_transaction_id", "status", "sport", "market", "matchup", "selection",
          "odds_raw", "odds_american", "risk_usd", "risk_cents", "placed_timestamp_source", "placed_at_utc",
          "placed_at_chicago", "placed_date_chicago", "champion_model_current", "champion_tier_current",
          "secondary_model_current", "secondary_tier_current", "recommendation_link", "independent_validation_status",
          "accounted_in_pnl"]
A_COLS = ["adjustment_id", "sport", "category", "description", "recognized_pnl_usd", "recognized_pnl_cents",
          "date_chicago", "source_period", "source_authority", "included_in_ytd_total"]
N_COLS = ["transaction_row_id", "datetime_source_chicago", "date_chicago", "timestamp_utc", "timestamp_chicago",
          "source_period", "category", "activity", "wallet_delta_usd", "wallet_delta_cents", "recognized_pnl_usd",
          "recognized_pnl_cents", "open_poker_stake_usd", "internal_transfer_usd", "accounting_treatment",
          "bovada_transaction_id", "poker_tournament_id"]
M_COLS = ["wager_key", "sport", "market", "matchup", "bet_selection", "placed_chicago", "bet_odds", "score_role",
          "score_id", "match_grade", "scored_selection", "scored_line", "scored_odds", "model_tier", "model_version",
          "score_action", "production_at_quote", "quote_utc", "scored_utc", "scored_seconds_before_bet", "model_ev",
          "full_kelly", "adjusted_kelly", "model_health", "score_source_file"]
S_COLS = ["score_id", "sport", "matchup", "game_start_utc", "quote_utc", "scored_utc", "market", "scored_selection",
          "line", "odds", "model_role", "model_version", "tier", "model_p", "ev", "full_kelly", "adjusted_kelly",
          "production_flag", "bet_sheet_status", "block_reason", "model_health", "quote_cohort", "source_file",
          "selection_source"]

D1 = T0 + timedelta(days=1)  # 2026-10-02 UTC; Chicago is UTC-5 (CDT)


def z(dt, ms="000"):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def wager(wid, ref, result, stake, pnl, placed, odds=None, market="Moneyline", selection="Home Team",
          matchup="Away Team @ Home Team", direction=None, settled=None):
    return dict(wager_id=wid, bovada_reference=ref, sport="NHL", market=market, matchup=matchup, selection=selection,
                direction=direction, odds_raw=None if odds is None else str(odds), odds_american=odds,
                stake_cents=stake, net_pnl_cents=pnl, result=result, placed_timestamp_source=placed,
                settled_timestamp_source=settled, placed_date_chicago="2026-10-02", original_frozen_tier="T1",
                prebet_evidence_category="PREBET", champion_tier_current="T2", champion_model_current="m2",
                source_cohort="New", accounted_in_pnl=1)


WAGERS = [
    # DQ-04 reference match; raw placement confirms the time
    wager("W1", "R1", "Win", 1100, 1000, z(D1 + timedelta(hours=1, seconds=5)), odds=-110,
          settled=z(D1 + timedelta(hours=4, seconds=-1), "999")),
    # DQ-03 loss without odds stays UNRECOVERABLE; DQ-05 Chicago local time labelled as UTC is corrected from raw
    wager("W2", "R2", "Loss", 2000, -2000, z(D1 + timedelta(hours=2, seconds=7) - timedelta(hours=5))),
    # DQ-03 win without odds is back-solved; DQ-04 no reference -> matched by time and risk
    wager("W3", None, "Win", 1000, 1500, z(D1 + timedelta(hours=3, seconds=9))),
    # DQ-02 Push/Void with void text in the matched raw transactions -> VOID
    wager("W4", "R4", "Push/Void", 500, 0, z(D1 + timedelta(hours=5, seconds=1)), odds=120),
    # DQ-01 aggregate-only settlement
    wager("W5", None, "Settled — aggregate only", 700, 0, None, odds=-105, selection="Rolled-up settlement"),
    # DQ-06 Puck line -> Spread; direction from selection vs matchup (rank stripped)
    wager("W6", "R6", "Loss", 300, -300, z(D1 + timedelta(hours=6, seconds=3)), odds=-150, market="Puck line",
          selection="Away Team +1.5 (-150)", matchup="Away Team (#3) @ Home Team"),
    # DQ-06 Over/Under direction; out-of-scope market
    wager("W7", "R7", "Push", 400, 0, None, odds=-110, market="Grand Salami total", selection="Over 30.5"),
    # DQ-12 the surviving copy of the upstream-excluded duplicate
    wager("W8#SOURCE_DUP_2", "RDUP", "Win", 1000, 2000, None, odds=200),
]
STAKE = sum(w["stake_cents"] for w in WAGERS)
ITEMIZED = sum(w["net_pnl_cents"] for w in WAGERS)
PRIOR = -100
NONSPORTS = [
    dict(transaction_row_id="N1", timestamp_utc=z(D1), category="Casino", wallet_delta_cents=-200,
         recognized_pnl_cents=-200, bovada_transaction_id="901", source_period="Exports"),
    dict(transaction_row_id="N2", timestamp_utc=z(D1 + timedelta(hours=1)), category="Bonuses and rewards",
         wallet_delta_cents=300, recognized_pnl_cents=300, bovada_transaction_id=None, source_period="Prior authority"),
    dict(transaction_row_id="N3", timestamp_utc=z(D1 + timedelta(hours=2)), category="Deposits and withdrawals",
         wallet_delta_cents=10000, recognized_pnl_cents=0, bovada_transaction_id="903", source_period="Exports"),
    dict(transaction_row_id="N4", timestamp_utc=z(D1 + timedelta(hours=3)), category="Poker",
         wallet_delta_cents=-50, recognized_pnl_cents=-50, bovada_transaction_id="904", source_period="Exports"),
]
META = dict(sportsbook_stakes_cents=STAKE, sportsbook_itemized_pnl_cents=ITEMIZED,
            sportsbook_prior_adjustment_cents=PRIOR, sportsbook_account_pnl_cents=ITEMIZED + PRIOR,
            casino_pnl_cents=-200, poker_pnl_cents=-50, bonuses_rewards_cents=300,
            all_gambling_net_pnl_cents=ITEMIZED + PRIOR + 50, excluded_duplicate_bovada_reference="RDUP")
LINKS = [  # (wager_key, quote, score_id)
    ("R1", z(D1 + timedelta(minutes=30)), "s1"),          # kept: quote before placement
    ("R2", z(D1 + timedelta(hours=1)), "s2"),             # kept only because W2's time is corrected from raw
    ("R6", z(D1 + timedelta(hours=7)), "s6"),             # dropped: quote after placement
    ("R404", z(D1), "s9"),                                # dropped: unknown wager
    ("R9", z(D1 + timedelta(hours=7)), "s10"),            # open ticket; kept
]


def make_baseline(path, meta=META):
    con = sqlite3.connect(path)
    for name, cols, rows in (
            ("sportsbook_wagers", W_COLS, WAGERS),
            ("sportsbook_open_wagers", O_COLS, [dict(wager_id="O1", bovada_reference="R9", sport="NBA",
                                                     market="Spread", risk_cents=200,
                                                     placed_timestamp_source=z(D1 + timedelta(hours=8)))]),
            ("accounting_adjustments", A_COLS, [dict(adjustment_id="PRIOR-1", sport="NCAAFB", category="Prior",
                                                     description="prior unallocated", recognized_pnl_cents=PRIOR)]),
            ("non_sports_transactions", N_COLS, NONSPORTS),
            ("score_to_wager_evidence_matches", M_COLS,
             [dict(wager_key=k, quote_utc=q, score_id=s, score_role="CHAMPION", match_grade="PREBET_EXACT")
              for k, q, s in LINKS]),
            ("model_scoring_history", S_COLS, [dict(score_id=s) for s in ("s1", "s2", "s6")])):
        con.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
        con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(cols))})",
                        [[r.get(c) for c in cols] for r in rows])
    con.execute("CREATE TABLE export_metadata (key, json_value)")
    con.executemany("INSERT INTO export_metadata VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()


def raw_items():
    """Placement debits (delta = -stake) and settlement credits, with a consistent running balance."""
    events = [  # (id, time, delta dollars, extra)
        (1, D1 + timedelta(hours=1, seconds=5), "-11", {"reference": "R1"}),
        (2, D1 + timedelta(hours=2, seconds=7), "-20", {"reference": "R2"}),
        (3, D1 + timedelta(hours=3, seconds=30), "-10", {}),                   # W3: 21 s after the recorded time
        (4, D1 + timedelta(hours=4), "21", {"reference": "R1"}),
        (5, D1 + timedelta(hours=5, seconds=1), "-5", {"reference": "R4"}),
        (6, D1 + timedelta(hours=5, minutes=30), "5", {"reference": "R4", "description": "Wager voided"}),
        (7, D1 + timedelta(hours=6, seconds=3), "-3", {"reference": "R6"}),
        (8, D1 + timedelta(hours=8), "-2", {"reference": "R9"}),
    ]
    bal, out = 1000, []
    for i, t, d, extra in events:
        bal += float(d)
        out.append(item(i, t, d, f"{bal:g}", **extra))
    return out


class CleanseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.exports = d / "exports"
        self.exports.mkdir()
        write_run(self.exports, T0, T0 + timedelta(days=3), [raw_items()])
        self.baseline = d / "baseline.sqlite"
        make_baseline(self.baseline)
        self.db = d / "accounts.sqlite"
        import_exports(self.db, self.exports, baseline=self.baseline)

    def q(self, sql, *a):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, a).fetchall()
        finally:
            con.close()

    def wagers(self):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            return {r["baseline_wager_id"]: dict(r) for r in con.execute("SELECT * FROM wagers")}
        finally:
            con.close()

    def issues(self, rule, action=None):
        sql = "SELECT row_ref, raw_value, cleansed_value, evidence FROM dq_issues WHERE rule_id = ?"
        return self.q(sql + (" AND action = ?" if action else ""), *([rule, action] if action else [rule]))

    def test_gates_pass_and_totals_reconcile_to_the_cent(self):
        r = run_cleanse(self.db)
        self.assertEqual(r["status"], "PASSED", r["gates"])
        self.assertEqual(r["gates"]["sportsbook_account_pnl"]["actual"], ITEMIZED + PRIOR)
        self.assertEqual(r["gates"]["settled_ticket_rows_conserved"]["actual"], len(WAGERS))
        self.assertEqual(r["wagers"], len(WAGERS) - 1)

    def test_cli_cleanse_runs_without_export_dir(self):
        # `accounts cleanse` has no --export-dir; it must not look up the export folder.
        import io
        from contextlib import redirect_stdout
        from gambling.cli import main
        from gambling.config import Paths
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["accounts", "cleanse", "--db", str(self.db)], Paths(Path(self.tmp.name) / "data"))
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("PASSED", out.getvalue())

    def test_dq01_aggregate_rows_are_adjustments_not_tickets(self):
        run_cleanse(self.db)
        self.assertNotIn("W5", self.wagers())
        self.assertEqual(self.q("SELECT kind, stake_cents, recognized_pnl_cents FROM accounting_adjustments "
                                "ORDER BY kind"), [("AGGREGATE_SETTLEMENT", 700, 0), ("PRIOR_UNALLOCATED", 0, PRIOR)])

    def test_dq02_push_void_uses_raw_evidence(self):
        run_cleanse(self.db)
        w = self.wagers()
        self.assertEqual((w["W4"]["result_raw"], w["W4"]["result"]), ("Push/Void", "VOID"))
        self.assertEqual(w["W7"]["result"], "PUSH")
        self.assertIn("Wager voided", self.issues("DQ-02")[0][3])

    def test_dq03_odds_backsolved_only_for_wins(self):
        run_cleanse(self.db)
        w = self.wagers()
        self.assertEqual((w["W3"]["odds_american"], w["W3"]["odds_status"]), (150.0, "BACKSOLVED"))
        self.assertEqual((w["W2"]["odds_american"], w["W2"]["odds_status"]), (None, "UNRECOVERABLE"))
        self.assertEqual(w["W1"]["odds_status"], "RECORDED")

    def test_dq04_keys_and_match_methods(self):
        run_cleanse(self.db)
        w = self.wagers()
        self.assertEqual((w["W1"]["wager_key"], w["W1"]["id_match_method"]), ("R1", "REFERENCE"))
        self.assertEqual(json.loads(w["W1"]["raw_transaction_ids"]), ["1", "4"])
        self.assertEqual((w["W3"]["wager_key"], w["W3"]["id_match_method"]), ("BTX-3", "TIME_RISK"))
        self.assertEqual(w["W7"]["id_match_method"], "REFERENCE_NOT_IN_RAW")

    def test_dq05_timestamps(self):
        run_cleanse(self.db)
        w = self.wagers()
        self.assertEqual(w["W1"]["settled_utc"], "2026-10-02T04:00:00+00:00")
        self.assertEqual(w["W1"]["settled_precision"], "MINUTE")
        self.assertEqual(w["W1"]["placed_time_basis"], "RAW_API_CONFIRMED")
        self.assertEqual(w["W2"]["placed_utc"], "2026-10-02T02:00:07+00:00")
        self.assertEqual(w["W2"]["placed_time_basis"], "RAW_API_CORRECTED")
        self.assertTrue(w["W2"]["placed_raw"].startswith("2026-10-01T21:00:07"))   # raw kept
        self.assertEqual(len(self.issues("DQ-05", "TIMEZONE_MISLABEL_CORRECTED_FROM_RAW")), 1)
        self.assertEqual(w["W7"]["placed_time_basis"], "NONE")

    def test_dq06_markets_and_directions(self):
        run_cleanse(self.db)
        w = self.wagers()
        self.assertEqual((w["W6"]["market"], w["W6"]["direction"], w["W6"]["away"]), ("Spread", "Away", "Away Team"))
        self.assertEqual((w["W7"]["market_scope"], w["W7"]["direction"]), ("OUT_OF_MODEL_SCOPE", "Over"))
        self.assertEqual(w["W1"]["direction"], "Home")

    def test_dq08_non_sports_keys_and_cash_movements(self):
        run_cleanse(self.db)
        rows = dict(self.q("SELECT key_method, COUNT(*) FROM non_sports_ledger GROUP BY 1"))
        self.assertEqual(rows, {"BOVADA_ID": 3, "COMPOSITE": 1})
        self.assertEqual(self.q("SELECT recognized_pnl_cents FROM non_sports_ledger WHERE category = "
                                "'Deposits and withdrawals'"), [(0,)])

    def test_dq09_links_require_placement_after_quote(self):
        run_cleanse(self.db)
        self.assertEqual(sorted(r[0] for r in self.q("SELECT score_id FROM wager_links")), ["s1", "s10", "s2"])
        self.assertEqual(len(self.issues("DQ-09", "DROPPED_UNRESOLVED_WAGER")), 1)
        self.assertEqual(len(self.issues("DQ-09", "DROPPED_PLACED_BEFORE_QUOTE")), 1)

    def test_dq12_exclusion_and_undated_prior_adjustment(self):
        run_cleanse(self.db)
        self.assertEqual(self.q("SELECT bovada_reference, present_in_baseline FROM accounting_exclusions"),
                         [("RDUP", 0)])
        self.assertIsNone(self.q("SELECT date_chicago FROM accounting_adjustments WHERE kind='PRIOR_UNALLOCATED'")[0][0])

    def test_dq11_retrospective_tier_kept_apart(self):
        run_cleanse(self.db)
        w = self.wagers()["W1"]
        self.assertEqual((w["original_frozen_tier"], w["retrospective_champion_tier"]), ("T1", "T2"))

    def test_failed_gate_publishes_nothing(self):
        con = open_accounts_db(self.db)
        con.execute("DROP TRIGGER IF EXISTS pnl_baseline_export_metadata_no_update")
        con.execute("UPDATE pnl_baseline_export_metadata SET json_value = '1' WHERE key = 'casino_pnl_cents'")
        con.commit()
        con.close()
        r = run_cleanse(self.db)
        self.assertEqual(r["status"], "FAILED")
        self.assertFalse(r["gates"]["casino_pnl_cents"]["pass"])
        self.assertEqual(self.q("SELECT COUNT(*) FROM c_wagers"), [(0,)])
        self.assertEqual(self.q("SELECT COUNT(*) FROM wagers"), [(0,)])
        self.assertGreater(self.q("SELECT COUNT(*) FROM dq_issues")[0][0], 0)

    def test_rerun_is_deterministic_and_append_only(self):
        a, b = run_cleanse(self.db), run_cleanse(self.db)
        self.assertEqual(a["fingerprint"], b["fingerprint"])
        self.assertEqual((a["run_id"], b["run_id"]), (1, 2))
        self.assertEqual(self.q("SELECT COUNT(*) FROM c_wagers"), [(2 * a["wagers"],)])
        self.assertEqual(self.q("SELECT COUNT(DISTINCT run_id) FROM wagers"), [(1,)])
        con = sqlite3.connect(self.db)
        for sql in ("UPDATE c_wagers SET stake_cents = 0", "DELETE FROM dq_issues", "UPDATE dq_runs SET status='FAILED'"):
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute(sql)
        con.close()

    def test_raw_layer_unchanged(self):
        before = self.q("SELECT transaction_id, version_sha256 FROM raw_transactions ORDER BY 1")
        base = self.q("SELECT * FROM pnl_baseline_sportsbook_wagers ORDER BY wager_id")
        run_cleanse(self.db)
        self.assertEqual(before, self.q("SELECT transaction_id, version_sha256 FROM raw_transactions ORDER BY 1"))
        self.assertEqual(base, self.q("SELECT * FROM pnl_baseline_sportsbook_wagers ORDER BY wager_id"))

    def test_dq10_scoring_db_opened_read_only_and_never_the_target(self):
        scores = Path(self.tmp.name) / "gambling.sqlite"
        con = sqlite3.connect(scores)
        con.execute("CREATE TABLE model_scores (score_id TEXT)")
        con.executemany("INSERT INTO model_scores VALUES (?)", [("s1",), ("s99",)])
        con.commit()
        con.close()
        run_cleanse(self.db, scoring_db=scores)
        ev = self.issues("DQ-10")[0][3]
        self.assertIn("export-only 2, database-only 1", ev)
        with self.assertRaises(Exception):
            run_cleanse(scores)

    def test_requires_a_baseline(self):
        empty = Path(self.tmp.name) / "empty.sqlite"
        import_exports(empty, self.exports)
        with self.assertRaisesRegex(RuntimeError, "no P&L baseline"):
            run_cleanse(empty)


if __name__ == "__main__":
    unittest.main()
