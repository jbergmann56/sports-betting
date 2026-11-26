# M1 verification: migration 0006 on a copy of the real `data/gambling.sqlite`

**Date:** 2026-11-25 · **Code:** `feature/core-model-data-sqlite` @ `a107847` (PR #9) · **Environment:** Python 3.13.18, scikit-learn 1.8.0 (`requirements-models.txt`)

## Input

The user uploaded the file from `C:\Github\Sports-Betting\data\gambling.sqlite`. Neither the original nor the migrated file is committed.

| Check | Result |
|---|---|
| Bytes | 46,010,368 |
| SHA-256 | `ef84f3a05ae775c6b4678a28a4beb56a44791372b9ff595b48c94d1bfb236739` |
| `PRAGMA integrity_check` / `foreign_key_check` | ok / none |
| Applied migrations | 0001–0005 (2026-11-11) |
| Capture batches / market quotes / model scores | 32 / 10,158 / 10,173 (matches the Nov 12 state) |
| Events / official results / releases / wager links | 1,693 / 124 / 18 / 0 |
| Batch range | `20261111T190119Z_dd69e0` … `NFL_20261110_072712CST` |

## Steps (on a copy only)

1. `open_store(copy).migrate()` → applied `0006_model_data` only. `schema_migrations` now lists 1–6.
2. `python -m gambling.modeldata --db COPY golden --external <reproducibility package>`. This step:
   - imported the five golden fixtures;
   - imported the NCAABB externals;
   - imported the NCAABB master as the base of `ncaabb/master`: 29,008 records, PUBLISHED, keyed by `game_id`.

## Results

- All five golden fixtures replay **PASSED** from inputs materialized from the copy: NFL, NHL, NCAAFB, NBA R4 and NCAABB V4.
- 48 sources and 37 dataset versions; every version re-verifies lossless against its preserved bytes.
- After migration and import, `integrity_check` is ok and `foreign_key_check` finds nothing.
- None of the 18 pre-existing tables changed (row hashes below, identical before and after both steps).
- No pre-existing schema object was removed or altered; every added object belongs to `md_*`.
- Migrated copy: 307,929,088 bytes, SHA-256 `0afe02725742bdcad7a90f5309e2727cdf58f38b226f3652da92f73e9f9b1f8d`.

| Table | Rows | Row hash (before = after) |
|---|---|---|
| `capture_batches` | 32 | `7c7fe6ce167db9ba` |
| `events` | 1,693 | `43620c26e507466d` |
| `fetch_attempts` | 118 | `62d752e8bdad499e` |
| `fetch_runs` | 4 | `70bdbcbd905cbaa9` |
| `history_imports` | 1 | `825f45945568664a` |
| `market_quotes` | 10,158 | `ae9f7f230e3725f8` |
| `model_release_aliases` | 33 | `40532ad8687c7877` |
| `model_release_artifacts` | 46 | `35b9c753efdeb270` |
| `model_release_status` | 18 | `07f12285bf904c50` |
| `model_releases` | 18 | `45c756cf79f632c4` |
| `model_scores` | 10,173 | `81cd8551d84c507d` |
| `official_game_results` | 124 | `f00663106569af41` |
| `quote_cohorts` | 51 | `4fa088e5370d3046` |
| `quote_outcomes` | 1,332 | `4737ff48fe0aaf17` |
| `settlements` | 148 | `154caeab5ffb725d` |
| `source_files` | 152 | `0d933c46ce1e2d42` |
| `sport_fetch_status` | 20 | `dceaaaec30711ec8` |
| `wager_links` | 0 | `4f53cda18c2baa0c` |

## Not done

- The live file on the PC has not been migrated. Opening it with this branch's code applies 0006 automatically, so make an offline backup first (`python -m gambling.modeldata snapshot <outside repo>`), or replace it with the verified migrated copy.
- Nothing appends to `ncaabb/master` automatically until the NCAABB daily run exists.
