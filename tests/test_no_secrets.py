"""No credential literals in tracked files (Odds API key quarantine, 2026-11-26)."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"""(?i)\b(api_?key|apikey|access_?token|secret|password)\b['"]?\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]""")
TEXT = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".cfg", ".ini", ".txt", ".sh", ".ps1", ".bat"}


class NoSecretsTests(unittest.TestCase):
    def test_no_credential_literals_in_tracked_files(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        hits = []
        for rel in files.splitlines():
            p = ROOT / rel
            if p.suffix.lower() not in TEXT or not p.is_file() or p.stat().st_size > 2_000_000:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if PATTERN.search(line):
                    hits.append(f"{rel}:{n}")
        self.assertEqual(hits, [], "credential literal in tracked files; use an environment variable")

    def test_legacy_odds_api_script_is_quarantined(self):
        src = (ROOT / "legacy/v1_app/odds_api_historical_nfl_events.py").read_text(encoding="utf-8")
        self.assertIn("API_KEY = None", src)
        self.assertIn("_quarantined()", src)


if __name__ == "__main__":
    unittest.main()
