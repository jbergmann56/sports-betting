# Implementation report — versioned model-input database (MySQL)

**Date:** 2026-11-25 · **Branch:** `feature/core-model-data-mysql` (stacked on `feature/core-scoring-betsheet`) · **Base:** `main` @ `734d44c`
**Release IDs affected:** none (no scorer, probability, tier, registry or authorization change). **Promotion:** not authorized.

## Files changed

- `gambling/modeldata/` (new): `store.py` (MySQL/SQLite store), `golden.py` (fixture import + proof), `__main__.py` (CLI), `schema/mysql/0001_model_data.sql`, `schema/sqlite/0001_model_data.sql`, `schema/mysql/grants.example.sql`.
- `tests/golden/replay.py`: input-source context (`Ctx`) so replays can read inputs materialized from the database; behaviour with defaults unchanged (5/5 PASS re-verified).
- `tests/test_modeldata.py` (new): 11-test contract run on SQLite and MySQL, Parquet import, schema-change refusal, golden-from-database proof.
- CI: `modeldata-mysql` job with a MySQL 8.0 service. Packaging extras `[mysql]`, `[parquet]`. `.gitattributes`: schema files `-text` (they are hash-checked).
- Docs: `docs/model-data/README.md` (schema, provenance, retrieval, import, Azure setup, backup, gated migration), `docs/architecture.md`, `ROADMAP.md`.

## Before / after golden replay

| Fixture | Inputs from repo (before) | Inputs re-materialized from MySQL 8.0.46 (after) | From SQLite (after) |
|---|---|---|---|
| NFL_20261110_072712CST | PASSED | PASSED | PASSED |
| NHL_DAY0_20261112 | PASSED | PASSED | PASSED |
| NCAAFB_20261102 | PASSED | PASSED | PASSED |
| NBA_R4_20261112 | PASSED | PASSED | PASSED |
| NCAABB_V4_20261101 | PASSED (sklearn 1.8.0 + external) | PASSED | PASSED |

Identical outputs under the golden rule ⇒ original probabilities, EV and tiers unchanged.

## Other verification (MySQL 8.0.46)

48 sources, 37 versions, 88,432 rows; `verify_version` lossless 37/37; triggers reject UPDATE/DELETE on evidence tables; idempotent re-import; preflight refuses to start DDL when `log_bin_trust_function_creators` is OFF (no partial schema). Real Parquet upload `betting_2023(1).parquet` (`7e6276f6…`) imported losslessly as 911 rows and left `STAGED`.

## Tests

`python -m unittest discover -s tests` → 111 OK (12 skipped without MySQL/external inputs). With MySQL and the model environment: `tests.test_modeldata` 23/23 OK, none skipped. Documentation gate passed.

## Kelly methodology

Not affected.

## Blockers / next steps

1. Azure server availability and credentials unverified from this session (M1). Requires `log_bin_trust_function_creators=ON`.
2. Typed projections (odds, features) and history import (M3).
3. Decide storage of the 81 MB NCAABB inputs on Azure (DB chunks vs Blob Storage keyed by SHA-256).

**ChatGPT review:** not required for forecasts; ChatGPT can read datasets through the `modeldata_reader` role once M2 passes.
