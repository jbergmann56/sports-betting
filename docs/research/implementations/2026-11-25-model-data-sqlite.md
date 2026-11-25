# Implementation report: model-input store in the rolling SQLite history

**Date:** 2026-11-25 · **Branch:** `feature/core-model-data-sqlite`, stacked on `feature/core-scoring-betsheet` (PR #7) · **Base:** `main` @ `734d44c`
**Supersedes:** the MySQL design on `feature/core-model-data-mysql` (never opened as a PR). The user decided "we are using sqlite in the project".
**Release IDs affected:** none. There is no scorer, probability, tier, registry or authorization change. **Promotion:** not authorized.

## Files changed

- `gambling/db/migrations/0006_model_data.sql` (new): the `md_*` tables, two views and append-only triggers, applied by the existing migrator into `data/gambling.sqlite`.
- `gambling/modeldata/`
  - `store.py`: SQLite only, using `gambling.db.migrate.connect`; atomic writes; `open_store`, `register_run(... sport, batch_id, quote_cohort_id)` validated against `model_releases`, `run_releases`, `link_scores`, `snapshot`, and `import_version(... game_key_column)`.
  - `golden.py` and `__main__.py`: `--db` / `$GAMBLING_DB` instead of a URL; new `snapshot` command.
  - Removed `schema/mysql/*` (including `grants.example.sql`), `schema/sqlite/*`, the MySQL connector and preflight.
- `tests/golden/replay.py`: input-source context (`Ctx`) carried over from the MySQL branch; defaults are unchanged.
- `tests/test_modeldata.py` (rewritten, 21 tests) covers:
  - shared migrator; untouched `source_files`; registry enforcement; foreign keys to batch and score;
  - `game_key` join; sport vocabulary; atomic rollback; snapshot;
  - the frozen-baseline linkage test; the golden-from-database proof.
- CI: `modeldata-mysql` job replaced by `modeldata` (no service container). `pyproject.toml`: `[mysql]` extra removed. `.gitattributes`: schema rule removed (migrations are already `-text`).
- Docs: `docs/model-data/README.md` (rewritten, including §2 on fit with the existing data model), `docs/architecture.md`, `ROADMAP.md`.

## Fit with the existing data model

| Conflict in the MySQL design | Resolution |
|---|---|
| Second `source_files` table | Named `md_source_files`; the existing table is unchanged |
| Second `model_releases` mirror | Removed. Foreign keys point to the existing `model_releases`; unregistered releases are refused |
| Separate `schema_versions` migrator | Removed; 0006 goes into `schema_migrations` |
| No link to quotes or scores | `batch_id` / `quote_cohort_id` foreign keys on runs, `md_run_score_links` → `model_scores`, `game_key` on rows plus `md_rows_by_game` |

## Before / after golden replay

| Fixture | Inputs from repo (before) | Inputs materialized from `md_*` in a copy of the history DB (after) |
|---|---|---|
| NFL_20261110_072712CST | PASSED | PASSED |
| NHL_DAY0_20261112 | PASSED | PASSED |
| NCAAFB_20261102 | PASSED | PASSED |
| NBA_R4_20261112 | PASSED | PASSED |
| NCAABB_V4_20261101 | PASSED (sklearn 1.8.0 + external) | PASSED |

The outputs are identical under the golden rule, so the original probabilities, EV and tiers are unchanged.
The 19 pre-existing tables hash identically before and after migration and import. The database copy was
rebuilt from the frozen archive (SHA-256 `2b8e3365…`). It is **not** the user's real database: that file is
on the user's PC, and the desktop bridge was offline.

## Tests

- `GOLDEN_EXTERNAL_DIR=<package> python -m unittest discover -s tests` in the pinned model environment: 109 OK, 0 skipped.
- Stdlib-only environment: 109 OK, 2 skipped.

## Kelly methodology

Not affected.

## Blockers / next steps

1. M1: apply 0006 to a copy of the real `data/gambling.sqlite` (32 batches / 10,158 quotes / 10,173 scores), after a verified offline backup.
2. Decide whether the live file stores the 81 MB NCAABB master. Storing it adds about 260 MB (rows plus chunks), and the file carries user-observation flags.
3. Typed projections and history import keyed by `game_key` (M2).

**ChatGPT review:** not required for forecasts. Share data through `snapshot` + SHA-256; exclude the NCAABB flagged master from shared snapshots.
