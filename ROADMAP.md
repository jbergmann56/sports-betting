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
- [ ] Retrieve/verify missing NHL controls, NCAABB V5 parameter freeze, NCAAFB Weeks8-10 posterior/inputs, NBA R3 challenger, and frozen NFL ZIP scorer members.
- [ ] Execute per-release historical parity and model checksum checks in Claude's development checkout; this ChatGPT audit inspected sources but did not execute five sport runners.
- [ ] Implement the certified shared scoring interface and first live adapter **without changing frozen model outputs**.
- [ ] Reconcile current-season chronology, exact quotes, original tiers, score statuses and all-rows bet-sheet exports.

## Executed transfer parity (2026-11-24, Claude Code)

See `docs/research/implementations/2026-11-24-model-transfer-readiness.md` and the companion `2026-11-24-release-readiness-inventory.csv`.

- [x] Run per-release frozen replays with unchanged scorers: NFL Nov 10 (in-repo), NBA R4 Nov 12, NCAAFB Nov 2, NCAABB V4 Nov 1 and NHL Day-0 Nov 12 reproduce archived outputs exactly; NBA Oct 29 reference does **not** match (research question Q1).
- [x] Identify environment pin: NCAABB V4 binary requires scikit-learn 1.8.0.
- [ ] B1–B4: external-input storage and hash manifest, model environment pin, golden replay harness, readiness CLI.
- [ ] B5–B7: `ScoreRow` v2, shared scoring, all-rows bet-sheet writer.
- [ ] Sport adapters in order NFL → NHL → NCAAFB → NBA → NCAABB, each with golden parity.
- [ ] Still missing: NCAABB V5 freeze parameters, NBA R3, NHL ML V3/PL V1/V15, Grand Salami release evidence.

No model was refit, re-tiered or promoted; no wager authorization changed.
