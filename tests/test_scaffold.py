import importlib
import unittest

from gambling.models import BLOCKED, SCORED, UNSCORED, ScoreRow


class ScaffoldTests(unittest.TestCase):
    def test_new_packages_import(self):
        for name in ("results", "features", "models", "scoring", "accounts", "performance"):
            importlib.import_module(f"gambling.{name}")

    def test_scored_row_must_be_coherent(self):
        ScoreRow("R", "q1", SCORED, 0.5, 0.45, 0.05)
        with self.assertRaises(ValueError):
            ScoreRow("R", "q1", SCORED, 0.6, 0.6, 0.0)
        with self.assertRaises(ValueError):
            ScoreRow("R", "q1", SCORED, 0.5, None, 0.5)

    def test_unscored_rows_need_reason_and_no_probability(self):
        ScoreRow("R", "q1", UNSCORED, reason="NO_FEATURES")
        ScoreRow("R", "q1", BLOCKED, reason="QUOTE_AFTER_START")
        with self.assertRaises(ValueError):
            ScoreRow("R", "q1", UNSCORED)
        with self.assertRaises(ValueError):
            ScoreRow("R", "q1", BLOCKED, 0.5, 0.5, 0.0, reason="x")


if __name__ == "__main__":
    unittest.main()
