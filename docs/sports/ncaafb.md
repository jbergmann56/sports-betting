# NCAAFB — model and bet-sheet authority

**Archived source:** `legacy_models/ncaafb/authority.json; legacy_models/ncaafb/score_both.py`  
**Working scope:** NCAAFB point-in-time SRS and market-specific authority  
**Current certification:** historical reference only for any newly generalized adapter. No new production `gambling/models/ncaafb/` adapter is certified by this reorganization.

## Required model audit

Reconstruct and freeze release versions, check past-season SRS, ML underdog segmentation, spread restrictions, OU blockers and missing week-one inputs.

Preserve market-specific champion/challenger/research distinctions, immutable release IDs and original-at-quote authorization. Record source cutoff, scoring/quote UTC times, production gates, holdout evidence, calibrated P(win/push/loss), EV, Full Kelly and Adjusted Kelly. A missing model artifact must be labelled blocked, not silently reimplemented as an unapproved authority.

## Bet-sheet acceptance criteria

Use `docs/betsheets/shared-contract.md`. Show all event/market/side rows (positive/zero/negative, Pass, Lean, blocked/unscorable), chronological order, original tier, model release, actual quoted price, EV, Kelly variants and reason when a figure is unavailable. Where an outside baseline or sport-specific diagnostic is used, document the real source, refresh time, and comparison calculation.

## Before production promotion

- [ ] Name and hash frozen model release and inputs.
- [ ] Reproduce historical scoring with golden fixtures including negative EV and missing-data rows.
- [ ] Compare new outputs to original historical model output without rewriting recorded observations.
- [ ] Document version, tier/eligibility changes, new-versus-existing bet logic, and tests.
- [ ] Update `ROADMAP.md`, `docs/model-authority.md`, and this file in the same PR.
