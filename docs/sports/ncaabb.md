# NCAABB — model and bet-sheet authority

**Archived source:** `legacy_models/ncaabb_v4/; legacy_models/ncaabb_v5/`  
**Working scope:** NCAABB V4 frozen release and V5 shadow research  
**Current certification:** frozen-replay adapter `gambling/models/ncaabb/v4_legacy.py` reproduces the archived Nov 1 V4 output exactly (golden `NCAABB_V4_20261101`). It covers that archived board; live use needs the items below.

## Frozen V4 adapter (2026-11-25)

- **Release:** `NCAABB_V4_PROD_THROUGH2025` (CHAMPION, wager-authorized; effective date inferred, PR #4 decision 6).
  - `NCAABB_V5_PROSPECTIVE_SHADOW` (first score 2026-11-06) and `NCAABB_V4_VALIDATION_FROZEN2024` (retrospective only) have no scorer for this board and are not on the sheet.
- **What runs:** the unchanged `prepare_and_score.py` (via `rebuild_nov01_offline.py`) and `score_ncaabb_v4.py`, using `NCAABB_V4_PRODUCTION_CANDIDATE.joblib` (scikit-learn 1.8.0 mandatory). The master and the 2026 schedule come from the reproducibility package, hash-checked.
- **Quotes:** parsed from the archived Bovada response by the shared `gambling/core/bovada.py`: 14 events, 76 sides. Events the preparer blocked are `BLOCKED` with its reason. On Nov 1 that is Villanova @ Notre Dame: "Captured after scheduled tip / not a pregame quote".
- **Probabilities:** `selected_probability` is V4's conditional non-push probability. V4 also supplies `estimated_push_probability` (the segment's integer-line push rate on integer lines, else 0). The row is unconditional: P(win) = (1 − push)·p, P(loss) = (1 − push)·(1 − p), P(push) = push. EV equals `expected_unit_net_at_quote`, and Full Kelly equals `full_kelly`. Each market evaluates one side; the other is `NOT_EVALUATED_BY_MODEL`.
- **Action classes:** these follow V4's recorded pre-bet eligibility (`stake_eligible`): eligible → QUALIFIED; ineligible Lean → LEAN; otherwise PASS. The tier label stays in `original_tier`.
  - On Nov 1, V4 marks 9 rows eligible: 2 tier B and **7 tier Lean**, all positive-EV. All 9 are therefore PRODUCTION_QUALIFIED.
  - **Open for ChatGPT/user review:** whether a stake-eligible V4 "Lean" should count as a production qualifier. The adapter records what V4 recorded and does not re-tier.
- **Adjusted Kelly:** `final_recommended_kelly` = Full Kelly × evidence factor × health multiplier × portfolio factor (1.0, no correlation optimizer). Method `V4_EVIDENCE_FACTOR_HEURISTIC`, certification `LEGACY_NOT_PORTFOLIO_CERTIFIED` (PR #4 decision 2).
- **Master append:** `append_run_to_master` appends each run's games to `ncaabb/master` (see `docs/model-data/README.md` §6a).
- **Sheet:** 76 rows: 35 scored (9 PRODUCTION_QUALIFIED, 26 PASS), 35 not evaluated, and 6 BLOCKED/QUOTE_NOT_OFFERED. Regression sheet: `tests/fixtures/betsheets/NCAABB_V4_20261101_betsheet.csv` (SHA-256 `ce540699…`).

**Before live use:**
- A daily preparer on new captures: schedule refresh and ESPN/team mapping.
- A results builder for the 76 master-only columns.
- A V5 shadow adapter.
- Reconciling the Nov 6–10 user-database NCAABB batches (V4 and V5) against this adapter.

## Required model audit

Audit early-season feature completeness, moneyline orientation, champion vs shadow, T-Rank baseline if actually available and model-specific Kelly calibration.

Preserve market-specific champion/challenger/research distinctions, immutable release IDs and original-at-quote authorization. Record source cutoff, scoring/quote UTC times, production gates, holdout evidence, calibrated P(win/push/loss), EV, Full Kelly and Adjusted Kelly. A missing model artifact must be labelled blocked, not silently reimplemented as an unapproved authority.

## Bet-sheet acceptance criteria

Use `docs/betsheets/shared-contract.md`. Show all event/market/side rows (positive/zero/negative, Pass, Lean, blocked/unscorable), chronological order, original tier, model release, actual quoted price, EV, Kelly variants and reason when a figure is unavailable. Where an outside baseline or sport-specific diagnostic is used, document the real source, refresh time, and comparison calculation.

## Before production promotion

- [ ] Name and hash frozen model release and inputs.
- [ ] Reproduce historical scoring with golden fixtures including negative EV and missing-data rows.
- [ ] Compare new outputs to original historical model output without rewriting recorded observations.
- [ ] Document version, tier/eligibility changes, new-versus-existing bet logic, and tests.
- [ ] Update `ROADMAP.md`, `docs/model-authority.md`, and this file in the same PR.
