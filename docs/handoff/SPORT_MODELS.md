# Five-sport model research and development briefs

**Read `docs/model-authority.md` and the registry before interpreting this document.** An item marked [PRIOR-DISCUSSION] is user research intent and does not supersede a frozen release or grant wagering authority. Each model's exact code, coefficients, artifacts and cutoffs remain in its respective repository files, not in this prose.

## Executive matrix

| Sport | Checked-in candidate/role | Historical artifact status / key unresolved task |
|---|---|---|
| NFL | `NFL_REV2_CAL_20261024` calibrated champion; `NFL_W8_FULL_SLOPE_20261026` challenger | Config/scorer in frozen ZIP, archived source in `legacy_models/nfl`; live feature/replay parity not certified |
| NCAAFB | `NCAAFB_SPREAD_PP_V2_20261028` provisional spread champion; frozen continuous V1 challenger; shared ML and totals components | Spread posterior inputs and current odds/feature artifacts incomplete; partial conditional/push limitations |
| NBA | `NBA_R4_V27_20261030` restored previous production scorer; R3 research challenger | R4 complete archived artifacts; current live feature-engine parity and chronology extension need certification; R3 artifacts missing |
| NHL | Three `NHL_*_DAY0_V1_20261025` individual-game scoring champions, with older research challengers | Model status is "Watch"; no wagering authorization; missing historical control files and challenger binaries |
| NCAABB | `NCAABB_V4_PROD_THROUGH2025` production candidate; V4 validation freeze; V5 prospective shadow | V4 files in repository; V5 freeze parameter JSON missing; outside T-Rank comparison not yet verified as executable |

## NFL

**[REPO-VERIFIED]** Registry seeds `NFL_REV2_CAL_20261024` as champion and `NFL_W8_FULL_SLOPE_20261026` as challenger. Frozen archive members include the scorer and champion configuration. `legacy_models/nfl/` includes `production_calibration.py`, `champion_context.py`, `segments.py`, `reconstruction.py` and `analyze.py`.

**[PRIOR-DISCUSSION]** Research emphasis: early-season previous-season SRS as appropriate; segment-level performance by home/away, prior-season form and schedule congestion; avoid changing calibration based solely on a tiny profitable stretch. Preserve ML/spread/total and original tier. Do not infer recent performance from the archived 2026-11-10 slate alone.

**[OPEN/VERIFY]** Find authoritative exact release input and frozen paired score fixtures, define true quote-to-feature cutoff, port scorer to generic API, test pregame parity and post-game chronology.

## NCAAFB

**[REPO-VERIFIED]** `legacy_models/ncaafb/authority.json` defines Week 8+ FBS-v-FBS spread partial-pooling V2, user-approved for provisional scoring 2026-10-28. Formula: `mu ~ Beta(25,25)`; group conditional `p_g | mu ~ Beta(50mu,50(1-mu))`. Eligibility: higher-slope underdog, |Z| >= 1.243 and offered-price EV positive. Groups: moderate [1.243,1.75), strong >=1.75; frozen reported probabilities 0.4987879548238005 moderate and 0.5844035053238725 strong, based on 45 decisive results (25W/20L). `B` provisional moderate, `B+` provisional strong, **no spread Tier A promotion**. Frozen continuous posterior is challenger, not silently blended.

`legacy_models/ncaafb/README.md` states four-checkpoint slope, expanding Week8+ Z denominator, original FBS-v-FBS least-squares SRS and +2.5 nonneutral home adjustment. Only spread differs between configurations; the ML rule and PFPA Under research components are shared, **not independent forecasts**.

Shared ML rule: market anchor plus fixed +0.10 log-odds uplift and opponent/favorite SRS <10 gate. Exact historical calibration population unresolved. Shared total: PFPA Under research Lean; zero normal allocation. Whole-line push probabilities were not validated; some recorded model P/EV/Kelly values are *conditional on decisive outcomes* and must be labelled accordingly. Adjusted Kelly, where justified, is posterior-aware *joint* optimization, not Full Kelly multiplied by an invented second haircut.

**[OPEN/VERIFY]** Missing posterior quadrature/input snapshots; current-game feature bridge; quote freshness; feature/push treatment. The authority file includes scenario bankroll/exposure from 2026-10; **never treat that as today's bankroll or placed bets**. Chat/project uploads (not yet proved in this repo) include corrected Week1 inputs, clean/staging datasets and 2023 schedules/odds candidates; see `MISSING_AND_UNCERTAIN.md`.

## NBA

**[REPO-VERIFIED]** `legacy_models/nba_r4/ACTIVE_RELEASE.json` restores previous production R4 as of 2026-10-30 using frozen V27 coefficients and prior feature implementation; R3 research challenger remains separate. Totals status: `RESTORED_PREVIOUS_UNDER_B`. No new probability promotion; newer calibration models shadow only. `legacy_models/nba_r4/RELEASE_HASHES.json` and source/binary evidence are present. `DEPENDENCE_MODEL.json` and portfolio experiments should not be mistaken for approved overall allocation.

**[PRIOR-DISCUSSION]** The research plan emphasizes exact live 2026-27 feature reconstruction (Elo, rolling margins, rest, B2B/3-in-4/4-in-6, offense/defense form); 2025-26 and 2026-27 chronology extension; tier B spread and B+ moneyline history must be measured instead of automatically set Pass. Compare champion and challenger at the identical book quote, retain missing-line scoring, and report Full and Adjusted Kelly. Optional outside forecast comparison: Dunks & Threes, with T-Rank for NCAA basketball; never invent values or confuse those with the in-repo model.

**[OPEN/VERIFY]** R4 is a documented historical production scorer, not yet an audited new generalized adapter. R3 source artifacts are missing according to registry. Old V27 feature parity for spread and ML was not independently certified. Check actual latest code and frozen outputs before implementing a research change.

## NHL

**[REPO-VERIFIED]** `legacy_models/nhl_day0/NHL_DAY0_PRODUCTION_AUTHORITY_2026_10_26.json` explicitly designates Day-0 versions for scoring individual totals, ML and puck line with historical broad-segment residuals and shrinkage k=200. It explicitly sets `wagering_authorized=false`, stake $0, and model health "Watch". Former V15/ML V3/PL V1 champion role labels were superseded; older forecasts/artifacts remain untouched. Exact paired pregame book odds, line signs and push-aware totals are required. `Adjusted Kelly` for these Day-0 models is N/A until separately validated; do not display false 0% or pretend it was computed.

**[PRIOR-DISCUSSION]** Additional work on Grand Salami totals and spread, game outcomes under official-time settlement, P&L by model/segment, and user-requested ties/pushes refund rule. Grand Salami is a **distinct market**; do not represent its authority as certified by the registered individual-game Day-0 models. Older authorities mentioned in research include NHL V14, Grand Salami totals V1 and Grand Salami spread Day-0 V1; retrieve exact artifacts before invoking them.

**[OPEN/VERIFY]** Missing segment controls and some challengers, actual Grand Salami offered book lines and timing, game eligibility and settlement policy on a specific market; no implied positive-EV production wagers from research-only edges.

## NCAABB

**[REPO-VERIFIED]** Registry `NCAABB_V4_PROD_THROUGH2025` includes production-candidate model binary and scripts, while `NCAABB_V4_VALIDATION_FROZEN2024` is for retrospective 2025 validation; do not swap their roles. `NCAABB_V5_PROSPECTIVE_SHADOW` is partial: shadow script exists but `NCAABB_V5_FREEZE_PARAMETERS.json` is missing. Its docstring explicitly says no wagers and no Adjusted Kelly implementation.

**[PRIOR-DISCUSSION]** Compare champion/challenger, historical betting performance by period and segment, and bring T-Rank as an *outside baseline* before purchasing KenPom. Include its sourced probability/forecast and EV when available, not as an assumed registered champion. Store all scored Pass/Lean/negative-EV records, chronological order, original tiers and distinct research signals.

**[OPEN/VERIFY]** Latest Nov-2026 authoritative NCAABB version and V5 freeze, outside T-Rank daily data, missing line/odds values, prospectively frozen comparison dataset, validated adjusted-sizing implementation.

## Model evaluation standards across sports

- Evaluation in ChatGPT: define exact eligible population, time boundaries, market side/odds, calibration (Brier/log loss/reliability), EV, realized paper performance, holdout size, confidence/uncertainty, and exposure/portfolio effects.
- Distinguish **point-in-time pregame** score from later retrospective reconstruction; never leak final score, postgame Elo/SRS or later available odds into past forecasts.
- Against a baseline, compare **same games / markets / quotes**, not disconnected samples. Keep outcome distributions win/push/loss when a push is possible.
- Positive historic ROI in small samples is evidence to investigate, not automatic proof of sustainable edge or grounds to authorize new stakes. User preference to retain positive historic tier segments should be evaluated explicitly and not silently discarded.
- Release/version comparison must attribute specific source paths and hash, train/validation windows, statuses, approval, score scope and failure cases.
