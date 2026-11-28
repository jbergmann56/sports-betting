"""Applied migrations are frozen.

0001-0007 are applied to the user's live data/gambling.sqlite (0006/0007 on 2026-11-25 from
commit 227236c). The migrator refuses a database whose recorded hash differs from the file, so
editing any of these files would lock the live database out. Changes go in a NEW migration.
"""
import tempfile
import unittest
from pathlib import Path

from gambling.db.migrate import apply_migrations, connect

# 0008 (espn_retrievals) and 0009 (pipeline_runs) are not applied to the live database yet.
APPLIED_TO_LIVE_DATABASE = {
    1: ("baseline", "76eeb319e910e7061b7ede0923b8a6b58ed691bd9922c5816b7dcd0e290eb239"),
    2: ("rolling_capture", "de99e0a442814bc264971c013a4edace2091ba423ea3310cb8fdbb59503c42d6"),
    3: ("history_views", "6bf696e013d2139c69554949225006e90d9ca93466bed35e62ccd11f03296dda"),
    4: ("model_registry", "85b1cf15bc6c2b1161789841cad9916bab30a32e3b1370ac5b792c6a0b9bb64c"),
    5: ("seed_model_registry", "52fb3fcb247949d2f29a933d30da25b1315db8a5b7063f1c0f2c9bea4464eeb0"),
    6: ("model_data", "1e552dd23f882249ee3f42c0d702aedaaf526170f28ac865999471bf636eff9f"),
    7: ("espn_results", "e17c9f733016182ebf5789ce32d80f56f38c5b772a3b147ffb3905aaa6562ec0"),
}


class MigrationFreezeTests(unittest.TestCase):
    def test_applied_migrations_are_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            con = connect(Path(d) / "x.sqlite")
            apply_migrations(con)
            recorded = {r[0]: (r[1], r[2]) for r in con.execute("SELECT version, name, sha256 FROM schema_migrations")}
            con.close()
        for version, expected in APPLIED_TO_LIVE_DATABASE.items():
            with self.subTest(version=version):
                self.assertEqual(recorded[version], expected,
                                 "applied migration edited: add a new migration instead")


if __name__ == "__main__":
    unittest.main()
