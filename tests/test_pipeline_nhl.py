"""NHL daily pipeline: the Nov 12 capture reproduces the frozen Day-0 regression sheet through the wrapper."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gambling.db.migrate import apply_migrations, connect
from gambling.models.nba.r4_legacy import CAPTURE_20261112
from gambling.pipeline.common import PipelineError
from gambling.pipeline.nhl import run_nhl_daily
from gambling.pipeline.record import record_run
from tests.test_nhl_adapter import assert_same_sheet, registry_authority

GOLDEN = Path(__file__).parent / "fixtures" / "betsheets" / "NHL_DAY0_20261112_betsheet.csv"
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


class NhlPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_reproduces_frozen_sheet_and_records(self):
        m = run_nhl_daily("2026-11-12", CAPTURE_20261112, self.root, None, authority=registry_authority(), now=NOW)
        # identical text on the reference platform; within 1e-9 elsewhere (libm last digits, as in the adapter test)
        assert_same_sheet(self, (Path(m["run_dir"]) / "betsheet.csv").read_bytes(), GOLDEN.read_bytes())
        self.assertNotIn("PRODUCTION_QUALIFIED", m["outputs"]["sheet_status"])
        self.assertEqual(json.loads((Path(m["run_dir"]) / "manifest.json").read_text())["inputs"]
                         ["scorer_quotes_csv"]["rows"], 66)
        con = connect(self.root / "g.sqlite")
        self.addCleanup(con.close)
        apply_migrations(con)
        self.assertEqual(record_run(con, Path(m["run_dir"]))["rows"], 132)

    def test_no_games_on_the_slate(self):
        with self.assertRaisesRegex(PipelineError, "no NHL games starting on 2026-11-13"):
            run_nhl_daily("2026-11-13", CAPTURE_20261112, self.root, None, authority=registry_authority(), now=NOW)


if __name__ == "__main__":
    unittest.main()
