# NCAABB — model and bet-sheet authority

**Archived source:** `legacy_models/ncaabb_v4/; legacy_models/ncaabb_v5/`  
**Working scope:** NCAABB V4 frozen release and V5 shadow research  
**Current certification:** historical reference only for any newly generalized adapter. No new production `gambling/models/ncaabb/` adapter is certified by this reorganization.

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
