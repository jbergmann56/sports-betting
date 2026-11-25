"""PR documentation policy checker; stdlib only.

Usage: python scripts/check_documentation.py <base-sha> <head-sha>
Checks that code changes are accompanied by affected docs, tests and roadmap.
It is not a substitute for running model parity tests.
"""
from __future__ import annotations

import subprocess
import sys


def changed_paths(base: str, head: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check(paths: set[str]) -> list[str]:
    errors: list[str] = []
    code = {p for p in paths if p.startswith(("gambling/", "apps/")) and p.endswith(".py")}
    changed_tests = {p for p in paths if p.startswith("tests/")}
    documented = lambda p: p in paths

    if code and not documented("ROADMAP.md"):
        errors.append("Code changes require ROADMAP.md update")
    if code and not changed_tests:
        errors.append("Code changes require tests/ changes (fixture or regression test)")

    for sport in ("nfl", "ncaafb", "nba", "nhl", "ncaabb"):
        model = any(p.startswith(f"gambling/models/{sport}/") for p in code)
        sheet = any(p.startswith(f"gambling/betsheets/{sport}/") for p in code)
        if model or sheet:
            if not documented(f"docs/sports/{sport}.md"):
                errors.append(f"{sport}: model/bet-sheet changes require docs/sports/{sport}.md")
        if model and not documented("docs/model-authority.md"):
            errors.append(f"{sport}: model changes require docs/model-authority.md")
        if sheet and not documented("docs/betsheets/shared-contract.md"):
            errors.append(f"{sport}: bet-sheet changes require docs/betsheets/shared-contract.md")

    if any(p.startswith("apps/streamlit/") for p in paths):
        if not documented("docs/streamlit.md"):
            errors.append("Streamlit changes require docs/streamlit.md")
    shared = any(p.startswith(("gambling/core/", "gambling/db/", "gambling/bovada/",
                              "gambling/scoring/", "gambling/accounts/", "gambling/performance/",
                              "gambling/parlays/", "gambling/bonuses/")) for p in code)
    if shared and not documented("docs/architecture.md"):
        errors.append("Shared package changes require docs/architecture.md")

    removed = [p for p in paths if p.startswith(("legacy_models/", "legacy_ops/", "legacy/v1_app/"))]
    if removed and not documented("docs/cleanup-inventory.md"):
        errors.append("Legacy changes require cleanup review in docs/cleanup-inventory.md")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python scripts/check_documentation.py BASE_SHA HEAD_SHA")
        return 2
    try:
        paths = changed_paths(argv[1], argv[2])
    except subprocess.CalledProcessError as exc:
        print(f"Could not compare commits: {exc}")
        return 2
    problems = check(paths)
    for message in problems:
        print(f"ERROR: {message}")
    print(f"Documentation gate: {'FAILED' if problems else 'PASSED'} ({len(paths)} changed paths)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
