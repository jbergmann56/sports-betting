# NFL — model and bet-sheet authority

**Archived source:** `legacy_models/nfl/`  
**Working scope:** NFL calibrated champion/segments and challengers  
**Current certification:** frozen-replay adapter `gambling/models/nfl/rev2_legacy.py` (2026-11-25) reproduces the archived Nov 10 board exactly. The daily pipeline below adds the schedule source, the capture converter and a week driver.

## Daily pipeline (2026-11-28, `UNVALIDATED_GENERALIZED_WRAPPER`)

`python -m gambling nfl-schedule` then `python -m gambling daily NFL --date D [--capture …]` (`gambling/pipeline/nfl.py`, `gambling/models/nfl/live.py`).
- **Schedule/results source (resolved):** the frozen `games_snapshot.csv` is the nflverse `games.csv` (`https://github.com/nflverse/nfldata/raw/master/data/games.csv`). Same 46 columns; all 7,239 frozen rows agree on teams, dates, weeks and scores with the nflverse file of 2026-11-28 (the frozen copy writes scores as `17.0`). `nfl-schedule` downloads it to `data/nfl/nflverse_games.csv` and keeps a timestamped copy in `data/nfl/archive/`.
- **Board converter:** capture quotes → `board.json` rows with nflverse team codes. The archived Nov 10 raw payload converts to exactly the archived `board.json` (same 12 rows, same order, same 2 skipped events).
- **Week driver:** the frozen `score.py` hard-codes Week 10. The driver is that file with only its Week-10 literals replaced (`WEEK_REPLACEMENTS`: feature week, calibration week, cut-off = first gameday of the week, prior-week completeness); for Week 10 the generated text is byte-identical to the frozen file. Model files are the frozen ones. The REV2 calibration itself distinguishes only weeks 1–7 and 8+.
- **Guards:** all board games must be one regular-season week; the run is BLOCKED unless every game of the prior week is final in the schedule file. Events without six offered pregame sides are UNSCORED rows.
- **Validation:** daily runs for Nov 12, 15 and 16 on the Nov 10 capture reproduce all 36 archived Week-10 rows (within 1e-12; the archived numbers differ from any re-execution by ≤ 3.6e-14), with the frozen snapshot and with the current nflverse file alike (`tests/test_pipeline_nfl.py`).
- **Not yet:** dual-run/validation (M3/M4); playoffs (`game_type` other than REG) are out of scope of the frozen release.

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
