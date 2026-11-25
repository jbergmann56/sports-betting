# NFL — model and bet-sheet authority

**Archived source:** `legacy_models/nfl/`  
**Working scope:** NFL calibrated champion/segments and challengers  
**Current certification:** frozen-replay adapter `gambling/models/nfl/rev2_legacy.py` (2026-11-25) reproduces the archived Nov 10 board exactly. It is **not** a live pipeline: live scoring still needs a current schedule/results snapshot (`games_snapshot.csv` source undocumented) and a capture-to-`board.json` converter.

## Frozen-replay adapter (2026-11-25)

- Releases: `NFL_REV2_CAL_20261024` (champion, wagering authorized per registry), `NFL_W8_FULL_SLOPE_20261026` (challenger, research). Unchanged: the scorer is the frozen-ZIP `score.py`; its `model/src` files are byte-identical to `legacy_models/nfl/` (the "REV1 primitives" `core.py` is what REV2-CAL executes).
- Mapping: champion probability only for tiers A/B+ (binary win P → `SCORED` on half lines, `CONDITIONAL_SCORED` on integer lines); other tiers `EVALUATED`; the opposite side `NOT_EVALUATED_BY_MODEL`. Challenger with no selected segment = both sides `EVALUATED` / PASS. Actions mapped from recorded text: `POSITIVE EV`→QUALIFIED, `SHADOW POSITIVE EV`→RESEARCH_POSITIVE_EV, `PASS…`→PASS.
- Full Kelly: the legacy `max(0, p − (1−p)/b)` equals the shared conditional/no-push formula (verified to 1e-12). Adjusted Kelly: none computed by either release; null with the release's recorded reason ("Joint predictive distribution and existing exposure amounts unavailable").
- Evidence: golden fixture `NFL_20261110_072712CST`; `tests/test_nfl_adapter.py` matches all 72 archived `model_scores` rows (status, tier, exact probability, EV/Full Kelly to 1e-12) and re-executes the frozen scorer; regression bet sheet `tests/fixtures/betsheets/NFL_20261110_072712CST_betsheet.csv` (144 rows: 1 PRODUCTION_QUALIFIED, 1 RESEARCH_POSITIVE_EV, 100 PASS, 42 NOT_EVALUATED_BY_MODEL).

## Required model audit

Audit original spread, moneyline and totals regime mapping, calibration, REV2-CAL replay, source feature timing and wager eligibility.

Preserve market-specific champion/challenger/research distinctions, immutable release IDs and original-at-quote authorization. Record source cutoff, scoring/quote UTC times, production gates, holdout evidence, calibrated P(win/push/loss), EV, Full Kelly and Adjusted Kelly. A missing model artifact must be labelled blocked, not silently reimplemented as an unapproved authority.

## Bet-sheet acceptance criteria

Use `docs/betsheets/shared-contract.md`. Show all event/market/side rows (positive/zero/negative, Pass, Lean, blocked/unscorable), chronological order, original tier, model release, actual quoted price, EV, Kelly variants and reason when a figure is unavailable. Where an outside baseline or sport-specific diagnostic is used, document the real source, refresh time, and comparison calculation.

## Before production promotion

- [ ] Name and hash frozen model release and inputs.
- [ ] Reproduce historical scoring with golden fixtures including negative EV and missing-data rows.
- [ ] Compare new outputs to original historical model output without rewriting recorded observations.
- [ ] Document version, tier/eligibility changes, new-versus-existing bet logic, and tests.
- [ ] Update `ROADMAP.md`, `docs/model-authority.md`, and this file in the same PR.
