# Five-sport authoritative model transfer audit
**Audit date:** 2026-11-24, US Central  
**GitHub baseline:** `main` at `597519e94f2662eaf0420bf64d2152c1755497d5`  
**Scope:** read-only review of named GitHub source files, the checked-in model registry and filenames, and the metadata of six user-provided NCAAFB files available to the ChatGPT research workspace. No model refit, score rerun, artifact copying into Git, bankroll change, or promotion was performed.

## Executive verdict

Claude can begin **engineering** against the existing code and historical registry today, but cannot yet certify a generalized daily scoring adapter for any of the five sports solely from the checked-in files. The repo contains 18 registered historical releases: **3 COMPLETE**, **2 IN_FROZEN_ARCHIVE**, **8 PARTIAL**, and **5 ARTIFACTS_MISSING**. These are `artifact_status` classifications recorded by `gambling/db/migrations/0005_seed_model_registry.sql`, not independent test results or claims about today's current model.

The original November 11 frozen history, scoring authority and model snapshots remain the comparison baseline. **Do not silently replace them** with conversational summaries, historical backtests recomputed after games, or user-uploaded draft datasets.

## Release classification and declared authority

The table below is derived from `0005_seed_model_registry.sql`, `legacy_models/nba_r4/ACTIVE_RELEASE.json`, `legacy_models/ncaafb/authority.json`, and `legacy_models/nhl_day0/NHL_DAY0_PRODUCTION_AUTHORITY_2026_10_26.json`. “Authorized” is a **historical registry flag**, not an instruction to place bets or proof a functioning live pipeline exists. The NCAABB champion assignment was recorded with INFERRED evidence and needs independent source confirmation.

| Sport | Release | Recorded role / wagering authorization | Artifacts |
|---|---|---|---|
| NBA | `NBA_R4_V27_20261030` | Champion / yes | COMPLETE |
| NBA | `NBA_R3_20261029` | Challenger / no | ARTIFACTS_MISSING |
| NCAABB | `NCAABB_V4_PROD_THROUGH2025` | Champion / yes (role evidence INFERRED) | COMPLETE |
| NCAABB | `NCAABB_V4_VALIDATION_FROZEN2024` | Research / no | COMPLETE |
| NCAABB | `NCAABB_V5_PROSPECTIVE_SHADOW` | Shadow / no | PARTIAL |
| NCAAFB | `NCAAFB_SPREAD_PP_V2_20261028` | Champion / yes, provisional | PARTIAL |
| NCAAFB | `NCAAFB_SPREAD_CONTINUOUS_V1_20261023` | Challenger / no | PARTIAL |
| NCAAFB | `NCAAFB_ML_W8PLUS_RULE` | Shared champion component / yes | PARTIAL |
| NCAAFB | `NCAAFB_OU_RESEARCH` | Research component / no | PARTIAL |
| NFL | `NFL_REV2_CAL_20261024` | Champion / yes | IN_FROZEN_ARCHIVE |
| NFL | `NFL_W8_FULL_SLOPE_20261026` | Challenger / no | IN_FROZEN_ARCHIVE |
| NHL | `NHL_ML_DAY0_V1_20261025` | Scoring champion / **no** | PARTIAL |
| NHL | `NHL_PL_DAY0_V1_20261025` | Scoring champion / **no** | PARTIAL |
| NHL | `NHL_OU_DAY0_V1_20261025` | Scoring champion / **no** | PARTIAL |
| NHL | `NHL_ML_V3` | Challenger / no | ARTIFACTS_MISSING |
| NHL | `NHL_PL_V1` | Challenger / no | ARTIFACTS_MISSING |
| NHL | `NHL_V15_CONDITIONAL_COUNT` | Challenger / no | ARTIFACTS_MISSING |
| NHL | `NHL_DAY0_APPROX_FROM_ROUNDED_EV` | Research approximation / no | ARTIFACTS_MISSING |

## NBA — archived files mostly present, current features not certified

**Observed sources:** `legacy_models/nba_r4/ACTIVE_RELEASE.json`, `RELEASE_HASHES.json`, `nba.py`, `scoring_core.py`, `portfolio_kelly.py`, `data/v27_coefficients.json`, `data/history.csv`, `data/previous_historical_master.csv`.

- Frozen R4/V27 previous deployed scorer restored Oct 30; totals prior UNDER B restored. Three markets covered; R3 challenger retained but R3 source/parameters not bundled.
- Nine expected release files are enumerated in `RELEASE_HASHES.json`. Presence was checked against GitHub tree; **SHA256 verification was not independently executed in this research audit**.
- `nba.py` uses `--quotes`, `--out`, optional `--history`; verifies release hashes on execution, reads original history, creates output manifest and will refuse to overwrite output directory. It imports pandas/numpy and calls scipy-based scoring, so legacy adapter dependencies must be installed deliberately; the lightweight root package's standard-library-only quickstart does not cover these legacy libraries.
- `ACTIVE_RELEASE.json` indicates `history_last_date=2026-10-29`; the 2025-26/2026-27 continuation and exact feature parity (Elo, margins, rest, B2B, 3-in-4/4-in-6, offense/defense) are **not** certified as a generalized live engine.
- `DEPENDENCE_MODEL.json` is a shadow / conditional portfolio dependence evaluation, not blanket approval of portfolio-sized wagers.

**Claude blocker/gate:** preserve original R4 outputs and hashes; extract paired quotes/features/golden market-side rows; certify a new chronological live feature builder before adopting R4 in `gambling/models/nba/`; keep R3 unavailable until exact frozen artifacts are recovered. Outside Dunks & Threes comparison is a separate research feature requiring verified source/time-aligned data.

## NCAABB — production-candidate binary present; wiring bug and shadow dependency

**Observed sources:** `legacy_models/ncaabb_v4/score_ncaabb_v4.py`, `ncaabb_models.py`, `ncaabb_matchup.py`, the two V4 joblib binaries; `legacy_models/ncaabb_v5/score_ncaabb_v5_shadow.py`.

- V4 production-candidate and V4 frozen validation binaries are present. Their use is role-specific; never swap retrospective validation binary for the future scoring candidate.
- **Concrete porting issue:** `score_ncaabb_v4.py` defaults `--model` to `Path(__file__).resolve().parents[1] / "models/NCAABB_V4_PRODUCTION_CANDIDATE.joblib"`. From the current `legacy_models/ncaabb_v4/` location this resolves to `legacy_models/models/...`, which does **not** exist in the inspected tree. An explicit correct `--model` path can be passed for a test; fix in a *new adapter*, not by mutating hashed legacy sources.
- V5 shadow script loads `NCAABB_V5_FREEZE_PARAMETERS.json` at module load, absent from GitHub tree; it also expects an extracted `--v4-root` with `code/` and `models/` subfolders, not the reorganized repository layout. Its docstring explicitly says no V5 Adjusted Kelly implementation, and no actual wagering.
- `NCAABB_V4_PROD_THROUGH2025` is set as champion with wagering flag 1 in migration but evidence_level **INFERRED**, not independently proven source authority. This must be called out in release audit.
- T-Rank as outside challenger is a prior research requirement, not a verified current adapter or registered champion. KenPom is deferred.

**Claude blocker/gate:** build a new V4 adapter with an explicit frozen binary path and normalized pregame inputs; verify output parity; recover V5 frozen parameters before attempting shadow replays, and keep shadow stakes disabled.

## NFL — frozen-archive extraction required

**Observed sources:** `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip`; migration `0005`; `legacy_models/nfl/{core,production_calibration,champion_context,segments,reconstruction,analyze}.py`.

- Champion `NFL_REV2_CAL_20261024` and challenger `NFL_W8_FULL_SLOPE_20261026` are marked `IN_FROZEN_ARCHIVE`. `0005` lists exact ZIP members for champion config/scorer/metadata and records SHA256/length for each.
- Root `legacy_models/nfl/core.py` calls itself `REV1-audited-tools-2026-10-24`: **do not substitute it for** the registered REV2-CAL scorer without checking frozen model identity.
- The ZIP is present in the GitHub tree. **This audit did not extract or independently rehash its binary members**, so “in archive” remains a declared artifact state, not an execution check.

**Claude blocker/gate:** extract in a controlled local environment, compare SHA256 to registry, reproduce the frozen score cohort, then wrap the actual REV2-CAL/reconstructed challenger behind `score(game, quotes, features)`, preserving roles and tiers.

## NCAAFB — authority exists; original reproduction inputs absent

**Observed sources:** `legacy_models/ncaafb/authority.json`, `README.md`, `build_features.py`, `score_both.py`.

- Oct 28 provisional Week8+ spread partial-pooling V2 champion vs original Oct23 continuous posterior challenger. The components for ML and total are shared and must not be counted as independent forecasts.
- Spread eligibility in authority: FBS-v-FBS, higher-slope underdog, |Z| >= 1.243, offered-price EV positive; provisional groups B (moderate), B+ (strong), no A spread. The calibration note discloses research limitations; conditional decisive-outcome P does **not** imply validated whole-line push-aware P/EV.
- **Direct source dependency audit:** `build_features.py` requires `inputs/evidence/replay.py`, `inputs/evidence/schedule2026.csv.gz`, `inputs/finals_week8.csv`, `inputs/finals_week9.csv`, `inputs/prior_features.csv`; `score_both.py` requires `inputs/quoted_lines.csv`, `inputs/authority.json`, `inputs/posterior_quadrature.csv`, plus generated `results/features_weeks8_10.csv`. These files are not in the GitHub tree. Note also that `authority.json` exists at the archive directory root, whereas the script references a distinct `inputs/authority.json` path.
- Output from the Nov2 analysis names 62 games/186 markets, but its all-rows output and original posterior input files are missing from the inspected GitHub tree.
- **Separate user-supplied data** were inspected (see `LOCAL_INPUT_INVENTORY_2026-11-24.md`), including 2026 Week1, 2018-25 clean/staging, and 2023 schedules/odds. These do **not** automatically supply the missing frozen 2026 Weeks8-10 files or prove identical historical calculations.

**Claude blocker/gate:** retrieve exact frozen package/missing paths and verify hash/parity. Independently reconcile the user's 2023 data; preserve provenance and duplicated rows pending physical-game ID deduplication. Never replace missing Week8+ slope features with prior season SRS in a manner that changes the release.

## NHL — score authority is not wagering authority; Grand Salami separate

**Observed sources:** `legacy_models/nhl_day0/NHL_DAY0_PRODUCTION_AUTHORITY_2026_10_26.json`, `day0_production.py`, registry `0005`.

- Individual-game ML, puck line, and totals Day-0 champions are designated for **scoreboard authority**; `wagering_authorized=false` and stake USD 0, model health Watch. This applies even when a displayed calculated EV is positive.
- `day0_production.py` explicitly requires `--controls`, `--schedule`, `--snapshot`, `--output`; the source historic control/segment file and several older challengers are missing in the inspected tree. It reports an unvalidated postprocessor; no automatic approval.
- Prior Grand Salami totals and spread research was expressly preserved in the NHL authority file, but **not** equivalent to the Day-0 individual-game release and not a verified runnable current Grand Salami engine.
- Exact signed puck line, paired pregame odds, discrete-total push and market-specific official-time game inclusion are required. Adjusted Kelly for Day-0 is **N/A** until validated, not 0%.

**Claude blocker/gate:** recover source controls, source-specific historical rules and frozen predictions; create separate Grand Salami module/release registry only when actual evidence permits. Preserve the user-requested Bovada ties/push refund default subject to per-market official rules.

## Cross-cutting engineering and scientific gates

1. **Do not equate file presence with executable package**: verify release hashes, environment dependencies, missing paths, CLI behavior and sample outputs. Reorganization only created empty sport folders.
2. The output contract is `gambling/models/base.py`: for every quoted side return a scored win/loss/push row **or** explicit UNSCORED/BLOCKED with reason. Tier, EV, Kelly and original authorization come later in shared logic.
3. Replay against same original odds/quote as-of and model input cutoff; do not leak final score, later odds or after-the-fact calibrations into frozen pregame predictions.
4. Account P&L vs hypothetical model P&L; original tier vs retrospective tier; research vs production roles; and model scoring vs wagering authorization must be separate immutable fields.
5. Research artifacts and outside model baselines must carry exact source, timestamp, immutable hash and release ID. Missing artifacts stay blocked; do not "reconstruct" as if identical without parity.
6. Run `python -m gambling models verify`, `python -m gambling models attribution`, `python -m gambling audit`, and `python -m unittest discover -s tests -v` in Claude's full checkout and record real output. These tests were **not rerun** during this read-only ChatGPT audit. CI was previously green for core audit; that is not five-sport live-model parity.

## Suggested development order (engineering readiness, not research ranking)

1. **NBA R4** — check 9 hashes and source/test fixtures; current live feature chronology/parity is the hard gate.
2. **NCAABB V4** — fix path/layout in a new adapter and freeze golden forecasts; V5 stays shadow blocked until parameters recovered.
3. **NFL REV2-CAL** — extract/rehash frozen members, identify actual runner before reimplementation.
4. **NCAAFB** — retrieve Oct frozen inputs, reconcile separately uploaded clean/staging data without promoting it.
5. **NHL Day-0** — recover segment controls and quote snapshots; Grand Salami as separate research branch.

This is a **dependency-oriented initial sequence**, not a claim that the later sports are less valuable. Multiple sports can be audited in parallel; a development merge may proceed only when the specific release's gate passes.

## Handoff acceptance checklist

- [ ] Each release's required file paths exist and SHA256 values match a frozen authority.
- [ ] Separate `scorer_runnable`, `feature_ready`, `quote_ready`, `parity_verified`, `research_status`, `wager_authorized` flags in engineering output.
- [ ] At least one archived cohort reproduced market-side P(win/loss/push), quoted price, tier, EV, Full Kelly, Adjusted Kelly or missing reason, and original authorization exactly.
- [ ] Every game/market/side row including Pass, negative EV and blocked is retained in chronological bet-sheet export.
- [ ] Outside comparisons T-Rank/Dunks & Threes carry provenance; no source = not available.
- [ ] Missing NCAAFB inputs, V5 freeze, NHL controls and R3 challenger artifacts stay explicit outstanding issues.
- [ ] Claude implementation PR includes results/evidence report and docs updated; ChatGPT evaluates independent model performance before a new release is proposed for promotion.

## Related documentation

`docs/handoff/README.md`, `SPORT_MODELS.md`, `MISSING_AND_UNCERTAIN.md`, `BETSHEETS.md`, `RESEARCH_TO_DEVELOPMENT.md`, `docs/model-authority.md`, `ROADMAP.md`.
