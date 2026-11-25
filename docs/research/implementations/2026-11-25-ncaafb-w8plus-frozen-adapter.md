# Implementation report: NCAAFB Week 8+ frozen-replay adapter

**Date:** 2026-11-25 · **Branch:** `sport/ncaafb`, stacked on `sport/nhl` (PR #10) · **Promotion:** none · **Refit:** none

## Files and release IDs

- `gambling/models/ncaafb/w8plus_legacy.py` (new): `NCAAFB_SPREAD_PP_V2_20261028`, `NCAAFB_SPREAD_CONTINUOUS_V1_20261023`, `NCAAFB_ML_W8PLUS_RULE`, `NCAAFB_OU_RESEARCH`.
- `gambling/betsheets/ncaafb/__init__.py`: `build_frozen_sheet`.
- `tests/test_ncaafb_adapter.py` (11 tests); `tests/fixtures/betsheets/NCAAFB_20261102_betsheet.csv` + `.sha256`.
- Docs: `docs/sports/ncaafb.md`, `docs/model-authority.md`, `docs/betsheets/shared-contract.md`, `ROADMAP.md`.

## Before / after

| Check | Archived | Adapter |
|---|---|---|
| Rows | 186 game-markets | 496 side-release rows (every archived row mapped) |
| Tier, P, EV, Full Kelly | archived | identical: 20 priced rows, max EV difference 2.2e-16 |
| Fresh scorer rerun vs archived output | — | identical within 1e-9 (golden rule) |
| PRODUCTION_QUALIFIED | — | 6: 1 PP-V2 spread + 5 ML rule, all registry-authorized champions |
| Golden replay `NCAAFB_20261102` | PASSED | PASSED (scorers untouched) |

## Kelly methodology

- **Full Kelly:**
  - unconditional on half-point lines and the moneyline: (b·p − (1−p))/b;
  - conditional diagnostic on integer lines: (b·p − (1−p))/b.
  Both equal the authority's `max(0,(p(1+b)−1)/b)`.
- **Adjusted Kelly, spread and ML:** null. The joint optimizer was not run, and exposure is not reconciled.
- **Adjusted Kelly, OU:** 0, as recorded (zero allocation).

## Confirmation

Probabilities, tiers and authorization are unchanged. No archived file was modified.

## Blockers

- Live weekly features, the posterior refresh decision, the SRS gate source and results ingestion.
- Reconcile the user-database NCAAFB batches from Nov 6–10.
