# Claude Code — executable model transfer runbook

This document operationalizes `MODEL_TRANSFER_AUDIT_2026-11-24.md`. The **research/approval role stays with ChatGPT**; Claude Code implements frozen specs, reproducible scoring, tests, exports and UI. Do not refit a frozen release as part of the transfer.

## Step 0 — detect working state and read authority

```bash
git fetch --all --prune
git checkout main
git pull --ff-only
git status --short
python -m unittest discover -s tests -v
python -m gambling audit
python -m gambling models list
python -m gambling models verify
python -m gambling models attribution
```

Report actual commands and results. A missing local frozen ZIP or database environment is a blocker, not evidence of model failure. Review `CLAUDE.md`, `docs/engineering-policy.md`, `docs/handoff/README.md`, `docs/handoff/MODEL_TRANSFER_AUDIT_2026-11-24.md`, and `docs/handoff/LOCAL_INPUT_INVENTORY_2026-11-24.md`.

## Step 1 — inventory each release in machine-readable terms

Create a **new research diagnostic report** (not migration that edits old rows), with at least:

`sport,release_id,market,role,registry_wager_authorized,evidence_level,artifact_status,all_artifact_paths_present,sha256_verified,required_external_input_paths,dependencies_available,scorer_runnable,feature_ready,quote_ready,parity_verified,parity_fixture_id,missing_reason,reference_sha`.

All boolean fields have separate status `UNKNOWN` until measured. Do not use `false` to mean “not checked”. For NCAABB authority marked `INFERRED`, label the uncertainty explicitly.

## Step 2 — recover exact freeze artifacts (sport branches)

- **NBA:** run R4 hash verification and frozen `nba.py score` in an isolated environment; pin quote and history SHA; verify NBA R3 is unavailable unless artifact source is recovered.
- **NCAABB:** invoke V4 with explicit correct `--model` file in a disposable output dir; adapt folder path without altering hashed legacy script; require V5 freeze JSON and original extracted V4 layout before a V5 shadow replay.
- **NFL:** extract registered ZIP members; compare SHA256/size with `0005_seed_model_registry.sql`; reproduce REV2-CAL and W8 challenger with same quote cohort. `legacy_models/nfl/core.py` is REV1 tools and not a drop-in replacement.
- **NCAAFB:** obtain 2026 `inputs/evidence/`, `inputs/finals_week8/9`, `inputs/prior_features.csv`, `inputs/quoted_lines.csv`, `inputs/posterior_quadrature.csv` and frozen `inputs/authority.json` or prove equivalent source with hash and parity. Use upload inventory only for separate staged history research.
- **NHL:** recover controls CSV, schedule and snapshot for Day-0, plus original Grand Salami release evidence. Keep individual-game and Grand Salami distinct; Day-0 is scoreboard-only with no authorized wager.

## Step 3 — implement one new model adapter at a time

Port from validated frozen code into `gambling/models/<sport>/`; implement `gambling.models.base.Adapter.score()`. The adapter returns exactly one coherent win/loss/push or blocked row per input market-side quote; tier, EV and betting authorization remain in shared scoring. Do not rewrite `legacy_models/` or historical registry data. Changed calibration = new version, not in-place edits.

## Step 4 — bet-sheet and scoring acceptance

Every sport's chronological workbook includes **all** scored rows, including negative/zero EV, Pass, Lean, research and explicit UNSCORED/BLOCKED. Keep champion and challenger side by side on *identical* quote times, source and price, with original tier, model role, EV, Full Kelly and Adjusted Kelly or missing reason. Include new vs existing. Push/ties refund under the **applicable** Bovada market rules.

See `docs/handoff/BETSHEETS.md`, `docs/betsheets/shared-contract.md`, and `docs/handoff/RESEARCH_TO_DEVELOPMENT.md`.

## Step 5 — hand results back to ChatGPT

Every PR must include the before/after rows, fixture IDs, full SHA hashes, parity counts, unresolved inputs, release authorization, tests, affected docs, and a reproducibility recipe. Write `docs/research/implementations/YYYY-MM-DD-<sport>-<topic>.md` with the template in `docs/handoff/RESEARCH_TO_DEVELOPMENT.md`.

ChatGPT evaluates forecast merit and refinements. Claude should not promote research-only versions, silently reclassify historical tier P&L, or use observed betting histories as a basis to invent current bankroll/exposure.

## Security / data handling

Do **not** commit private betting-account exports, runtime SQLite DB, browsers/sessions or sensitive source CSVs. `.local_archive/` is Git-ignored but not remotely created or backed up by Git. Stage user-provided NCAAFB data outside Git and retain exact checksums. The user may manually copy those assets from ChatGPT into Claude's environment when they choose.
