# NBA — model and bet-sheet authority

**Archived source:** `legacy_models/nba_r4/`  
**Working scope:** NBA V27/R4 production candidate, earlier R3 research challenger  
**Current certification:** frozen-replay adapter `gambling/models/nba/r4_legacy.py` reproduces the archived Nov 12 R4 output exactly (golden `NBA_R4_20261112`). It covers that archived board; live use needs the items below.

## Frozen R4 adapter (2026-11-25)

| Release | Registry | On the sheet |
|---|---|---|
| `NBA_R4_V27_20261030` (scorer label `NBA_PREVIOUS_PRODUCTION_R4_20261030`) | CHAMPION, wager-authorized in all three markets | Scored by the unchanged `legacy_models/nba_r4/nba.py score`, which verifies its own `RELEASE_HASHES.json` |
| `NBA_R3_20261029` | CHALLENGER, `ARTIFACTS_MISSING` | `BLOCKED` on every quote, so the gap is visible (not reconstructed) |

- **Sides each rule evaluates:**
  - Spread: the margin-gap side; B if it is the underdog and the gap is ≥ 5.
  - Moneyline: the larger-residual side; B+ if market p < 0.30 and the residual is 3–6 pp; Lean at 6–8 pp.
  - Total: Under only; B if the predicted total is ≤ market − 10.
  - The other side is `NOT_EVALUATED_BY_MODEL`.
- **Probability basis:** Spread B (0.5459) and OU B (0.5852) are Beta posterior means on wins/losses, i.e. P(win | decisive). Half-point lines are unconditional; integer lines (Toronto +9.0 on Nov 12) are `CONDITIONAL_SCORED` with push UNKNOWN. ML B+ is logistic(logit(no-vig) + 0.359), on a two-way moneyline.
- **Actions:** B or B+ with `QUALIFIED_POSITIVE_EV` → QUALIFIED; with `NO_POSITIVE_EV` → PASS; Lean → LEAN; Pass → PASS.
- **Adjusted Kelly:** the scorer's joint posterior-predictive expected-log portfolio stake (`portfolio_kelly.py` + `DEPENDENCE_MODEL.json`), passed through unchanged. It is labelled `LEGACY_NOT_PORTFOLIO_CERTIFIED`, because the dependence model is "SHADOW_ADJUSTED_KELLY; not validated joint calibration". When the scorer reports it unavailable (any Total in the active set), it is null with that reason.
- **Quotes:** `quotes_json_from_capture` rebuilds the scorer's 12-field JSON from the Nov 12 capture `quotes.csv` (batch `20261112T134056Z_68f7ec`, stored once in the NHL fixture) using the archived builder's rules. It matches the archived input byte-for-byte, so every row carries the capture's Bovada price id and timestamp. The scorer's own label `USER_BOVADA_UNTIMESTAMPED` is kept in diagnostics.
- **Nov 12 sheet:** 48 rows (4 games × 6 sides × R4/R3). Two rows are PRODUCTION_QUALIFIED: Washington +10.5 and Toronto +9.0 (Spread B, EV +0.042, Full Kelly 0.0464, portfolio Adjusted Kelly 0.0463 each). Ten are PASS; R3 is BLOCKED on all 24 of its rows. Regression sheet: `tests/fixtures/betsheets/NBA_R4_20261112_betsheet.csv` (SHA-256 `495ed026…`).

**Results feed (2026-11-25):** `python -m gambling results fetch --sport NBA --date D` records ESPN finals. Then `python -m gambling results nba-history --base <history.csv> --through <slate−1> --out <new.csv>` writes the base history plus the new finals to a new file, which the unchanged scorer can read with `--history`.
- **Unknown names:** the feed stops on team names the base never used, unless `--allow-new-names` is passed.
- **Checked against the database:** the database's 15 NBA finals for Nov 8–9 match the manual history.
- **Reconciliation (2026-11-25):** see `docs/reconciliation/2026-11-25-recorded-history.md`. The Nov 9–11 runs had the Nov 8 Pelicans @ Clippers final under "LA Clippers"; the frozen history renamed it, so the archived Nov 12 forecast was scored on a different history than those runs.
- **Data-quality finding (not changed):** the frozen history uses both "Los Angeles Clippers" (2018 through 2026-11-08) and "LA Clippers" (2026-10-28 onward, 6 rows), so the V27 features treat them as two teams. Any change belongs to ChatGPT research and a new release; this frozen release is not altered.

**Before live use:**
- An automated completed-results feed. (Done: ESPN collector, above; first live fetch pending on the user PC.) The scorer rejects history more than 7 days stale, and the Nov 6–11 finals were transcribed manually (PR #4 decision 5).
- A decision to either recover the R3 artifacts or retire R3.
- The Oct 29 pipeline remains unresolved (research Q1).
- The user database has R4/R3 batches for Nov 6–11 but not Nov 12; reconciling them is a follow-up.

## Required model audit

Retain release artifact hashes; verify V27 live feature-engine parity, champion/challenger tiers, ML/spread/totals, outside baseline provenance and full/adjusted Kelly.

Preserve market-specific champion/challenger/research distinctions, immutable release IDs and original-at-quote authorization. Record source cutoff, scoring/quote UTC times, production gates, holdout evidence, calibrated P(win/push/loss), EV, Full Kelly and Adjusted Kelly. A missing model artifact must be labelled blocked, not silently reimplemented as an unapproved authority.

## Bet-sheet acceptance criteria

Use `docs/betsheets/shared-contract.md`. Show all event/market/side rows (positive/zero/negative, Pass, Lean, blocked/unscorable), chronological order, original tier, model release, actual quoted price, EV, Kelly variants and reason when a figure is unavailable. Where an outside baseline or sport-specific diagnostic is used, document the real source, refresh time, and comparison calculation.

## Before production promotion

- [ ] Name and hash frozen model release and inputs.
- [ ] Reproduce historical scoring with golden fixtures including negative EV and missing-data rows.
- [ ] Compare new outputs to original historical model output without rewriting recorded observations.
- [ ] Document version, tier/eligibility changes, new-versus-existing bet logic, and tests.
- [ ] Update `ROADMAP.md`, `docs/model-authority.md`, and this file in the same PR.
