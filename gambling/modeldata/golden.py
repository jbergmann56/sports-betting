"""Import the five golden replay fixtures into the model-data store and prove reproduction.

``import_golden`` preserves every fixture input, expected output, manifest, the frozen
archive ZIP and (when supplied) the NCAABB external inputs as immutable source files;
tabular inputs are also imported as dataset versions with lossless rows. Each fixture
becomes a ``GOLDEN_FIXTURE`` run whose ``run_inputs`` pin exactly which bytes sit at
which path.

``prove_golden`` materializes every run **from the database only** into a fresh
directory and executes the golden replay harness against those files. The scorers are
unchanged; a PASS proves the database returns the exact inputs the original runs used.

    python -m gambling.modeldata.golden --url mysql://... --external /path/to/package
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Optional

from gambling.config import PACKAGE_ROOT
from gambling.modeldata.store import Store, connect, parser_for

FIXTURES = PACKAGE_ROOT / "tests" / "golden" / "fixtures"
FROZEN_ZIP = PACKAGE_ROOT / "data" / "GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip"
ACTOR = "gambling.modeldata.golden"
FLAGGED_EXTERNAL = {"NCAABB/basketball_audit/v4/NCAABB_DB_CLEAN_REBUILT_2021_2025.csv"}
# Model-generated columns whose names resemble staking fields; reviewed 2026-11-25.
REVIEWED_MODEL_FIELDS = {
    "health_stake_multiplier": "NCAABB V4 model output: health-based sizing multiplier (no user stake)",
    "stake_eligible": "NCAABB V4 model output: boolean eligibility for sizing",
    "cash_bet_status": "NCAABB V4 model output: constant 'Simulation / no bet executed'",
}
PUBLIC_MARKET = ("quotes", "bovada", "espn_", "mbb_schedule", "schedule2026", "finals_week", "scoreboard")


def _sensitivity(name: str) -> str:
    low = name.lower()
    return "PUBLIC_MARKET" if any(k in low for k in PUBLIC_MARKET) else "MODEL_INTERNAL"


def _dataset_id(fixture_id: str, rel: str) -> str:
    return f"golden/{fixture_id}/{rel}"


def import_golden(store: Store, external_dir: Optional[Path] = None) -> dict:
    summary = {"fixtures": {}, "sources": 0, "versions": 0}
    zip_sha = store.register_source(FROZEN_ZIP.read_bytes(), FROZEN_ZIP.name, "MODEL_INTERNAL",
                                    f"repo data/{FROZEN_ZIP.name} (frozen Nov 11 evidence archive)", ACTOR)
    for fx in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        manifest_path = fx / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fid = manifest["fixture_id"]
        store.register_run(fid, "GOLDEN_FIXTURE", manifest["release_ids"], manifest["environment"],
                           manifest.get("scorer_files", []), notes=manifest.get("provenance"))
        m_sha = store.register_source(manifest_path.read_bytes(), f"{fid}/MANIFEST.json", "MODEL_INTERNAL",
                                      f"repo tests/golden/fixtures/{fid}/MANIFEST.json", ACTOR)
        store.pin_input(fid, f"fixtures/{fid}/MANIFEST.json", "MANIFEST", m_sha)
        if manifest.get("frozen_zip_prefix") or fid.startswith("NFL"):
            store.pin_input(fid, f"archive/{FROZEN_ZIP.name}", "ARCHIVE", zip_sha)
        count = 0
        for group, role in (("inputs", "INPUT"), ("expected", "EXPECTED_OUTPUT")):
            for entry in manifest.get(group, []):
                rel = entry["path"]
                data = (fx / rel).read_bytes()
                sens = _sensitivity(rel)
                sha = store.register_source(data, f"{fid}/{rel}", sens,
                                            f"repo tests/golden/fixtures/{fid}/{rel}; {manifest.get('provenance', '')}",
                                            ACTOR)
                assert sha == entry["sha256"], f"{fid}/{rel} differs from its manifest hash"
                version_id = None
                parser = parser_for(rel)
                if parser != "blob":
                    store.ensure_dataset(_dataset_id(fid, rel), "replay_input" if role == "INPUT" else "predictions",
                                         manifest.get("sport"), f"{fid} {group} file {rel}")
                    version_id = store.import_version(_dataset_id(fid, rel), sha[:16], sha, parser, ACTOR,
                                                      notes=f"golden fixture {fid}",
                                                      reviewed_columns=REVIEWED_MODEL_FIELDS)
                    store.set_status(version_id, "PUBLISHED", "golden fixture evidence", ACTOR)
                    summary["versions"] += 1
                store.pin_input(fid, f"fixtures/{fid}/{rel}", role, sha, version_id)
                count += 1
        for entry in manifest.get("external_inputs", []):
            if external_dir is None:
                continue
            path = Path(external_dir) / entry["package_path"]
            data = path.read_bytes()
            sens = "CONTAINS_USER_OBSERVATION_FLAGS" if entry["package_path"] in FLAGGED_EXTERNAL \
                else _sensitivity(entry["package_path"])
            sha = store.register_source(data, entry["package_path"], sens,
                                        f"{manifest['external_package']['name']} "
                                        f"(sha256 {manifest['external_package']['sha256']}) :: {entry['package_path']}",
                                        ACTOR)
            if sha != entry["sha256"]:
                raise AssertionError(f"external {entry['package_path']} differs from manifest")
            store.ensure_dataset(_dataset_id(fid, entry["package_path"]), "replay_input", manifest.get("sport"),
                                 f"{fid} external input {entry['package_path']}")
            vid = store.import_version(_dataset_id(fid, entry["package_path"]), sha[:16], sha,
                                       parser_for(entry["package_path"]), ACTOR, notes=entry["reason_not_committed"])
            store.set_status(vid, "PUBLISHED", "golden fixture external evidence", ACTOR)
            store.pin_input(fid, f"external/{entry['package_path']}", "INPUT", sha, vid)
            summary["versions"] += 1
            count += 1
        summary["fixtures"][fid] = count
    summary["sources"] = int(store.fetchone("SELECT COUNT(*) FROM source_files")[0])
    return summary


def prove_golden(store: Store, fixtures: Optional[list[str]] = None) -> list[dict]:
    """Materialize each run from the database only and replay it with the unchanged scorers."""
    sys.path.insert(0, str(PACKAGE_ROOT))
    from tests.golden.replay import Ctx, replay
    reports = []
    with tempfile.TemporaryDirectory(prefix="modeldata_proof_") as tmp:
        root = Path(tmp)
        runs = [r[0] for r in store.fetchall("SELECT run_id FROM model_runs WHERE run_kind = 'GOLDEN_FIXTURE' "
                                             "ORDER BY run_id")]
        for run_id in runs:
            if fixtures and run_id not in fixtures:
                continue
            store.materialize_run(run_id, root)
        ext = root / "external"
        for run_id in runs:
            if fixtures and run_id not in fixtures:
                continue
            ctx = Ctx(fixtures_dir=root / "fixtures", frozen_zip=root / "archive" / FROZEN_ZIP.name)
            report = replay(run_id, ext if ext.exists() else None, ctx)
            report["input_source"] = "MODEL_DATA_DB"
            store.record_result(run_id, "MODEL_DATA_DB", report["status"], report)
            reports.append(report)
    return reports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Import golden fixtures into the model-data store and prove replay.")
    ap.add_argument("--url", default=os.environ.get("GAMBLING_MODELDATA_URL"), required=False)
    ap.add_argument("--external", default=os.environ.get("GOLDEN_EXTERNAL_DIR"))
    ap.add_argument("--skip-import", action="store_true")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("--url or GAMBLING_MODELDATA_URL is required")
    store = connect(args.url)
    out = {"backend": store.dialect, "python": platform.python_version(), "migrated": store.migrate()}
    if not args.skip_import:
        out["import"] = import_golden(store, Path(args.external) if args.external else None)
    reports = prove_golden(store)
    out["replays"] = [{k: r[k] for k in ("fixture_id", "status") if k in r} | ({"reason": r["reason"]} if
                      "reason" in r else {}) for r in reports]
    print(json.dumps(out, indent=2))
    return 0 if all(r["status"] in ("PASSED", "SKIPPED") for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
