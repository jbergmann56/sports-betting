"""Reconciliation of recorded history against the frozen adapters, on the frozen-baseline database.

Every batch reconciled for the user's database (Nov 6-11) is in the bundled frozen archive, so this
reproduces the reconciliation in CI. NHL is stdlib-only; NBA needs the model environment.
"""
import importlib.util
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gambling.config import Paths, default_paths
from gambling.db import init_database

MODEL_ENV = all(importlib.util.find_spec(m) for m in ("pandas", "numpy", "scipy"))


class ReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        paths = Paths(Path(cls.tmp.name))
        shutil.copy(default_paths().frozen_archive, paths.frozen_archive)
        init_database(paths)
        cls.con = sqlite3.connect(f"file:{paths.database}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def test_nhl_day0_rows_reproduce_exactly(self):
        from gambling.reconcile.nhl import reconcile_all
        reports = {r["batch_id"]: r["outcomes"] for r in reconcile_all(self.con)}
        matched = sum(o.get("MATCH", 0) for o in reports.values())
        self.assertEqual(matched, 552)
        for outcomes in reports.values():
            self.assertFalse({"PROBABILITY_DIFFERS", "EV_DIFFERS", "NOT_REPLAYED", "SIDE_UNRESOLVED"} & set(outcomes))
        self.assertEqual(reports["FIVE_SPORT_20261106_AFTERNOON_V1"], {"NOT_REPLAYABLE_LABEL": 6,
                                                                       "basis:RECORDED_SIDE": 6})
        self.assertEqual(sum(o.get("basis:SIDE_FROM_SELECTION_DISPLAY", 0) for o in reports.values()), 64)

    @unittest.skipUnless(MODEL_ENV, "model environment not installed")
    def test_nba_r4_reproduces_with_documented_history_variants(self):
        from gambling.reconcile.nba import reconcile_all
        got = {(r["batch_id"], r["slate"]): r for r in reconcile_all(self.con)}
        expected_variant = {
            "FIVE_SPORT_20261106_AFTERNOON_V1": "FROZEN",
            "FIVE_SPORT_20261107_LATE_PREVIEW_0600Z": "BEFORE_PREVIOUS_DAY_FINALS",
            "FIVE_SPORT_20261108_0707CST_V1": "FROZEN",
            "FIVE_SPORT_20261109_0848CST_V1": "NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS",
            "FIVE_SPORT_20261110_0726CST_V1": "NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS",
            "FIVE_SPORT_20261111_0039CST_V1": "NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS",
        }
        full = 0
        for (batch, _), r in got.items():
            with self.subTest(batch=batch):
                if batch in expected_variant:
                    self.assertEqual(r["history_variant"], expected_variant[batch])
                    self.assertEqual(set(r["outcomes"]), {"MATCH"})
                    full += r["outcomes"]["MATCH"]
                else:  # afternoon R4_R3 runs: decisions reproduce, intermediates unexplained
                    self.assertEqual(set(r["decisions_only"]["outcomes"]), {"MATCH"})
        self.assertEqual(full, 138)


if __name__ == "__main__":
    unittest.main()
