# Implementation report: NCAABB V4 frozen-replay adapter and master append

**Date:** 2026-11-25 · **Branch:** `sport/ncaabb`, stacked on `feature/core-model-data-sqlite` (PR #9, now stacked on #12) · **Promotion:** none · **Refit:** none

## Files and release IDs

- `gambling/models/ncaabb/v4_legacy.py` (new): `NCAABB_V4_PROD_THROUGH2025`, plus `master_records_from_inputs` and `append_run_to_master`.
- `gambling/betsheets/ncaabb/__init__.py`: `build_frozen_sheet`.
- `gambling/core/bovada.py` (new; shared parser). NCAAFB now uses it, and its regression sheet is byte-identical.
- `gambling/modeldata/store.py`: `append_records` refuses an unregistered `run_id` with a clear error, instead of a foreign-key failure.
- `tests/test_ncaabb_adapter.py` (12 tests, including 2 external); `tests/test_modeldata.py` (+1); `tests/fixtures/betsheets/NCAABB_V4_20261101_betsheet.csv` + `.sha256`.
- Docs: `docs/sports/ncaabb.md`, `docs/model-authority.md`, `docs/betsheets/shared-contract.md`, `docs/model-data/README.md`, `docs/architecture.md`, `ROADMAP.md`.

## Before / after

| Check | Archived | Adapter |
|---|---|---|
| Scored market rows | 35 | 35 mapped; 76-row sheet |
| P, push, EV, Full Kelly, Adjusted Kelly | archived | identical (EV / Full Kelly difference 0.0) |
| Full pipeline rerun (external package) | — | prior ratings, inputs and scored markets IDENTICAL; preparer's block reason recovered |
| PRODUCTION_QUALIFIED | — | 9, from recorded `stake_eligible` (7 tier Lean, 2 tier B) |
| Master append (real master) | 29,008 | 29,021 after the Nov 1 run; 0 added on rerun |
| Golden replay `NCAABB_V4_20261101` | PASSED | PASSED |

## Kelly methodology

- **Full Kelly:** (b·p − (1−p))/b on the conditional non-push probability, which equals V4's.
- **Adjusted Kelly:** V4's evidence-factor heuristic, passed through as `LEGACY_NOT_PORTFOLIO_CERTIFIED`.

## Confirmation

Probabilities, tiers and authorization are unchanged. No archived file was modified, and the master's existing records are untouched (append only).

## Open review item

Seven V4 rows with tier "Lean" are recorded `stake_eligible=True` and therefore show as PRODUCTION_QUALIFIED. Should they? ChatGPT/user to decide. Any change must be a separately versioned authority record, not an adapter edit.

## Blockers

- A live daily preparer.
- A results builder for the master-only columns.
- A V5 shadow adapter.
- Reconciling the Nov 6–10 user-database batches.
