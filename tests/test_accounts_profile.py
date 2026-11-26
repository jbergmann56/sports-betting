"""Pre-import profile of Bovada account exports.

All export files here are SYNTHETIC (fictitious ids and amounts) in the exporter's file layout;
no real account data is used or committed.
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gambling.accounts import exports

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def ms(dt):
    return int(dt.timestamp() * 1000)


def item(i, at, delta, balance, cat="SPORTSBOOK", **extra):
    return {"id": str(i), "timestamp": ms(at), "productGroupId": f"g{i}",
            "aggregate": {"wallet": {"category": cat, "currency": "USD", "delta": {"total": str(delta)},
                                     "balance": {"total": str(balance)}}}, **extra}


def write_run(folder, start, end, pages, stopped="reached the last page", derived=True):
    stem = f"bovada_transactions_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}"
    with open(folder / f"{stem}_pages.jsonl", "w", encoding="utf-8") as f:
        for n, items in enumerate(pages, 1):
            f.write(json.dumps({"page": n, "data": {"items": items, "summary": {}}}) + "\n")
    log = {"started_at_utc": end.isoformat(), "created_at_from": start.isoformat().replace("+00:00", "Z"),
           "finished_at_utc": (end + timedelta(minutes=2)).isoformat(), "stopped_because": stopped,
           "pages": [{"page": n, "items": len(p), "has_next": n < len(pages)} for n, p in enumerate(pages, 1)]}
    (folder / f"{stem}_run.json").write_text(json.dumps(log))
    if derived:
        first = {}
        for p in pages:
            for it in p:
                first.setdefault(it["id"], it)
        (folder / f"{stem}.json").write_text(json.dumps({"transaction_count": len(first),
                                                         "transactions": list(first.values())}))
        with open(folder / f"{stem}.csv", "w", encoding="utf-8-sig") as f:
            f.write("id\n" + "".join(f"{i}\n" for i in first))
    return stem


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_complete_contiguous_runs(self):
        a = [item(1, T0 + timedelta(days=1), "-10", "90"), item(2, T0 + timedelta(days=2), "25", "115")]
        b = [item(2, T0 + timedelta(days=2), "25", "115"), item(3, T0 + timedelta(days=20), "-15", "100")]
        write_run(self.dir, T0, T0 + timedelta(days=15), [a])
        write_run(self.dir, T0 + timedelta(days=10), T0 + timedelta(days=30), [b])
        r = exports.profile_exports(self.dir)
        self.assertEqual(len(r["coverage"]["covered_utc"]), 1)  # overlapping windows merge
        self.assertEqual(r["coverage"]["not_covered_utc"], [])
        self.assertEqual(r["counts"]["unique_transactions"], 3)
        self.assertEqual(r["counts"]["ids_in_several_runs"], 1)
        self.assertEqual(r["counts"]["ids_with_differing_versions_across_runs"], 0)
        self.assertEqual(r["balance_chain"]["grouping_that_holds"], ["per_currency", "per_category_and_currency"])
        self.assertTrue(r["import_ready"])

    def test_gap_between_windows_is_not_covered_not_zero(self):
        write_run(self.dir, T0, T0 + timedelta(days=5), [[item(1, T0 + timedelta(days=1), "-10", "90")]])
        write_run(self.dir, T0 + timedelta(days=40), T0 + timedelta(days=60),
                  [[item(9, T0 + timedelta(days=41), "-5", "60")]])
        r = exports.profile_exports(self.dir, since="2026-09-02")
        gaps = r["coverage"]["not_covered_utc"]
        self.assertEqual(len(gaps), 2)  # before the first window (since Sep 2) and between windows
        self.assertTrue(gaps[0][0].startswith("2026-09-02"))
        self.assertIn("not zero", r["coverage"]["rule"])
        # 90 -> 60 with only a -5 delta: the chain breaks across the gap
        self.assertEqual(r["balance_chain"]["per_currency"]["ALL|USD"]["breaks_not_same_timestamp"], 1)
        self.assertFalse(r["import_ready"])

    def test_partial_run_is_not_coverage(self):
        write_run(self.dir, T0, T0 + timedelta(days=5), [[item(1, T0 + timedelta(days=1), "-10", "90")]],
                  stopped="browser error: closed")
        r = exports.profile_exports(self.dir)
        self.assertEqual(r["coverage"]["covered_utc"], [])
        self.assertEqual(r["runs"][0]["status"], "PARTIAL")
        self.assertIn("INCOMPLETE_RUN", r["runs"][0]["issues"][0])
        self.assertFalse(r["import_ready"])

    def test_duplicates_and_changed_versions(self):
        pending = item(5, T0 + timedelta(days=1), "-20", "80", status="PENDING")
        settled = item(5, T0 + timedelta(days=1), "-20", "80", status="SETTLED")
        write_run(self.dir, T0, T0 + timedelta(days=3), [[pending], [pending]])  # same id on two pages
        write_run(self.dir, T0, T0 + timedelta(days=9), [[settled]])
        r = exports.profile_exports(self.dir)
        self.assertEqual(r["runs"][0]["duplicate_ids_within_run"], 1)
        self.assertEqual(r["runs"][0]["duplicate_id_conflicts_within_run"], 0)
        self.assertEqual(r["counts"]["ids_with_differing_versions_across_runs"], 1)
        self.assertEqual(r["counts"]["differing_fields"], {"status": 1})

    def test_derived_files_must_match_pages_and_pages_are_required(self):
        stem = write_run(self.dir, T0, T0 + timedelta(days=3), [[item(1, T0 + timedelta(days=1), "-1", "9")]])
        (self.dir / f"{stem}.json").write_text(json.dumps({"transaction_count": 0, "transactions": []}))
        r = exports.profile_exports(self.dir)
        self.assertIn("DERIVED_JSON_DIFFERS_FROM_PAGES", r["runs"][0]["issues"])
        (self.dir / f"{stem}_pages.jsonl").unlink()
        r = exports.profile_exports(self.dir)
        self.assertEqual(r["runs"][0]["status"], "NOT_USABLE")

    def test_category_specific_balances_detected(self):
        write_run(self.dir, T0, T0 + timedelta(days=5), [[
            item(1, T0 + timedelta(hours=1), "-10", "90", "SPORTSBOOK"),
            item(2, T0 + timedelta(hours=2), "5", "55", "CASINO"),
            item(3, T0 + timedelta(hours=3), "-10", "80", "SPORTSBOOK")]])
        r = exports.profile_exports(self.dir)
        self.assertEqual(r["balance_chain"]["grouping_that_holds"], ["per_category_and_currency"])

    def test_baseline_reconciliation(self):
        write_run(self.dir, T0, T0 + timedelta(days=5), [[item(1, T0 + timedelta(days=1), "-10", "90",
                                                               reference="REF-111")]])
        base = self.dir / "baseline.sqlite"
        con = sqlite3.connect(base)
        con.execute("CREATE TABLE sportsbook_wagers (wager_id, bovada_reference, source_transaction_id, "
                    "placed_at_utc, settled_at_utc, net_pnl_cents)")
        con.executemany("INSERT INTO sportsbook_wagers VALUES (?,?,?,?,?,?)", [
            ("w1", "REF-111", None, "2026-10-02T00:00:00Z", "2026-10-02T03:00:00Z", -1000),
            ("w2", "REF-222", None, "2026-10-03T00:00:00Z", "2026-10-03T03:00:00Z", 900),
            ("w3", "REF-333", None, "2026-09-03T00:00:00Z", "2026-09-03T03:00:00Z", 500)])
        con.commit()
        con.close()
        rec = exports.profile_exports(self.dir, baseline=base)["baseline_reconciliation"]
        self.assertEqual((rec["matched_in_covered_time"], rec["unmatched_in_covered_time"],
                          rec["unmatched_outside_covered_time"]), (1, 1, 1))
        self.assertEqual(rec["unmatched_in_covered_time_examples"][0]["wager_id"], "w2")

    def test_markdown_and_cli_write_reports_outside_git(self):
        from gambling.cli import main
        from gambling.config import Paths
        write_run(self.dir, T0, T0 + timedelta(days=3), [[item(1, T0 + timedelta(days=1), "-1", "9")]])
        data = Path(self.tmp.name) / "data"
        self.assertEqual(main(["accounts", "profile", "--export-dir", str(self.dir)], Paths(data)), 0)
        reports = list((data / "accounts" / "reports").glob("export_profile_*.md"))
        self.assertEqual(len(reports), 1)
        self.assertIn("Import ready:** True", reports[0].read_text())


if __name__ == "__main__":
    unittest.main()
