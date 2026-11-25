"""Golden replay regression tests for the five archived sport scorers.

Each test runs an unchanged archived scorer against hashed archived inputs and
requires output identical to the archived output (see tests/golden/replay.py).
Fixtures that need the pinned model environment (requirements-models.txt) or the
external reproducibility package (GOLDEN_EXTERNAL_DIR) are SKIPPED with the
reason; a skip is never reported as a pass.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from tests.golden.replay import EXTERNAL_ENV, RUNNERS, load_manifest, replay, verify_hashes

EXTERNAL = Path(os.environ[EXTERNAL_ENV]) if os.environ.get(EXTERNAL_ENV) else None


class GoldenManifestTests(unittest.TestCase):
    """Stdlib-only: pinned fixture evidence and scorer bytes are unchanged."""

    def test_every_fixture_has_a_manifest_and_runner(self):
        fixtures = {p.name for p in (Path(__file__).parent / "golden" / "fixtures").iterdir() if p.is_dir()}
        self.assertEqual(fixtures, set(RUNNERS))

    def test_committed_evidence_hashes_match(self):
        for fixture_id in RUNNERS:
            with self.subTest(fixture=fixture_id):
                self.assertEqual(verify_hashes(load_manifest(fixture_id), None), [])

    def test_manifests_declare_no_model_change(self):
        for fixture_id in RUNNERS:
            m = load_manifest(fixture_id)
            self.assertTrue(m["model_changes"].startswith("NONE"))
            self.assertTrue(m["release_ids"])


class GoldenReplayTests(unittest.TestCase):
    def _check(self, fixture_id):
        report = replay(fixture_id, EXTERNAL)
        if report["status"] == "SKIPPED":
            self.skipTest(report["reason"])
        self.assertEqual(report["status"], "PASSED", report)


for _fixture in RUNNERS:
    setattr(GoldenReplayTests, f"test_replay_{_fixture}",
            lambda self, f=_fixture: self._check(f))


if __name__ == "__main__":
    unittest.main()
