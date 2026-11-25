# Implementation report: NHL Day-0 frozen-replay adapter

**Date:** 2026-11-25 · **Branch:** `sport/nhl`, stacked on `sport/nfl` (PR #8) · **Promotion:** none · **Refit:** none

## Files and release IDs

- `gambling/models/nhl/day0_legacy.py` (new): `NHL_ML_DAY0_V1_20261025`, `NHL_PL_DAY0_V1_20261025`, `NHL_OU_DAY0_V1_20261025`, `NHL_ML_V3`, `NHL_PL_V1`, `NHL_V15_CONDITIONAL_COUNT`.
- `gambling/betsheets/nhl/__init__.py`: `build_capture_sheet`.
- `gambling/scoring/sheet.py`: `assemble(..., market_releases=)`. Optional; existing behaviour unchanged.
- `tests/test_nhl_adapter.py` (8 tests); `tests/fixtures/betsheets/NHL_DAY0_20261112_betsheet.csv` + `.sha256`.
- Docs: `docs/sports/nhl.md`, `docs/model-authority.md`, `docs/architecture.md`, `ROADMAP.md`.

## Before / after

| Check | Archived (fixture) | Adapter + shared pricing |
|---|---|---|
| Rows | 132 | 132 |
| PASS / UNSCORED / RESEARCH_POSITIVE_EV | 81 / 44 / 7 | 81 / 44 / 7 |
| p_win, tier, status per row | — | identical (132/132) |
| EV / Full Kelly (88 scored rows) | archived | max abs difference 0.0 |
| Golden replay `NHL_DAY0_20261112` | PASSED | PASSED (scorer untouched) |

## Kelly methodology

Full Kelly is the shared formula with the model's own push probability, (b·p_win − p_loss)/(b·(p_win + p_loss)). This equals the scorer's `full_kelly_diagnostic`. Adjusted Kelly is null, because the release supplies none and is research only.

## Confirmation

Probabilities, tiers, statuses and authorization are unchanged. No release is wager-authorized, and no archived file was modified.

## Blockers

- The controls are frozen through 2025.
- PL V1 and V15 inputs are missing.
- No live NHL `model_scores` exist for Nov 12 in the user database.
- ChatGPT evaluation is required before any change in authority.
