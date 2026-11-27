# NHL — model and bet-sheet authority

**Archived source:** `legacy_models/nhl_day0/`  
**Working scope:** NHL Day-0 source; later versions require explicit authority reconciliation  
**Current certification:** frozen-replay adapter `gambling/models/nhl/day0_legacy.py` reproduces the archived Nov 12 output exactly (golden `NHL_DAY0_20261112`). It is research only: no NHL release is wager-authorized, and nothing here changes that.

## Frozen Day-0 adapter (2026-11-25)

| Market | Champion (scoring authority, no wagering) | Challenger | Challenger state |
|---|---|---|---|
| Moneyline | `NHL_ML_DAY0_V1_20261025` | `NHL_ML_V3` | Re-emits the no-vig market probability (`MARKET_ANCHOR_NO_INDEPENDENT_EDGE`) |
| Spread (puck line) | `NHL_PL_DAY0_V1_20261025` | `NHL_PL_V1` | UNSCORED: no game-specific oriented PL V1 probability |
| Total | `NHL_OU_DAY0_V1_20261025` | `NHL_V15_CONDITIONAL_COUNT` | UNSCORED: certified 2026-27 current-season features pending |

- **What runs:** the unchanged `legacy_models/nhl_day0/day0_production.py` (SHA-256 `ae1f9c5b…`), driven through the unchanged original capture adapter (`3a52e462…`) on the frozen controls `OBSERVED_PRICE_ALL_CONTROLS.csv` (`4b6119a0…`, 20,470 rows, frozen through 2025). Everything runs in a subprocess and is hash-checked before running. The inputs come from the golden fixture or, by SHA-256, from the model-input store (`Day0Inputs.from_store`).
- **Probabilities and pushes:** probabilities are the scorer's own P(win/loss/push). The push probability is captured from `score_games` because the archived CSV drops it.
  - Integer totals (for example 6.0) carry the model's push probability (`push_probability_status=MODEL`; 0.109 on Nov 12).
  - Moneyline and ±1.5 puck lines carry the model's P(push)=0.
- **Pricing:** EV and Full Kelly are recomputed by `gambling/scoring/pricing.py`. They equal the archived values on all 88 scored rows.
- **Tiers:** `Lean` (status `RESEARCH_POSITIVE_EV`) for positive-EV champion rows, otherwise `Pass`. Exactly as recorded; no row is QUALIFIED.
- **Adjusted Kelly:** null. The scorer emits `adjusted_kelly=None` with `authorized_stake_usd=0`.
- **Incomplete boards:** an event without six `OFFERED_PREGAME` sides is skipped by the original adapter. The new adapter shows it as UNSCORED rows (`INCOMPLETE_OR_NOT_PREGAME_BOARD`) instead of dropping it.
- **Bet sheet:** `gambling.betsheets.nhl.build_capture_sheet(quotes_csv, authority)`. It gives each quoted side × the champion and challenger of its market (132 rows on Nov 12). Regression sheet: `tests/fixtures/betsheets/NHL_DAY0_20261112_betsheet.csv` (SHA-256 `b2b91b78…`).

**Reconciliation (2026-11-25):** all 552 recorded Day-0 rows of the user database (Nov 7–11) reproduce exactly from the database's own quotes (`docs/reconciliation/2026-11-25-recorded-history.md`).

**Daily pipeline (2026-11-27, `UNVALIDATED_GENERALIZED_WRAPPER`):** `python -m gambling daily NHL --date D [--capture …]` (`gambling/pipeline/nhl.py`). The capture rows of NHL games starting on D (Central) are copied to `inputs/quotes.csv` and scored by the unchanged Day-0 scorer on the frozen controls (hash-checked; frozen through 2025, so 2026-27 games use prior-season segments). Output: a new run folder (sheet CSV/Excel, manifest with hashes), recorded in `gambling.sqlite` (`pipeline_runs`, `pipeline_sheet_rows`). Research only: no row can be wager-eligible. Through the pipeline the Nov 12 capture reproduces the regression sheet byte for byte (`tests/test_pipeline_nhl.py`).

**Known scorer artifacts (recorded, not changed):** the contracts carry a hard-coded `date` of 2026-10-27 and `source_label` "BetUS direct page", although the Nov 12 prices are Bovada. The sheet uses the quote's own time and bookmaker. The scorer label is kept in the row diagnostics.

**Before any live or production use:** a decision on refreshing the controls (frozen through 2025, so 2026-27 games are scored on prior-season segments only); the missing PL V1 and V15 inputs; and ChatGPT evaluation of the Day-0 residual edge. The user's `data/gambling.sqlite` holds no NHL `model_scores` for batch `20261112T134056Z_68f7ec`, so the fixture CSV is the reference.

## Required model audit

Distinguish sides/totals/Grand Salami; verify ties-refund semantics where market rules apply, V14/V13 authority, Day-0 restrictions and research-only classifications.

Preserve market-specific champion/challenger/research distinctions, immutable release IDs and original-at-quote authorization. Record source cutoff, scoring/quote UTC times, production gates, holdout evidence, calibrated P(win/push/loss), EV, Full Kelly and Adjusted Kelly. A missing model artifact must be labelled blocked, not silently reimplemented as an unapproved authority.

## Bet-sheet acceptance criteria

Use `docs/betsheets/shared-contract.md`. Show all event/market/side rows (positive/zero/negative, Pass, Lean, blocked/unscorable), chronological order, original tier, model release, actual quoted price, EV, Kelly variants and reason when a figure is unavailable. Where an outside baseline or sport-specific diagnostic is used, document the real source, refresh time, and comparison calculation.

## Before production promotion

- [ ] Name and hash frozen model release and inputs.
- [ ] Reproduce historical scoring with golden fixtures including negative EV and missing-data rows.
- [ ] Compare new outputs to original historical model output without rewriting recorded observations.
- [ ] Document version, tier/eligibility changes, new-versus-existing bet logic, and tests.
- [ ] Update `ROADMAP.md`, `docs/model-authority.md`, and this file in the same PR.
