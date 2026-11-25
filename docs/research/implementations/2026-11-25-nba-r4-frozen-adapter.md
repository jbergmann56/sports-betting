# Implementation report: NBA R4 frozen-replay adapter

**Date:** 2026-11-25 · **Branch:** `sport/nba`, stacked on `sport/ncaafb` (PR #11) · **Promotion:** none · **Refit:** none

## Files and release IDs

- `gambling/models/nba/r4_legacy.py` (new): `NBA_R4_V27_20261030` (champion) and `NBA_R3_20261029` (challenger, BLOCKED).
- `gambling/betsheets/nba/__init__.py`: `build_frozen_sheet`.
- `tests/test_nba_adapter.py` (10 tests); `tests/fixtures/betsheets/NBA_R4_20261112_betsheet.csv` + `.sha256`.
- Docs: `docs/sports/nba.md`, `docs/model-authority.md`, `docs/betsheets/shared-contract.md`, `ROADMAP.md`.

## Before / after

| Check | Archived | Adapter |
|---|---|---|
| Market rows | 12 | 12 mapped; 48-row sheet (24 R4 + 24 R3 BLOCKED) |
| Tier, P, EV, Full Kelly, Adjusted Kelly | archived | identical |
| Fresh rerun of `nba.py score` | — | identical within 1e-9 (run timestamp excluded) |
| Scorer quote JSON | archived input | rebuilt byte-identically from the capture |
| PRODUCTION_QUALIFIED | — | 2 (Washington +10.5, Toronto +9.0), both registry-authorized champion rows |
| Golden replay `NBA_R4_20261112` | PASSED | PASSED (scorer untouched) |

## Kelly methodology

- **Full Kelly:** (b·p − (1−p))/b. It is unconditional on half-point lines and a conditional diagnostic on integer lines; both equal the scorer's `full_kelly`.
- **Adjusted Kelly:** the scorer's joint expected-log portfolio over conditional dependence scenarios, passed through unchanged. It is labelled `LEGACY_NOT_PORTFOLIO_CERTIFIED` (shadow dependence model).

## Confirmation

Probabilities, tiers and authorization are unchanged. No archived file was modified.

## Blockers

- An automated results feed.
- A decision on the R3 artifacts or retirement.
- The Oct 29 pipeline (research Q1).
- Reconciling the Nov 6–11 user-database batches.
