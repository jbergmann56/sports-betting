"""Golden replay harness for the five archived sport scorers.

Each fixture runs an UNCHANGED archived scorer (byte-identical to
``legacy_models/`` or to a frozen-archive member) against hashed archived inputs
in a temporary directory and compares its output with the archived output.

Comparison rule (all fixtures): identical row count and column list; numeric
columns equal within ``ATOL`` with identical NaN positions; all other columns
equal as strings. Run-time timestamp columns are excluded per fixture.

Nothing here refits, recalibrates, re-tiers or promotes a model, and nothing
writes to ``legacy_models/``, ``data/`` or the fixture directories.

Usage::

    python -m tests.golden.replay                 # all fixtures
    python -m tests.golden.replay --fixture NFL_20261110_072712CST
    python -m tests.golden.replay --external /path/to/GAMBLING_DAILY_FEATURE_SOURCE_REPRO_20261112

Fixtures whose external inputs or pinned environment are unavailable report
``SKIPPED`` with the reason; they never report ``PASSED`` without running.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FROZEN_ZIP = REPO / "data" / "GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip"
ATOL = 1e-9
EXTERNAL_ENV = "GOLDEN_EXTERNAL_DIR"


class Skip(Exception):
    """Fixture cannot run in this environment; never treated as a pass."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Ctx:
    """Where fixture inputs come from. Defaults are the committed repo fixtures; the model-data
    proof points these at files materialized from the database instead."""
    fixtures_dir: Path = FIXTURES_DIR
    frozen_zip: Path = FROZEN_ZIP


def load_manifest(fixture_id: str, fixtures_dir: Path = FIXTURES_DIR) -> dict:
    return json.loads((fixtures_dir / fixture_id / "MANIFEST.json").read_text(encoding="utf-8"))


def verify_hashes(manifest: dict, external_dir: Path | None, ctx: Ctx = Ctx()) -> list[str]:
    """Return a list of problems; empty list means every pinned file matches."""
    problems: list[str] = []
    fixture = ctx.fixtures_dir / manifest["fixture_id"]
    for group in ("inputs", "expected"):
        for entry in manifest.get(group, []):
            p = fixture / entry["path"]
            if not p.is_file():
                problems.append(f"missing {group} file {entry['path']}")
            elif sha256(p) != entry["sha256"]:
                problems.append(f"sha256 mismatch {group} {entry['path']}")
    for entry in manifest.get("scorer_files", []):
        if entry["location"].startswith("zip:"):
            continue  # verified after extraction
        p = REPO / entry["location"]
        if not p.is_file() or sha256(p) != entry["sha256"]:
            problems.append(f"scorer file changed or missing: {entry['location']}")
    for entry in manifest.get("external_inputs", []):
        if external_dir is None:
            continue
        p = external_dir / entry["package_path"]
        if not p.is_file():
            problems.append(f"external input missing: {entry['package_path']}")
        elif sha256(p) != entry["sha256"]:
            problems.append(f"external sha256 mismatch: {entry['package_path']}")
    return problems


def compare_csv(produced: Path, expected: Path, exclude: tuple[str, ...] = (),
                row_filter: Callable[[dict], bool] | None = None,
                sort_keys: tuple[str, ...] = (), basename_cols: tuple[str, ...] = (),
                produced_columns_only: bool = False) -> dict:
    """Compare two CSVs under the golden rule. Requires pandas (legacy scorers do).

    ``basename_cols``: columns holding absolute run-time file paths; compared by
    file name only (the directory is an environment artefact, not model output).
    ``produced_columns_only``: compare every column the scorer writes; columns
    present only in the expected file (added by a later presentation step) are
    listed in ``not_compared`` instead of failing the shape check.
    """
    import ntpath
    import numpy as np
    import pandas as pd

    a = pd.read_csv(expected, dtype=str, keep_default_na=False)
    b = pd.read_csv(produced, dtype=str, keep_default_na=False)
    not_compared: list[str] = []
    if produced_columns_only:
        missing = [c for c in b.columns if c not in a.columns]
        if missing:
            return {"status": "FAILED", "reason": f"produced columns absent from expected: {missing}",
                    "expected_rows": len(a), "produced_rows": len(b), "differing_columns": missing,
                    "max_abs_numeric_diff": 0.0}
        not_compared = [c for c in a.columns if c not in b.columns]
        a = a[list(b.columns)]
    for col in basename_cols:
        for frame in (a, b):
            if col in frame:
                frame[col] = frame[col].map(lambda v: ntpath.basename(v.replace("\\", "/").rstrip("/")) if "/" in v or "\\" in v else v)
    if row_filter is not None:
        a = a[a.apply(lambda r: row_filter(r.to_dict()), axis=1)]
        b = b[b.apply(lambda r: row_filter(r.to_dict()), axis=1)]
    if sort_keys:
        a = a.sort_values(list(sort_keys), kind="stable")
        b = b.sort_values(list(sort_keys), kind="stable")
    a = a.reset_index(drop=True)
    b = b.reset_index(drop=True)
    result = {"expected_rows": len(a), "produced_rows": len(b),
              "expected_cols": a.shape[1], "produced_cols": b.shape[1],
              "differing_columns": [], "max_abs_numeric_diff": 0.0, "not_compared": not_compared,
              "normalized_path_columns": list(basename_cols)}
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        result["status"] = "FAILED"
        result["reason"] = "shape or column mismatch"
        return result
    max_diff = 0.0
    for col in a.columns:
        if col in exclude:
            continue
        x, y = a[col], b[col]
        xn, yn = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
        numeric = (xn.notna() | (x == "")).all() and (yn.notna() | (y == "")).all() and xn.notna().any()
        if numeric:
            if ((x == "") != (y == "")).any() or (xn.isna() != yn.isna()).any():
                result["differing_columns"].append(col)
                continue
            both = xn.notna() & yn.notna()
            d = float(np.max(np.abs(xn[both].to_numpy(float) - yn[both].to_numpy(float)))) if both.any() else 0.0
            max_diff = max(max_diff, d)
            if d > ATOL:
                result["differing_columns"].append(col)
        elif not x.equals(y):
            result["differing_columns"].append(col)
    result["max_abs_numeric_diff"] = max_diff
    result["status"] = "IDENTICAL" if not result["differing_columns"] else "FAILED"
    return result


def _require(*modules: str) -> None:
    for m in modules:
        if importlib.util.find_spec(m) is None:
            raise Skip(f"python module {m!r} not installed (see requirements-models.txt)")


def _require_sklearn(version: str) -> None:
    _require("sklearn")
    import sklearn
    if sklearn.__version__ != version:
        raise Skip(f"scikit-learn {version} required by the frozen binary; found {sklearn.__version__}")


def _external(manifest: dict, external_dir: Path | None) -> Path:
    if not manifest.get("external_inputs"):
        return Path()
    if external_dir is None:
        raise Skip(f"external inputs required; set {EXTERNAL_ENV} to the extracted "
                   f"{manifest['external_package']['name']} directory")
    return external_dir


def _run(cmd: list[str], cwd: Path) -> None:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"scorer failed ({' '.join(cmd)}): {done.stderr[-2000:]}")


# --------------------------------------------------------------------------- stages


def run_nfl(manifest: dict, work: Path, external_dir: Path | None, ctx: Ctx) -> list[dict]:
    _require("pandas", "numpy", "scipy")
    prefix = manifest["frozen_zip_prefix"]
    if sha256(ctx.frozen_zip) != manifest["frozen_zip"]["sha256"]:
        raise RuntimeError("frozen ZIP sha256 does not match the fixture manifest")
    with zipfile.ZipFile(ctx.frozen_zip) as z:
        for name in z.namelist():
            if name.startswith(prefix):
                z.extract(name, work)
    src = work / prefix / "scoring"
    for entry in manifest["scorer_files"]:
        if entry["location"].startswith("zip:"):
            member = entry["location"].split("!", 1)[1]
            if sha256(work / member) != entry["sha256"]:
                raise RuntimeError(f"frozen ZIP member hash mismatch: {member}")
    expected = work / "expected"
    expected.mkdir()
    for name in ("dual_model_bet_sheet.csv", "both_side_inputs.csv", "team_features.csv"):
        shutil.copy2(src / name, expected / name)  # archived outputs, copied before the run
    _run([sys.executable, "-B", "score.py"], src)
    return [dict(name=n, **compare_csv(src / n, expected / n))
            for n in ("dual_model_bet_sheet.csv", "both_side_inputs.csv", "team_features.csv")]


def run_nhl(manifest: dict, work: Path, external_dir: Path | None, ctx: Ctx) -> list[dict]:
    _require("pandas", "numpy")  # scorer is stdlib-only; the comparison uses pandas
    fx = ctx.fixtures_dir / manifest["fixture_id"]
    pkg = work / "models" / "nhl_day0"
    pkg.mkdir(parents=True)
    (work / "models" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    shutil.copy2(REPO / "legacy_models/nhl_day0/day0_production.py", pkg / "day0_production.py")
    shutil.copy2(fx / "inputs/OBSERVED_PRICE_ALL_CONTROLS.csv", pkg / "OBSERVED_PRICE_ALL_CONTROLS.csv")
    shutil.copy2(fx / "inputs/nhl_score_adapter_ORIGINAL.py", work / "nhl_adapter.py")
    script = (
        "import csv,sys\n"
        "sys.path.insert(0, %r)\n"
        "import nhl_adapter\n"
        "out, incomplete, audits = nhl_adapter.score(%r)\n"
        "w = csv.DictWriter(open('produced.csv','w',newline=''), fieldnames=list(out[0]))\n"
        "w.writeheader(); w.writerows(out)\n"
        "print(len(out), len(incomplete), len(audits))\n"
    ) % (str(work), str(fx / "inputs/20261112_quotes.csv"))
    (work / "run_nhl.py").write_text(script)
    _run([sys.executable, "-B", "run_nhl.py"], work)
    keys = ("event_id", "market", "side", "model_role", "model_version")
    produced = work / "produced.csv"
    return [dict(name="nhl_scores_20261112.csv",
                 **compare_csv(produced, fx / "expected/nhl_scores_20261112.csv", sort_keys=keys,
                             produced_columns_only=True))]


def run_ncaafb(manifest: dict, work: Path, external_dir: Path | None, ctx: Ctx) -> list[dict]:
    _require("pandas", "numpy", "scipy")
    fx = ctx.fixtures_dir / manifest["fixture_id"]
    shutil.copytree(fx / "inputs", work / "inputs")
    (work / "results").mkdir()
    shutil.move(str(work / "inputs/oct27_scoreboard.json"), work / "results/oct27_scoreboard.json")
    for name in ("build_features.py", "score_both.py"):
        shutil.copy2(REPO / "legacy_models/ncaafb" / name, work / name)
    _run([sys.executable, "-B", "build_features.py"], work)
    _run([sys.executable, "-B", "score_both.py"], work)
    return [dict(name=e["path"].split("/", 1)[1],
                 **compare_csv(work / "results" / e["path"].split("/", 1)[1], fx / e["path"],
                             basename_cols=("Source",)))
            for e in manifest["expected"] if e["path"].endswith(".csv")]


def run_nba(manifest: dict, work: Path, external_dir: Path | None, ctx: Ctx) -> list[dict]:
    _require("pandas", "numpy", "scipy")
    fx = ctx.fixtures_dir / manifest["fixture_id"]
    shutil.copytree(REPO / "legacy_models/nba_r4", work / "nba_r4")
    out = work / "out"
    _run([sys.executable, "-B", str(work / "nba_r4/nba.py"), "score",
          "--quotes", str(fx / "inputs/2026-11-12_nba_quotes.json"),
          "--history", str(fx / "inputs/nba_history_through_2026-11-11.csv"),
          "--out", str(out)], work)
    return [dict(name="forecasts.csv",
                 **compare_csv(out / "forecasts.csv", fx / "expected/forecasts.csv", exclude=("Frozen_UTC",)))]


def run_ncaabb(manifest: dict, work: Path, external_dir: Path | None, ctx: Ctx) -> list[dict]:
    _require("pandas", "numpy", "joblib")
    _require_sklearn(manifest["environment"]["scikit-learn"])
    ext = _external(manifest, external_dir)
    fx = ctx.fixtures_dir / manifest["fixture_id"]
    root = work / "nov01_v4_inputs"
    v4 = work / "basketball_audit" / "v4"
    (v4 / "code").mkdir(parents=True)
    (v4 / "models").mkdir()
    shutil.copytree(fx / "inputs", root)
    for name in ("ncaabb_models.py", "ncaabb_matchup.py", "score_ncaabb_v4.py"):
        shutil.copy2(REPO / "legacy_models/ncaabb_v4" / name, v4 / "code" / name)
    shutil.copy2(REPO / "legacy_models/ncaabb_v4/NCAABB_V4_PRODUCTION_CANDIDATE.joblib",
                 v4 / "models/NCAABB_V4_PRODUCTION_CANDIDATE.joblib")
    for entry in manifest["external_inputs"]:
        dest = work / entry["stage_path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ext / entry["package_path"], dest)
    shutil.move(str(root / "rebuild_nov01_offline.py"), work / "rebuild_nov01_offline.py")
    _run([sys.executable, "-B", "rebuild_nov01_offline.py"], work)
    return [dict(name=n, **compare_csv(root / n, fx / "expected" / n))
            for n in ("prior_2026_ratings.csv", "V4_scoring_inputs.csv", "V4_scored_markets.csv")]


RUNNERS: dict[str, Callable[[dict, Path, Path | None, Ctx], list[dict]]] = {
    "NFL_20261110_072712CST": run_nfl,
    "NHL_DAY0_20261112": run_nhl,
    "NCAAFB_20261102": run_ncaafb,
    "NBA_R4_20261112": run_nba,
    "NCAABB_V4_20261101": run_ncaabb,
}


def replay(fixture_id: str, external_dir: Path | None = None, ctx: Ctx = Ctx()) -> dict:
    manifest = load_manifest(fixture_id, ctx.fixtures_dir)
    report = {"fixture_id": fixture_id, "release_ids": manifest["release_ids"]}
    try:
        if manifest.get("external_inputs") and external_dir is None:
            _external(manifest, external_dir)
        problems = verify_hashes(manifest, external_dir, ctx)
        if problems:
            report.update(status="FAILED", reason="; ".join(problems))
            return report
        with tempfile.TemporaryDirectory(prefix=f"golden_{fixture_id}_") as tmp:
            outputs = RUNNERS[fixture_id](manifest, Path(tmp), external_dir, ctx)
        report["outputs"] = outputs
        report["status"] = "PASSED" if all(o["status"] == "IDENTICAL" for o in outputs) else "FAILED"
    except Skip as why:
        report.update(status="SKIPPED", reason=str(why))
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--fixture", choices=sorted(RUNNERS), action="append")
    ap.add_argument("--external", default=os.environ.get(EXTERNAL_ENV))
    args = ap.parse_args(argv)
    external = Path(args.external) if args.external else None
    reports = [replay(f, external) for f in (args.fixture or list(RUNNERS))]
    print(json.dumps(reports, indent=2))
    return 0 if all(r["status"] in ("PASSED", "SKIPPED") for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
