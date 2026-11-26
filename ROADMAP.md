# Migration roadmap — reproducibility before automation

## Phase 0 — complete in this export

- Carry forward the November 11 authoritative rolling-history snapshot.
- Import the original five-sport model source packages as *legacy reference*
  code, without promoting or silently refitting any model.
- Audit 28 capture batches, 1,156 events, 6,936 quotes, 10,173 scores, and 148
  matched settled games; reproduce November 11 production-score classification.
- Preserve the 88 hypothetical same-cohort parlays as research-only observations.
- Provide a CLI and automated audit regression tests.

## Phase 1 — stable price ingestion (core done 2026-11-11)

Done: date-independent Bovada client (`gambling/bovada/`), URL-variant ladder
for the CDN stale-cache failure, response classification, retries/backoff,
per-market parsing with explicit states, event-page recovery, append-only raw
captures with checksums, `Date − Age` snapshot times, `fetch --replay`, golden
tests against archived NFL/NBA payloads and fault-injection tests.

Also done: package cleanup into importable modules (`config`, `odds`,
`timeutil`, `history`, `db`, thin `cli`), and the persistent rolling SQLite
history — hashed numbered migrations, one-time verified import of the frozen
archive, `ingest` of capture JSON (raw bodies stay as files, verified by
sha256), append-only triggers, line-movement / latest-price / fetch-health
views, and point-in-time exports.

Remaining:
- Cross-check each board against an independent schedule (ESPN) so games the
  book never listed are labelled `NOT_LISTED_BY_BOOK` rather than invisible.
- Optional re-sweep to tighten cross-sport skew under the 120 s cohort rule.
- A versioned normalization view mapping legacy `side`/`game_key`/status
  conventions onto the current vocabulary (legacy rows stay as recorded).
- `legacy_ops/fetch_nov11_*.py` are kept as archived evidence; do not use them.

## Phase 2 — one model adapter at a time

Model registry done (2026-11-11): 18 releases registered with artifact hashes,
role/authority history and mappings for all 29 legacy labels; every archived
score is attributed. Releases marked `PARTIAL` / `ARTIFACTS_MISSING` keep their
archived predictions but cannot make new ones until rebuilt as a *new* release
that reproduces the archived outputs (NCAAFB V2 is likely rebuildable from
`authority.json`). NBA R3 and the NHL challengers are candidates for retirement.

For each NHL, NBA, NCAABB, NFL, and NCAAFB champion/challenger release:

1. Register the release and its artifact hashes; record feature cutoffs and train/validation boundaries.
2. Refactor the existing source into a uniform `score(game, odds, state)` contract.
3. Compare exact known-game Model P, tier, EV, and Full/Adjusted Kelly against
   golden outputs for several archived cohorts.
4. Fail closed on missing features; preserve Pass ledger and blocker reasons.
5. Only then enable daily scoring for that sport; no automatic refits/promotions.

## Phase 3 — results and accounts

- Daily ESPN finals imported separately from raw Bovada bets.
  - [x] 2026-11-25: ESPN scoreboard collector for all five sports (`gambling/results/espn.py`, migration `0007_espn_results`, `python -m gambling results fetch|conflicts|nba-history`). Raw responses are kept with URL, request date, retrieval time and SHA-256; every event is observed; finals are recorded once in `official_game_results` and never overwritten (differences go to `espn_result_conflicts`). NBA history feed writes base + ESPN finals to a new file and blocks on team names the base never used. 0007 verified on a copy of the real database (31 existing tables unchanged).
  - [x] Reconciliation: the user database's 15 NBA finals (Nov 8–9) agree with the manually transcribed R4 history; the one key mismatch is the Clippers name (below).
  - [x] First live fetch on the user PC (2026-11-25, NBA 2026-11-24): 3 events, 3 finals recorded, 0 conflicts. This applied 0006 + 0007 to the live `data/gambling.sqlite` (backup `data/archives/gambling.sqlite.pre-0006-0007.20261125.bak`). Migrations 0001–0007 are now frozen (`tests/test_migration_freeze.py`).
  - [x] 0008 `espn_result_retrievals`: a re-fetch that returns identical bytes records only the retrieval, not another full capture.
  - [ ] Daily scheduled fetch (all sports, previous day) on the user PC.
  - [ ] Data-quality finding for ChatGPT review: the frozen NBA history uses both "Los Angeles Clippers" (through 2026-11-08) and "LA Clippers" (2026-10-28 onward, 6 rows), so V27 features split the team. Not changed (frozen evidence).
- Immutable odds snapshots; append game result events; calculate hypothetical
  market outcomes but never equate them to money won or lost.
- Import user-account wagers using unique transaction IDs, wager legs and
  settlements; reconcile cashback, casino/poker, and manual adjustments.
- Produce original tier as of recommendation and tier under current model
  separately, including unmatched and unverifiable recommendations.

## Phase 4 — independent parlay research and bonus ledger

Exact sportsbook multi-leg quote required. Same-day, distinct-game legs only.
Measure realized out-of-sample log growth and both bonus objectives after real
qualification and account rules have been verified. The model stays research
only until proper promotion criteria are satisfied.

## Phase 5 — optional interface

Only after the core CLI is reliable, add a lightweight local dashboard. A
Streamlit interface is a practical option; a server or cloud deployment is not
necessary for the initial workflow.

## Completion conditions

The migration replaces ChatGPT operational scoring when one reproducible
command performs: capture today's odds, score all available games with the
frozen champion and challenger, flag new vs previous bets, log passes and
missing inputs, attach yesterday's finals, update historical ledgers, calculate
research parlays, and export the chronological bet sheet—without manual data
repairs and without a chat history dependency.

## Phase R1 — repository/workstream reorganization (2026-11-24, in progress)

- [x] Preserve pre-reorganization migration plan in `docs/history/migration-roadmap-2026-11.md`.
- [x] Publish canonical engineering policy, package boundaries, branch strategy, model-authority and shared bet-sheet contract.
- [x] Publish separate NFL, NCAAFB, NBA, NHL, NCAABB and Streamlit specifications.
- [x] Scaffold sport model and bet-sheet packages and CI documentation gates.
- [x] Run offline tests and frozen-history audit in GitHub Actions (run 45529455524): documentation gate, unit tests, and frozen-history audit passed. Five-sport *live-model parity* remains a separate, outstanding certification.
- [ ] Merge validated `reorg/v1` to `main` only after checks.
- [x] Create six workstream branches provisionally at reorg/v1 head; synchronize them with validated main after integration.
- [ ] Verify separate offline/local backup before untracking any cleanup candidate.
- [ ] Inventory and integrate post-November-11 model and bet-sheet changes from their actual source.

This phase is structure and documentation only: no model promotion, recalibration, odds/pricing logic change, or wager settlement rewrite is authorized. The archived November 11 board is not necessarily the newest bet sheet.

## Research-to-development handoff — documentation package

- [x] Prepare a Claude Code-readable repository, model, bet-sheet, wagering/parlay/bonus and provenance brief in `docs/handoff/`.
- [x] Link Claude and agent entry instructions to the handoff, with a reusable research change-request template and implementation-report workflow.
- [ ] Complete five-sport latest-code/authoritative-release inventory, including out-of-repository files and uncommitted changes.
- [ ] Implement first independently approved research decision with paired frozen replay, documented release ID and golden tests.
- [ ] Build a continuously validated, all-rows chronological bet-sheet export per sport, then separate Streamlit UI integration.

Historical provenance, immutable original score/authorization and unknown account data limits remain in force. Handoff docs are **not** certification that these features already work.

## Five-sport transfer audit (2026-11-24)

- [x] Inspect all 18 seeded release artifact/authority statuses and code-dependency paths; document evidence and gaps in `docs/handoff/MODEL_TRANSFER_AUDIT_2026-11-24.md`.
- [x] Inspect six user-supplied NCAAFB file schemas/counts/hashes; **metadata only**, no raw data transfer to Git and no authority promotion; see `docs/handoff/LOCAL_INPUT_INVENTORY_2026-11-24.md`.
- [x] Publish Claude model-transfer runbook and startup instructions.
- [ ] Retrieve/verify missing (NHL controls: recovered — rebuilt exactly, SHA-256 `4b6119a0…`, in the NHL golden fixture), NCAABB V5 parameter freeze, NCAAFB Weeks8-10 posterior/inputs, NBA R3 challenger, and frozen NFL ZIP scorer members.
- [ ] Execute per-release historical parity and model checksum checks in Claude's development checkout; this ChatGPT audit inspected sources but did not execute five sport runners.
- [ ] Implement the certified shared scoring interface and first live adapter **without changing frozen model outputs**.
- [ ] Reconcile current-season chronology, exact quotes, original tiers, score statuses and all-rows bet-sheet exports.

## Executed transfer parity (2026-11-24, Claude Code)

See `docs/research/implementations/2026-11-24-model-transfer-readiness.md` and the companion `2026-11-24-release-readiness-inventory.csv`.

- [x] Run per-release frozen replays with unchanged scorers: NFL Nov 10 (in-repo), NBA R4 Nov 12, NCAAFB Nov 2, NCAABB V4 Nov 1 and NHL Day-0 Nov 12 reproduce archived outputs exactly; NBA Oct 29 reference does **not** match (research question Q1).
- [x] Identify environment pin: NCAABB V4 binary requires scikit-learn 1.8.0.
- [x] B2–B3: pinned model environment (`requirements-models.txt`, scikit-learn 1.8.0) and golden replay harness with five hashed fixtures (`docs/golden-fixtures.md`); all five PASS in the pinned environment; CI `golden-replay` job added (NCAABB skips without external inputs).
- [ ] B1: external-input storage — superseded by the model-input database design (`docs/model-data/`).
- [ ] B4: readiness CLI.
- [x] B5–B7: adapter contract v2 (conditional probabilities, push states, NOT_EVALUATED_BY_MODEL, labelled complements per PR #4 decisions 3–4), push-aware EV/Full Kelly, Adjusted Kelly pass-through with method/certification, all-rows chronological CSV + Excel bet sheets (`tests/test_scoring_v2.py`, 22 tests).
- [x] NFL frozen-replay adapter (REV2-CAL + W8) with golden parity and 72/72 archived-row match; complete 144-row bet sheet.
- [x] NHL Day-0 frozen adapter (ML/PL/OU champions + V3/PL V1/V15 challengers) with golden parity: 132/132 archived rows, original 81 PASS / 44 UNSCORED / 7 RESEARCH_POSITIVE_EV split, model push probability on integer totals; no release wager-authorized.
- [x] NCAAFB Week 8+ frozen adapter (spread PP-V2 champion / continuous-V1 challenger, shared ML rule, shared OU research rule) with golden parity on the Nov 2 board: 186/186 archived tiers, probabilities, EV and Full Kelly unchanged; fresh scorer rerun identical within 1e-9; 496-row sheet with 6 PRODUCTION_QUALIFIED (registry-authorized) rows.
- [x] NBA R4 (V27) frozen adapter with golden parity on Nov 12: 12/12 archived rows (tier, P, EV, Full Kelly, shadow portfolio Adjusted Kelly) unchanged; rerun identical within 1e-9; scorer quote JSON rebuilt byte-identically from the capture; R3 challenger BLOCKED (artifacts missing); 48-row sheet, 2 PRODUCTION_QUALIFIED spreads.
- [x] NCAABB V4 frozen adapter with golden parity on Nov 1: 35/35 archived rows (P, push, EV, Full Kelly, evidence-factor Adjusted Kelly) unchanged; full rerun identical and preparer block reason recovered; 76-row sheet, 9 PRODUCTION_QUALIFIED from recorded `stake_eligible` (7 tier Lean, 2 tier B) — eligibility mapping flagged for ChatGPT/user review.
- [x] All five sports have frozen-replay adapters and complete bet sheets (NFL, NHL, NCAAFB, NBA, NCAABB).
- [ ] NCAABB live use: daily preparer on new captures (SportsDataverse schedule refresh, ESPN mapping), master results builder for the 76 master-only columns, V5 shadow adapter, reconcile Nov 6–10 user-database batches.
- [ ] NBA live use: automated completed-results source (scorer rejects history >7 days stale; Nov 6–11 finals were manual), R3 artifacts or retirement decision, Oct 29 pipeline (research Q1); reconcile Nov 6–11 user-database NBA batches.
- [ ] NCAAFB live use: weekly pregame features, posterior/quadrature refresh decision, published SRS gate source, results ingestion; reconcile Nov 6–10 `model_scores` batches in the user database against this adapter.
- [ ] NHL live use: control-file refresh decision (frozen through 2025), V15/PL V1 inputs, ChatGPT evaluation of Day-0 edge.
- [ ] NFL live pipeline: current schedule/results source and capture-to-board converter.
- [ ] Still missing: NCAABB V5 freeze parameters, NBA R3, NHL ML V3/PL V1/V15, Grand Salami release evidence.

No model was refit, re-tiered or promoted; no wager authorization changed.

## Model-input store (SQLite) — 2026-11-25

MySQL/Azure dropped by user decision ("we are using sqlite in the project").

- [x] M0: migration `0006_model_data` in `gambling/db/migrations`, applied by the existing migrator into `data/gambling.sqlite`. `md_*` tables reuse `model_releases` (no second registry), link runs to `capture_batches` / `quote_cohorts` / `model_scores`, carry `game_key` on rows. Importer for CSV/CSV.gz/Parquet/JSON/blob, time-safe retrieval, run pins, account/wager column guard, snapshot with SHA-256, CLI. All five golden fixtures replay identically from inputs materialized from a copy of the history database; the 19 pre-existing tables are byte-for-byte unchanged (`docs/model-data/README.md`).
- [x] Growing masters: `ncaabb/master` (base FULL + APPEND chain keyed by `game_id`, `produced_by_run`, supersede-by-key, as-of reads); the master stays in the live database per user decision. `append_run_to_master` (NCAABB adapter) appends a run's pregame inputs keyed by ESPN `game_id`; verified on the real master (29,008 + 13; rerun appends 0). It runs automatically once a daily NCAABB pipeline exists.
- [x] M1a: 0006 + master + golden import verified on a copy of the real `data/gambling.sqlite` (SHA-256 `ef84f3a0…`; 32 / 10,158 / 10,173); 18 existing tables unchanged; 5/5 PASSED (`docs/model-data/M1-verification-2026-11-25.md`).
- [ ] M1b: migrate the live file on the PC after a verified offline backup.
- [ ] M2: read-only import of capture history, ESPN finals and recovered feature inputs, keyed by `game_key`.
- [ ] M3: dual-run period: frozen outputs remain authoritative.
- [ ] M4: independent validation and recorded authority decision.
