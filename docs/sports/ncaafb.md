# NCAAFB — model and bet-sheet authority

**Archived source:** `legacy_models/ncaafb/authority.json; legacy_models/ncaafb/score_both.py`  
**Working scope:** NCAAFB point-in-time SRS and market-specific authority  
**Current certification:** frozen-replay adapter `gambling/models/ncaafb/w8plus_legacy.py` reproduces the archived Nov 2 (Week 10) output exactly (golden `NCAAFB_20261102`). It covers that archived board only; new weeks need the live inputs listed below.

## Frozen Week 8+ adapter (2026-11-25)

| Market | Release | Registry role / wagering | Side the rule evaluates |
|---|---|---|---|
| Spread | `NCAAFB_SPREAD_PP_V2_20261028` | CHAMPION / authorized (provisional, Health "Watch") | Higher-slope team; eligible if underdog and \|Z\| ≥ 1.243 |
| Spread | `NCAAFB_SPREAD_CONTINUOUS_V1_20261023` | CHALLENGER / not authorized | Same |
| Moneyline | `NCAAFB_ML_W8PLUS_RULE` (shared by both configurations; asserted identical) | CHAMPION / authorized | Underdog in the +250..400, total 45..55 regime |
| Total | `NCAAFB_OU_RESEARCH` (shared; asserted identical) | RESEARCH / zero allocation | Under when PFPA − total ≤ −5 |

- **What runs:** the unchanged `build_features.py` and `score_both.py` (hash-pinned), on the archived inputs (hash-checked against the fixture manifest).
- **Quotes:** built from the archived raw Bovada coupon response, with outcome price IDs as `quote_id`. Every price the scorer read from `quoted_lines.csv` must equal the raw outcome.
- **Sides the rule never looks at:** `NOT_EVALUATED_BY_MODEL`. Where the line is mirrored, the shared sheet shows a labelled `DERIVED_COMPLEMENT`, never eligible.
- **Probability basis:** P(win | decisive), per the authority's conditional-decisive settlements. Half-point spreads and the moneyline are unconditional with P(push)=0. Integer spreads and totals (11.0, 3.0, 17.0, 72.0, 55.0 on Nov 2) are `CONDITIONAL_SCORED` with push UNKNOWN (PR #4 decision 4). EV and Full Kelly use the conditional formulas, which equal the scorer's `max(0,(p(1+b)−1)/b)`.
- **Tiers to action classes, as recorded:** B+/B provisional and A existing → QUALIFIED; Lean → LEAN; Pass and B descriptive → PASS. The status comes from the registry at quote time. Only the PP-V2 champion and the ML rule can be PRODUCTION_QUALIFIED; continuous V1 is QUALIFIED_NOT_WAGER_AUTHORIZED.
- **Unscored rows:** the UAB SRS-gate row is UNSCORED ("current published UAB SRS not recovered; stale 4-3 source not substituted"). The scorer's hypothetical probability stays in the diagnostics, never in `p_win`.
- **Adjusted Kelly:**
  - Spread and ML: null, "Joint sizing not run; current exposure not reconciled". The authority's joint expected-log optimizer was not run for this board, and no stand-in is computed.
  - OU: 0 (zero normal allocation), passed through as recorded.

**Nov 2 sheet:** 496 rows (62 games × 8 side-release pairs).
- Six rows are PRODUCTION_QUALIFIED: Texas State +6.5 (B+ provisional) and the five A existing moneyline underdogs (Akron, Arkansas, Marshall, Northern Illinois, UTEP).
- Six continuous-V1 spreads are QUALIFIED_NOT_WAGER_AUTHORIZED.
- Two OU Unders are LEAN.
- One row (UAB gate) is UNSCORED.

Regression sheet: `tests/fixtures/betsheets/NCAAFB_20261102_betsheet.csv` (SHA-256 `d03ae32d…`).

PRODUCTION_QUALIFIED records the original pre-bet authorization as registered. It is not a recommendation to bet, and this app places no wagers.

**Parser refactor (2026-11-25, NCAABB PR):** the Bovada coupon parsing moved to the shared `gambling/core/bovada.py`. `quotes_from_bovada` keeps its signature, and the NCAAFB regression sheet is byte-identical.

**Reference:** the user database holds NCAAFB `model_scores` for Nov 6–10 but none for Nov 2, so the fixture's archived output is the reference. Reconciling the Nov 9/10 `PROJECT_RULES` / `ALL_QUOTES` batches against this adapter is a follow-up.

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
