# Implementation report — NFL REV2-CAL / W8 frozen-replay adapter

**Date:** 2026-11-25 · **Branch:** `sport/nfl` (stacked on `feature/core-scoring-betsheet` ← `feature/core-golden-replay` ← `docs/claude-transfer-readiness-20261124`) · **Base:** `main` @ `734d44c`
**Promotion / wager authorization:** **not authorized; none changed.** No model refit, recalibration, re-tier or registry change.

| Field | Value |
|---|---|
| Release IDs affected | `NFL_REV2_CAL_20261024` (champion), `NFL_W8_FULL_SLOPE_20261026` (challenger) — read only |
| Artifact hashes | frozen-ZIP `scoring/score.py` `6fe3e0e4…74b`, `champion_config_preserved.json` `eba7e749…506`, `metadata.json` `88e2f6ad…e9e` (pinned in code, equal to migration `0005`); `model/src/*.py` byte-identical to `legacy_models/nfl/*` |
| Input evidence | `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip!NFL_20261110_072712CST/` — Bovada snapshot retrieved 2026-11-10T13:27:12.524437Z (payload `2d9ee2a6…d65`), 12 games, 72 quoted sides; Week 9 complete (15/15) |

## Files changed

- `gambling/models/nfl/rev2_legacy.py` (new) — wide-snapshot → `QuoteSide` converter, frozen-output → `ScoreRow` v2 mapping, optional re-execution of the unchanged scorer, pinned member hashes.
- `gambling/betsheets/nfl/__init__.py` — `build_frozen_sheet` (complete chronological sheet).
- `gambling/scoring/sheet.py` — `Authority.from_connection` (registry lookup from an open connection).
- `tests/test_nfl_adapter.py` (new, 9 tests); `tests/fixtures/betsheets/NFL_20261110_072712CST_betsheet.csv` + `.sha256` (regression).
- Docs: `docs/sports/nfl.md`, `docs/model-authority.md` (adapter log), `docs/betsheets/shared-contract.md`, `ROADMAP.md`.

## Before / after (same quotes, same releases)

| Check | Before (archived) | After (adapter + shared scoring) |
|---|---|---|
| Golden replay `NFL_20261110_072712CST` | 36 / 72 / 32 rows | **IDENTICAL** (max abs diff 3.6e-14) |
| Archived `model_scores` rows (batch `NFL_20261110_072712CST`) | 72 rows: 1 PRODUCTION_QUALIFIED, 1 RESEARCH_POSITIVE_EV, 70 PASS | **72/72 match**: status, tier, probability (exact equality), EV and Full Kelly (≤1e-12), line, odds |
| Model probabilities | 4 champion + 6 challenger | identical floats; 4 champion rows on integer lines → `CONDITIONAL_SCORED`; challenger 3 `SCORED` (half line / ML), 3 `CONDITIONAL_SCORED` |
| Coverage | 36 game-markets (one row per market per model) | **144 rows** = 72 quoted sides × 2 releases; 42 `NOT_EVALUATED_BY_MODEL` with labelled complements where justified |
| Production qualifier | BAL −5 (−110), tier A, EV +0.00286, Full Kelly 0.00314 | same, `PRODUCTION_QUALIFIED` (champion, wagering authorized at quote time) |
| Research signal | TEN ML +400, challenger, EV +0.1761, Full Kelly 0.0440 | same, `RESEARCH_POSITIVE_EV`, `release_wager_authorized=FALSE` |

## Kelly methodology and status

- **Full Kelly:** legacy `max(0, p − (1−p)/b)` = shared formula; on integer lines labelled `CONDITIONAL_SINGLE_BET_DIAGNOSTIC` (P is win given decisive; push probability UNKNOWN per decision 4).
- **Adjusted Kelly:** not computed by either release. Null with reason `RELEASE_REPORTS_UNAVAILABLE: Joint predictive distribution and existing exposure amounts unavailable`. No haircut introduced.

## Tests

`python -m unittest discover -s tests` → **97 tests OK** (1 skipped: NCAABB golden without external inputs). `tests/test_nfl_adapter.py` 9/9 including fresh re-execution. Documentation gate passed.

## Confirmation

Original model probabilities, tiers, recorded actions and registry authorization are unchanged; the adapter only reshapes frozen output and adds labelled arithmetic.

## Remaining blockers (NFL)

1. Live pipeline: source of `games_snapshot.csv` (schedule + results used for team features) is undocumented; needs an independent results feed with point-in-time cutoff.
2. Capture → `board.json` converter for live Bovada captures.
3. `score_as_of_utc` is not written by the scorer; the archive records 2026-11-10T13:29:43.370561Z in `model_scores.scored_at_utc` (not yet joined into the sheet).

**ChatGPT review:** not required for forecast merit — no forecast, calibration, tier or sizing change. Shared presentation rules (complements, conditional basis) follow PR #4 decisions 3–4.
