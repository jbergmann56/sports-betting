# Five-sport model transfer readiness — executed parity report

**Date:** 2026-11-24 (US Central) · **Author:** Claude Code (development role)
**Baseline:** `main` @ `734d44c` (includes `MODEL_TRANSFER_AUDIT_2026-11-24.md`, `LOCAL_INPUT_INVENTORY_2026-11-24.md`, `CLAUDE_MODEL_TRANSFER_RUNBOOK.md`)
**Machine-readable companion:** `2026-11-24-release-readiness-inventory.csv` (runbook Step 1 schema, one row per release)
**Promotion / wager authorization:** **none.** No model was refit, recalibrated, re-tiered or promoted. No registry row, `legacy_models/` byte or frozen archive member was modified. Every replay ran the unchanged archived scorer in a temporary directory and compared its output to the archived output.

This report executes the checks that the ChatGPT-side audit (`MODEL_TRANSFER_AUDIT_2026-11-24.md`) recorded as *not run*, and closes or narrows several of its open items.

---

## 1. Commands and results (runbook Step 0)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 58 tests, OK |
| `python -m gambling audit` | integrity `ok`, 0 FK errors; 28 batches / 1,156 events / 6,936 quotes / 10,173 scores / 148 settlements |
| `python -m gambling replay --date 2026-11-11` | 41 games; 269 PASS, 11 PRODUCTION_QUALIFIED, 9 RESEARCH_POSITIVE_EV |
| `python -m gambling models verify` | `all_verified: true` — 13 releases hash-verified (including all 7 NFL frozen-ZIP members per release), 5 with no registered artifacts |
| `python -m gambling models attribution` | 10,173 scores attributed (9,362 DOCUMENTED, 648 USER_CONFIRMED, 163 INFERRED), 0 unresolved labels; 9,315 distinct predictions after the 858 NCAAFB shared-component copies collapse |

Environment: Python 3.13, pandas 3.x, numpy 2.5, scipy, scikit-learn 1.9.1 (default) and an isolated scikit-learn **1.8.0** environment for NCAABB V4 (see §3.3).

## 2. Executed parity summary

Comparison rule: identical shape and columns; numeric columns equal within 1e-9 with identical NaN positions; string columns equal. Run-time timestamp columns excluded where noted.

| Sport | Fixture ID | Scorer (all byte-identical to repo `legacy_models/`) | Inputs | Result |
|---|---|---|---|---|
| NFL | `NFL_20261110_072712CST` | Frozen-ZIP `score.py` + `model/src/*` (src files identical to `legacy_models/nfl/*`) | All inside the repo's frozen ZIP | **IDENTICAL** — bet sheet 36×27, side inputs 72×22, team features 32×16; scorer self-checks true |
| NBA | `NBA_R4_20261112` | `legacy_models/nba_r4/nba.py` | Package history through 2026-11-11 (`29fb3330…`), Nov 12 capture quotes (`e26bb328…`) | **IDENTICAL** — 12×34 forecasts (excl. `Frozen_UTC`) |
| NBA | `NBA_R4_20261029_REFERENCE` | same | `oct29_quotes.json`, `history.csv` cut to `< 2026-10-29` | **NOT MATCHING** `evidence/repaired_oct29_reference.csv`: 2 spread selections, home margin up to 1.78 pts, structural win P up to 0.046. The reference is labelled `RECOVERED_FEATURE_RULES_CORRECTED_HISTORY_FROZEN_COEFFICIENTS` (different pipeline). Research decision required (Q1). |
| NCAAFB | `NCAAFB_20261102` | `build_features.py`, `score_both.py`, `authority.json` | Package `NCAAFB/nov02_production_feature_rebuild/inputs/*` (hashes in CSV) | **IDENTICAL** — features 174×48, all-markets 186×38 (62 games); tier counts reproduce |
| NCAABB | `NCAABB_V4_20261101` | `ncaabb_models.py`, `ncaabb_matchup.py`, `score_ncaabb_v4.py`, `NCAABB_V4_PRODUCTION_CANDIDATE.joblib` | Package 2021–25 master (51.6 MB), 2026 schedule (29.6 MB), ESPN JSON, Bovada raw, restored capture time | **IDENTICAL** from raw sources — ratings 365×8, inputs 13×62, scored markets 35×60 (**requires scikit-learn 1.8.0**) |
| NHL | `NHL_DAY0_20261112` | `day0_production.py` + package `nhl_score_adapter_ORIGINAL.py` | Package `OBSERVED_PRICE_ALL_CONTROLS.csv` (`4b6119a0…`), Nov 12 capture quotes | **IDENTICAL** — 132 rows (11 games × 6 sides × champion/challenger); max abs diff 9e-17 on P/EV/Kelly; tiers and statuses equal. Features 66×15 identical. |

The *Feature Source & Reproducibility* package used above is the user-supplied file `GAMBLING_DAILY_FEATURE_SOURCE_REPRO_20261112.zip` (18,786,561 bytes, SHA-256 `77d7637777806501e8bf47b62003e7d48864d85bf0a4cd63ee5e23287f2ac46a`). It is **not** the set of six NCAAFB CSVs in `LOCAL_INPUT_INVENTORY_2026-11-24.md`; those remain staged research history only.

## 3. Readiness by sport

Readiness scale: **R-IN-REPO** reproducible from committed files only · **R-EXTERNAL** reproducible with pinned external inputs · **BLOCKED** artifacts missing · **NOT-SCORING** research/validation artifact.

### 3.1 NFL — R-IN-REPO (champion and challenger)

- **Artifacts:** champion config, frozen challenger models JSON, scorer and source all in the frozen ZIP; registry hashes verified. The ZIP's `model/src/core.py` ("REV1 primitives") is byte-identical to `legacy_models/nfl/core.py` and is what REV2-CAL executes — REV2-CAL = `score.py` + `champion_config_preserved.json` + `apply_calibration.py` over these primitives. The audit's caution not to substitute a different core is satisfied: there is only one.
- **Authority match:** REV2-CAL champion, W8 full-slope challenger labelled `RESEARCH - NOT PRODUCTION`. Matches registry.
- **Bet-sheet gaps:** one row per game-market (champion selection) with challenger merged, not six side rows; no start time column (must join quotes); calibrated P only for tiers A/B+ (Pass/Lean rows are evaluated without probability); Adjusted Kelly NaN with recorded reason "joint predictive distribution and existing exposure unavailable".
- **Live gaps:** `games_snapshot.csv` (schedule + results) source is not documented in-repo; a live results/schedule feed and a Bovada-capture → `board.json` converter are needed.

### 3.2 NBA — R-EXTERNAL (R4); R3 BLOCKED

- **Artifacts:** all 9 `RELEASE_HASHES.json` files present and verified. R4 reproduces the Nov 12 slate exactly with the package history through Nov 11.
- **Authority match:** R4 champion restored 2026-10-30; totals `RESTORED_PREVIOUS_UNDER_B`; probability promotion none. R3 challenger code/parameters absent everywhere supplied → challenger column cannot be produced; 198 archived R3 rows stay as recorded.
- **Bet-sheet gaps:** one selected side per market (3 rows/game); Pass rows carry `Full_Kelly = 0.0` / `Adjusted_Kelly = 0.0` rather than null + reason; Adjusted Kelly is computed by the portfolio optimizer only for qualifying non-total markets, otherwise `Adjusted_Kelly_Status` explains why.
- **Live gaps:** scorer refuses history older than 7 days or containing the slate date (correct point-in-time guard) → needs an automated finals collector. Nov 6–11 finals in the package history were manually transcribed (Q5). Oct 29 reference mismatch unresolved (Q1).

### 3.3 NCAABB — R-EXTERNAL (V4 production candidate); V5 BLOCKED

- **Artifacts:** V4 binary and code verified; full raw-source reproduction of Nov 1 succeeds.
- **New finding — environment pin:** the joblib binary was pickled with **scikit-learn 1.8.0**; scikit-learn 1.9.1 fails with `ModuleNotFoundError: No module named '_loss'`. A pinned model environment is a hard requirement.
- **Confirmed porting issue:** default `--model` path resolves to a nonexistent `legacy_models/models/…`; the package uses an extracted `v4/models/` layout. Fix in the new adapter, not in hashed legacy code.
- **Authority match:** champion role evidence is `INFERRED` (Q6). `NCAABB_V4_VALIDATION_FROZEN2024` is retrospective only — NOT-SCORING.
- **Bet-sheet gaps:** 2–3 selected-side rows per game; `adjusted_kelly_before_portfolio` = Full Kelly × `evidence_factor` (effective-N shrinkage). Policy forbids double-counting calibration shrinkage, so whether this is the authorized Adjusted Kelly needs a research ruling (Q2). Output also contains post-game fields (`result`, `realized_unit_net`) that must never feed pregame scoring.
- **V5 shadow:** `NCAABB_V5_FREEZE_PARAMETERS.json` absent from the repo and every supplied package → BLOCKED; 3,722 archived V5 rows stay as recorded.
- **Data size:** required inputs total ~81 MB (51.6 MB master, 29.6 MB schedule) — storage decision needed (B1).

### 3.4 NCAAFB — R-EXTERNAL (spread champion, challenger, shared ML/OU components)

- **Artifacts:** repo `score_both.py`, `build_features.py`, `authority.json` are byte-identical to the package; the script's `inputs/authority.json` has the same hash as the repo-root `authority.json`. All "missing" inputs listed in the ChatGPT audit exist in the package with the hashes in the inventory CSV, and reproduce Nov 2 exactly.
- **Authority match:** PP V2 champion (B / B+ provisional, no spread A), continuous V1 challenger, shared ML Tier A rule and research PFPA Under; components are not double-counted. Output carries `ProbabilityBasis` — spread P/EV/Kelly are conditional on a decisive result.
- **Bet-sheet gaps:** one selected side per market; Adjusted Kelly unavailable pending reconciled exposure; one ML gate (Charlotte) intentionally `Unscored: SRS gate`.
- **Live gaps:** builder is hard-coded to Weeks 8–10 (Week 11 roll-forward `build11.py` archived, not yet replayed); published-SRS gate needs a live source.

### 3.5 NHL — R-EXTERNAL (three Day-0 scoring champions); challengers BLOCKED

- **Artifacts:** `day0_production.py` byte-identical to package; the controls file (`--controls`) is external but was rebuilt exactly (20,470 rows) from the V13 package on 2026-11-12; the original score adapter is in the package, not the repo.
- **Authority match:** Day-0 ML/PL/OU are scoreboard champions with `wagering_authorized=false`, stake $0, health Watch; Adjusted Kelly N/A. Replay reproduces exactly that: research Lean / Pass only.
- **Bet-sheet fit:** best of the five — already emits all six sides per game, champion and challenger rows side by side, explicit `UNSCORED` for missing challengers.
- **Blocked:** ML V3, PL V1, V15 models absent (Nov 12 rows are market-anchor or `UNSCORED`); no Grand Salami artifacts of any kind — Grand Salami remains a separate future release.

## 4. Cross-sport contract gaps (engineering)

1. **Evaluated-without-probability rows** (NFL, NCAAFB, NBA Pass/Lean) cannot be represented by `ScoreRow` (`SCORED` requires P; `UNSCORED` means not evaluated).
2. **Probability basis** (NCAAFB conditional-on-decisive) has no field; `ScoreRow` forces an unconditional push probability.
3. **Six-side completeness:** four of five legacy scorers emit only the model's selected side. The bet sheet must add opposite-side rows from the quote board without inventing probabilities (Q3).
4. **Kelly null semantics** differ (NaN with reason vs 0.0); normalize in `gambling/scoring`, never in adapters.
5. **Chronology:** only NCAAFB (`KickoffCT`) and NHL (`start_utc`) carry start times; all others must join the capture's event start.
6. **Environment:** two dependency profiles exist (stdlib core; pinned `pandas/numpy/scipy/scikit-learn==1.8.0` model profile).

## 5. Prioritized development backlog

Each item: branch → deliverable → exit criterion. No item refits or promotes a model.

**P0 — evidence and reproducibility foundation**

| ID | Branch | Deliverable | Exit criterion |
|---|---|---|---|
| B1 | `feature/core-external-inputs` | Decide storage for external inputs (repo is public; ~19 MB package + ~81 MB NCAABB data). Commit a hash manifest `legacy_models/EXTERNAL_INPUTS.json` and an append-only migration registering them as `EXTERNAL_INPUT` artifacts; files live in Git LFS, a private release asset, or `GAMBLING_DATA_DIR` | `models verify` checks external inputs when present and reports `NOT_PRESENT` (not failure) when absent |
| B2 | `feature/core-model-env` | `requirements-models.txt` pinning the verified versions (scikit-learn 1.8.0 et al.); optional `[models]` extra | NCAABB V4 loads in CI model job |
| B3 | `feature/core-golden-replay` | `tests/golden/` runner + fixtures `NFL_20261110_072712CST` (runs in CI from repo), `NBA_R4_20261112`, `NCAAFB_20261102`, `NCAABB_V4_20261101`, `NHL_DAY0_20261112` (explicit `SKIP: external input absent` when inputs are not present — never a silent pass) | All five pass locally with inputs; NFL passes in CI |
| B4 | `feature/core-readiness-cli` | `python -m gambling models readiness` emitting the inventory schema from registry + checks | Output matches this report's CSV |

**P1 — shared scoring and bet-sheet core**

| ID | Branch | Deliverable | Exit criterion |
|---|---|---|---|
| B5 | `feature/core-scorerow-v2` | `ScoreRow` v2: `EVALUATED` status (tier/signal without P), `probability_basis`, side/selection/line, opposite-side rows | Contract tests; `docs/betsheets/shared-contract.md` updated |
| B6 | `feature/core-scoring` | `gambling/scoring`: push-aware EV and Full Kelly per `BETSHEETS.md`; Adjusted Kelly only as supplied by the release with algorithm ID, else null + reason; tier/authorization from registry status at quote time | Hand-checked fixtures; reproduces EV/Kelly of all five goldens |
| B7 | `feature/core-betsheet` | Consolidated writer (CSV + Excel): six sides per game, CT chronology, champion/challenger columns, original tier, new-vs-previous, null reasons | `BETSHEETS.md` acceptance tests on goldens |

**P2 — sport adapters (one PR each, on `sport/<sport>`)**

| Order | Sport | Why this order | Exit criterion |
|---|---|---|---|
| 1 | NFL | Only sport reproducible entirely in-repo → CI-enforceable parity | Adapter output = `NFL_20261110_072712CST` row-for-row |
| 2 | NHL | Simple stdlib scorer; already six-sided with challengers; no wagering authority simplifies gates | = `NHL_DAY0_20261112` |
| 3 | NCAAFB | Exact parity; needs B5 probability basis and B1 inputs | = `NCAAFB_20261102`; then Week 11 `build11.py` replay |
| 4 | NBA | Parity proven, but live use needs the results collector (B8) and Q1/Q5 decisions | = `NBA_R4_20261112` |
| 5 | NCAABB | Needs B1 storage for 81 MB inputs, B2 pin, Q2/Q6 decisions | = `NCAABB_V4_20261101` |

**P3 — live inputs and UI**

| ID | Deliverable |
|---|---|
| B8 | `gambling/results`: ESPN finals/schedule capture with raw-payload hashing (unblocks NBA freshness, NCAABB `games_before`, NCAAFB weekly finals, NFL snapshot) |
| B9 | Generalized NCAAFB weekly feature builder as **new code** proven equal to `build_features.py` (Nov 2) and `build11.py` (Nov 8) |
| B10 | Capture → legacy-input converters (NBA 12-field JSON, NFL `board.json`) as tested adapters |
| B11 | `apps/streamlit` read-only viewer over B7 exports and the registry |
| B12 | Accounts/P&L import per the separate plan (local data only; synthetic fixtures in Git) |

## 6. Missing artifacts to request (cannot be reconstructed)

| Artifact | Needed for | Status |
|---|---|---|
| `NCAABB_V5_FREEZE_PARAMETERS.json` | V5 shadow replay | Not in repo or any supplied package |
| NBA R3 code + parameters | R3 challenger column | Not found |
| NHL ML V3, PL V1, V15 models (+ V15 2026-27 features) | NHL challenger columns | Not found |
| NHL Grand Salami totals V1 / spread Day-0 V1 release evidence | Grand Salami module | Not found |
| NCAABB Nov 7 ESPN schedule JSON | Nov 7 replay | Known missing |
| Source of NFL `games_snapshot.csv` | Live NFL features | Undocumented |

## 7. Research questions for ChatGPT (decision tickets)

- **Q1** NBA: is `evidence/repaired_oct29_reference.csv` or restored R4 output the authoritative Oct 29 golden? (Nov 12 R4 parity is exact.)
- **Q2** NCAABB: is V4 `adjusted_kelly_before_portfolio` (Full Kelly × evidence factor) the approved Adjusted Kelly, or an effective-N haircut that policy excludes?
- **Q3** All sports: for non-selected sides, may the bet sheet display a complementary probability (1 − p) for two-outcome markets, or only `EVALUATED / NOT_SELECTED` with no P?
- **Q4** NCAAFB: confirm presentation of conditional-on-decisive P/EV/Kelly (label vs suppress unconditional fields).
- **Q5** NBA: accept the manually transcribed Nov 6–11 finals in the frozen history, or require an ESPN-sourced replacement with a discrepancy report?
- **Q6** NCAABB: confirm `NCAABB_V4_PROD_THROUGH2025` champion authority (registry evidence `INFERRED`).

## 8. Reproduction recipe

Extract the frozen ZIP (in repo) and the Feature Source & Reproducibility package (SHA above) to temporary directories; copy archived outputs aside; run each scorer unchanged (`score.py`; `nba.py score --quotes … --history …`; `build_features.py && score_both.py`; `rebuild_nov01_offline.py` under scikit-learn 1.8.0; NHL `adapter.score(quotes)` with the package controls); compare with the rule in §2. B3 will turn this recipe into committed tests.
