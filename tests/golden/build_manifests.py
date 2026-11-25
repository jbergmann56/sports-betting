"""Write MANIFEST.json for each golden fixture (run once when a fixture is created).

Records SHA-256 and size of every committed input and expected output, the
exact scorer files (repo paths or frozen-ZIP members), external inputs that are
deliberately NOT committed, provenance and the verified environment. Re-running
must reproduce identical hashes; a changed hash means evidence changed and the
fixture must not be silently regenerated.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tests.golden.replay import FIXTURES_DIR, FROZEN_ZIP, REPO, sha256

PACKAGE = {
    "name": "GAMBLING_DAILY_FEATURE_SOURCE_REPRO_20261112.zip",
    "sha256": "77d7637777806501e8bf47b62003e7d48864d85bf0a4cd63ee5e23287f2ac46a",
    "bytes": 18786561,
    "note": "User-supplied Feature Source & Reproducibility package; not committed (public repository).",
}
VERIFIED_ENV = {"python": "3.13.18", "scikit-learn": "1.8.0", "numpy": "2.5.5", "pandas": "3.1.1",
                "scipy": "1.18.1", "joblib": "1.6.0", "lock_file": "requirements-models.txt",
                "verified_utc": "2026-11-25",
                "also_passes": "NFL/NHL/NCAAFB/NBA also verified with numpy 2.5.3, pandas 3.0.5, scikit-learn 1.9.1"}


def files(fixture: Path, group: str) -> list[dict]:
    root = fixture / group
    return [{"path": f"{group}/{p.relative_to(root).as_posix()}", "sha256": sha256(p), "bytes": p.stat().st_size}
            for p in sorted(root.rglob("*")) if p.is_file()]


def repo_files(*paths: str) -> list[dict]:
    return [{"location": p, "sha256": sha256(REPO / p), "bytes": (REPO / p).stat().st_size} for p in paths]


def zip_files(prefix: str, names: list[str]) -> list[dict]:
    out = []
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        for n in names:
            data = z.read(prefix + n)
            import hashlib
            out.append({"location": f"zip:data/{FROZEN_ZIP.name}!{prefix}{n}",
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return out


def build() -> None:
    nfl_prefix = "NFL_20261110_072712CST/"
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        nfl_members = sorted(n[len(nfl_prefix):] for n in z.namelist()
                             if n.startswith(nfl_prefix) and not n.endswith("/"))
    specs = {
        "NFL_20261110_072712CST": dict(
            sport="NFL", slate="2026-11-10 capture (Week 10 board)",
            release_ids=["NFL_REV2_CAL_20261024", "NFL_W8_FULL_SLOPE_20261026"],
            frozen_zip_prefix=nfl_prefix,
            scorer_files=zip_files(nfl_prefix, [m for m in nfl_members if m.startswith("scoring/") and
                                                (m.endswith(".py") or m.endswith(".json"))]) +
            repo_files(*(f"legacy_models/nfl/{n}" for n in (
                "analyze.py", "apply_calibration.py", "champion_context.py", "core.py",
                "production_calibration.py", "reconstruction.py", "segments.py"))),
            expected_rows={"dual_model_bet_sheet.csv": 36, "both_side_inputs.csv": 72, "team_features.csv": 32},
            provenance="All inputs, scorer and expected outputs are members of the committed frozen ZIP; "
                       "expected outputs are copied from the ZIP before the scorer runs.",
            comparison="dual_model_bet_sheet.csv, both_side_inputs.csv, team_features.csv",
            environment=dict(VERIFIED_ENV)),
        "NHL_DAY0_20261112": dict(
            sport="NHL", slate="2026-11-12 (capture 20261112T134056Z_68f7ec)",
            release_ids=["NHL_ML_DAY0_V1_20261025", "NHL_PL_DAY0_V1_20261025", "NHL_OU_DAY0_V1_20261025",
                         "NHL_ML_V3", "NHL_PL_V1", "NHL_V15_CONDITIONAL_COUNT"],
            scorer_files=repo_files("legacy_models/nhl_day0/day0_production.py"),
            expected_rows={"nhl_scores_20261112.csv": 132},
            provenance="Controls rebuilt exactly (20,470 rows) from NHL_DAY0_CHAMPION_AUTHORITY_V13_PACKAGE.zip; "
                       "adapter and quotes from the reproducibility package; expected = NHL rows of "
                       "20261112_all_model_scores.csv (source file retained alongside).",
            comparison="NHL rows sorted by event_id, market, side, model_role, model_version",
            environment=dict(VERIFIED_ENV, note="stdlib only")),
        "NCAAFB_20261102": dict(
            sport="NCAAFB", slate="2026-11-02 Week 10 (62 games / 186 markets)",
            release_ids=["NCAAFB_SPREAD_PP_V2_20261028", "NCAAFB_SPREAD_CONTINUOUS_V1_20261023",
                         "NCAAFB_ML_W8PLUS_RULE", "NCAAFB_OU_RESEARCH"],
            scorer_files=repo_files("legacy_models/ncaafb/build_features.py", "legacy_models/ncaafb/score_both.py",
                                    "legacy_models/ncaafb/authority.json"),
            expected_rows={"ALL_62_GAMES_BOTH_MODEL_TIERS.csv": 186, "features_weeks8_10.csv": 174},
            provenance="Inputs from the reproducibility package nov02_production_feature_rebuild/inputs plus "
                       "results/oct27_scoreboard.json; inputs/authority.json is byte-identical to "
                       "legacy_models/ncaafb/authority.json.",
            comparison="every CSV written to results/ by build_features.py and score_both.py",
            environment=dict(VERIFIED_ENV)),
        "NBA_R4_20261112": dict(
            sport="NBA", slate="2026-11-12 (4 games / 12 market rows)",
            release_ids=["NBA_R4_V27_20261030"],
            scorer_files=repo_files(*(f"legacy_models/nba_r4/{n}" for n in (
                "nba.py", "scoring_core.py", "portfolio_kelly.py", "dependence.py", "ACTIVE_RELEASE.json",
                "DEPENDENCE_MODEL.json", "RELEASE_HASHES.json", "data/v27_coefficients.json",
                "data/history.csv", "data/previous_historical_master.csv"))),
            expected_rows={"forecasts.csv": 12},
            provenance="History through 2026-11-11 from the reproducibility package; Nov 6-11 finals were "
                       "manually transcribed (bridge retained) and are accepted as frozen replay input only "
                       "(research decision 5, PR #4). Quotes JSON produced by build_nba_daily_features.py "
                       "from the Nov 12 capture. Oct 29 reference is a separate, unresolved pipeline "
                       "(decision 1) and is not part of this fixture.",
            comparison="forecasts.csv excluding Frozen_UTC (run timestamp)",
            environment=dict(VERIFIED_ENV)),
        "NCAABB_V4_20261101": dict(
            sport="NCAABB", slate="2026-11-01 (13 games / 35 market rows)",
            release_ids=["NCAABB_V4_PROD_THROUGH2025"],
            scorer_files=repo_files("legacy_models/ncaabb_v4/ncaabb_models.py",
                                    "legacy_models/ncaabb_v4/ncaabb_matchup.py",
                                    "legacy_models/ncaabb_v4/score_ncaabb_v4.py",
                                    "legacy_models/ncaabb_v4/NCAABB_V4_PRODUCTION_CANDIDATE.joblib"),
            external_inputs=[
                dict(package_path="NCAABB/basketball_audit/v4/NCAABB_DB_CLEAN_REBUILT_2021_2025.csv",
                     stage_path="basketball_audit/v4/NCAABB_DB_CLEAN_REBUILT_2021_2025.csv",
                     sha256="9d2e77c0ebf2815c3a2b073f1959e1d5372b043e47c36c0b5793d111100bf179", bytes=51585899,
                     reason_not_committed="51.6 MB; contains user-observation flags (actual_bet_status); "
                                          "public repository"),
                dict(package_path="NCAABB/nov01_v4_inputs/mbb_schedule_2026.csv",
                     stage_path="nov01_v4_inputs/mbb_schedule_2026.csv",
                     sha256="4d3a8671fe8cfd2c4d4c2faaff4d70460afc4b55880e89d3d9bb8a4797639ac6", bytes=29557108,
                     reason_not_committed="29.6 MB public SportsDataverse release; size")],
            external_package=PACKAGE,
            expected_rows={"prior_2026_ratings.csv": 365, "V4_scoring_inputs.csv": 13, "V4_scored_markets.csv": 35},
            provenance="Full rebuild from raw sources via the original prepare_and_score.py wrapper, which "
                       "restores the recorded capture time (2026-11-01T20:34:07.379540Z) before scoring.",
            comparison="prior_2026_ratings.csv, V4_scoring_inputs.csv, V4_scored_markets.csv",
            environment=dict(VERIFIED_ENV, note="Binary pickled with scikit-learn 1.8.0; 1.9.1 fails "
                                                  "(ModuleNotFoundError: _loss). Pin is mandatory.")),
    }
    for fixture_id, spec in specs.items():
        fx = FIXTURES_DIR / fixture_id
        manifest = {"fixture_id": fixture_id, **spec,
                    "inputs": files(fx, "inputs") if (fx / "inputs").exists() else [],
                    "expected": files(fx, "expected") if (fx / "expected").exists() else [],
                    "frozen_zip": {"path": f"data/{FROZEN_ZIP.name}", "sha256": sha256(FROZEN_ZIP)},
                    "comparison_rule": "row count and column list equal; numeric |diff| <= 1e-9 with identical "
                                       "NaN positions; other columns equal as strings",
                    "model_changes": "NONE - unchanged archived scorer; no refit, recalibration, re-tier or promotion"}
        (fx / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(fixture_id, len(manifest["inputs"]), "inputs", len(manifest["expected"]), "expected")


if __name__ == "__main__":
    build()
