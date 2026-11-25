# Golden replay fixtures

Five frozen fixtures prove that the archived sport scorers reproduce their archived
outputs exactly. They are the regression gate for every adapter, scoring, bet-sheet
and data-layer change: **a change that alters any fixture output is a model change**
and goes through `docs/handoff/RESEARCH_TO_DEVELOPMENT.md`, not a code PR.

| Fixture | Release IDs | Expected rows | Inputs | Runs in CI |
|---|---|---|---|---|
| `NFL_20261110_072712CST` | `NFL_REV2_CAL_20261024`, `NFL_W8_FULL_SLOPE_20261026` | bet sheet 36, side inputs 72, team features 32 | members of the committed frozen ZIP | yes |
| `NHL_DAY0_20261112` | Day-0 ML/PL/OU champions; ML V3, PL V1, V15 challenger rows as re-emitted | 132 | controls (20,470 rows), original adapter, Nov 12 quotes — committed | yes |
| `NCAAFB_20261102` | PP V2, continuous V1, ML W8+ rule, OU research | 186 market rows, 174 feature rows (+7 other result files) | Nov 2 frozen inputs — committed | yes |
| `NBA_R4_20261112` | `NBA_R4_V27_20261030` | 12 | history through Nov 11, quotes JSON, results bridge — committed | yes |
| `NCAABB_V4_20261101` | `NCAABB_V4_PROD_THROUGH2025` | ratings 365, inputs 13, scored markets 35 | small inputs committed; 2021–25 master (51.6 MB) and 2026 schedule (29.6 MB) **external** | skipped unless `GOLDEN_EXTERNAL_DIR` is set |

## Rules

- Scorers run **unchanged**: repo `legacy_models/` files or frozen-ZIP members, verified by SHA-256 before every run.
- Every committed input and expected output is pinned by SHA-256 in `tests/golden/fixtures/<id>/MANIFEST.json`. A hash change fails the stdlib test `test_committed_evidence_hashes_match`.
- Comparison: equal row count and column list; numeric `|diff| ≤ 1e-9` with identical NaN positions; other columns equal as strings. Observed maximum differences are ≤ 1.5e-13 (floating-point summation order).
- Documented, per-fixture normalizations only:
  - NBA `Frozen_UTC` (run timestamp) is excluded.
  - NCAAFB `result_update_provenance.csv` `Source` holds the absolute path of the original run's input file; compared by file name.
  - NHL expected rows come from the consolidated Nov 12 export, which added presentation columns `start_ct`, `local_date`, `slate`; all 22 scorer-produced columns are compared and the 3 presentation columns are reported as `not_compared`.
- A fixture that cannot run reports `SKIPPED` with the reason (missing module, scikit-learn version, external inputs). It is never reported as passed.

## Environment

`requirements-models.txt` (also `pip install -e .[models]`) pins the verified environment: Python 3.13.18, scikit-learn **1.8.0**, numpy 2.5.5, pandas 3.1.1, scipy 1.18.1, joblib 1.6.0. scikit-learn is mandatory for NCAABB: the V4 binary was pickled with 1.8.0 and 1.9.1 cannot load it. The core `gambling` package remains standard-library only.

## External inputs (NCAABB)

Not committed because the repository is public and the master contains user-observation flags (`actual_bet_status`; stakes are zero). Source: `GAMBLING_DAILY_FEATURE_SOURCE_REPRO_20261112.zip` (SHA-256 `77d76377…c46a`, 18,786,561 bytes). Extract it and set `GOLDEN_EXTERNAL_DIR` to the extracted root; the harness verifies each external file's SHA-256 before use. These inputs move to the model-input database (`docs/model-data/`) once it is validated.

## Commands

```bash
python -m unittest tests.test_golden_replay -v           # skips report reasons
GOLDEN_EXTERNAL_DIR=/path/to/package python -m tests.golden.replay   # JSON report, all five
python -m tests.golden.build_manifests                   # only when creating a NEW fixture
```

Never regenerate an existing fixture's manifest to make a failing replay pass.
