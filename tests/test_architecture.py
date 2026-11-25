"""Smoke-test modular scaffolding and documentation contract.

This does not validate historical score parity or certify live models.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import unittest

from scripts.check_documentation import check

ROOT = Path(__file__).resolve().parents[1]
SPORTS = ("nfl", "ncaafb", "nba", "nhl", "ncaabb")


class ModularStructureTests(unittest.TestCase):
    def test_sport_scaffolds_import_without_promoting_live_scorers(self):
        for sport in SPORTS:
            for base in ("gambling.models", "gambling.betsheets"):
                with self.subTest(base=base, sport=sport):
                    module = importlib.import_module(f"{base}.{sport}")
                    self.assertTrue(module.__doc__)

    def test_shared_and_ui_scaffolds(self):
        for name in ("gambling.core", "gambling.parlays", "gambling.bonuses"):
            importlib.import_module(name)
        self.assertTrue((ROOT / "apps/streamlit/README.md").exists())

    def test_documentation_contract_present(self):
        required = (
            "CLAUDE.md", "AGENTS.md", "ROADMAP.md",
            "docs/engineering-policy.md", "docs/architecture.md",
            "docs/model-authority.md", "docs/betsheets/shared-contract.md",
            "docs/branch-strategy.md", "docs/streamlit.md",
            "docs/history/migration-roadmap-2026-11.md",
        )
        for file in required:
            with self.subTest(file=file):
                self.assertTrue((ROOT / file).is_file())
        for sport in SPORTS:
            self.assertTrue((ROOT / f"docs/sports/{sport}.md").is_file())

    def test_gate_requires_documentation(self):
        self.assertTrue(check({"gambling/models/nba/model.py", "tests/test_nba.py"}))
        self.assertEqual(check({
            "gambling/models/nba/model.py", "tests/test_nba.py", "ROADMAP.md",
            "docs/sports/nba.md", "docs/model-authority.md",
        }), [])

    def test_gate_requires_sheet_contract_and_streamlit(self):
        self.assertTrue(check({"gambling/betsheets/nhl/export.py", "tests/test_nhl.py", "ROADMAP.md"}))
        self.assertTrue(check({"apps/streamlit/app.py", "tests/test_ui.py", "ROADMAP.md"}))


if __name__ == "__main__":
    unittest.main()
