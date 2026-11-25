# Claude Code handoff — Gambling sports research application

**Prepared:** November 24, 2026 (America/Chicago). **Source:** committed code on `main`, existing project decisions and conversations.  
**Purpose:** Claude Code owns **software development**; ChatGPT owns **statistical evaluation and model-refinement research**. GitHub is the handoff and implementation record. This is a knowledge brief, not a frozen model release, a live sportsbook feed, an account data export, or a claim that unimplemented modules work.

## Read this first in Claude Code

1. `CLAUDE.md`, then `docs/engineering-policy.md` (mandatory non-negotiable rules).
2. This handoff's `CURRENT_STATE.md` and `SPORT_MODELS.md`; inspect the actual artifacts and schema they cite.
3. `BETSHEETS.md` and `WAGERS_PARLAYS_BONUSES.md` for product behavior and accounting boundaries.
4. `RESEARCH_TO_DEVELOPMENT.md` and `RESEARCH_CHANGE_REQUEST_TEMPLATE.md` for approved ChatGPT-to-Claude work.
5. `MISSING_AND_UNCERTAIN.md` before making any model-authority claim.
6. `ROADMAP.md`, `docs/architecture.md`, `docs/model-authority.md`, `docs/branch-strategy.md` and the active `docs/sports/<sport>.md`.

## Roles and collaboration contract

| Area | ChatGPT research role | Claude development role |
|---|---|---|
| New model ideas | Form hypotheses, reconstruct/evaluate evidence, calibrate, test challengers | Implement experiment hooks and reproducible scripts without affecting champion |
| Model promotion | Recommend with specified evidence; record uncertainty | Verify frozen parity, tests, governance, and explicit approval; create a new release |
| Daily scoring | Analyze outputs, diagnose disagreement and historical behavior | Capture odds, apply certified model adapters, persist scoring and generate bet sheets |
| Bet-sheet improvements | Define columns, scope, calculations, status semantics and rankings | Implement and test sport-specific and consolidated exports/UI |
| P&L/bonuses | Evaluate returns, exposure, bonus strategy and model attribution | Ingest/reconcile real ledger with evidence, provide reproducible reports |
| Streamlit | Review user-facing analytical usefulness | Implement UI without duplicating model logic |

**No inference from chat to authority:** A ChatGPT suggestion does not automatically change `main`, the model release registry, or a betting authorization. Claude should take a research proposal, verify its artifacts against the repo and data, and implement only scoped changes. User-approved decisions are recorded in docs and versioned code.

## Provenance labels in this handoff

- **[REPO-VERIFIED]** Directly inspected current `main` source/artifacts and documentation.
- **[PRIOR-DISCUSSION]** User requests or past conversation state; valid product requirements or research context, but not proof that a feature was committed or a data file is available.
- **[OPEN/VERIFY]** Undetermined, missing or not independently executable/reconciled; never fill with plausible defaults.
- **[PROPOSED]** Architecture/research/development workflow recommendation, not executed code.

The literal repository is authoritative for **what is implemented**. Immutable original model release records and point-in-time evidence are authoritative for **historical model state**. Reconciled sportsbook transactions are authoritative for **real money P&L**. A discussion may govern the intended direction but does not override observed code or frozen historical records.

## The intended end state

A single reproducible, multi-sport pipeline that captures time-stamped Bovada lines; maintains all immutable quotes, score records and releases; applies versioned champion and challenger models; exports **every** scored bet-sheet row in chronological order; identifies new/existing and blocked/unscorable rows; reconciles actual settled wagers and bonuses; produces separate research parlay comparisons and actual account performance; and serves all these via Streamlit. No application action should place bets.

## Do not do these things

- Do not rewrite frozen scores, silently refit an existing release, or promote challenger/shadow models because they show positive EV.
- Do not assume `legacy_models` is a working generalized five-sport live engine.
- Do not assume a missing sportsbook line, a stale quote, a hypothetical win, or a positive past ROI proves a real available wager.
- Do not pretend the November 11, 2026 frozen bet sheet incorporates all later research changes.
- Do not commit personal account exports, live database files, credentials, session cookies or unverified research datasets.
- Do not delete source/legacy evidence as "cleanup" before a verified independent backup and restoration test.

## First recommended Claude session

Read every document above; run the repository unit tests and frozen audit; inspect the model registry and missing model artifacts; inventory the *actual* code behind each current bet sheet; record any missing post-Nov-11 files or approvals; then propose ONE sport-specific adapter/fixture PR. See the requests in `MISSING_AND_UNCERTAIN.md`. No automatic promotion or score approximation.

## New verified model-transfer audit (November 24, 2026)

- `MODEL_TRANSFER_AUDIT_2026-11-24.md`: primary-source-backed status for all 18 releases and five sports, source dependency blockers and implementation order.
- `LOCAL_INPUT_INVENTORY_2026-11-24.md`: six user-supplied NCAAFB file hashes, counts, missing slopes, 2023 reconstruction limits and safe local transfer.
- `CLAUDE_MODEL_TRANSFER_RUNBOOK.md`: explicit commands, artifact-recovery gates, one-adapter-at-a-time implementation and ChatGPT research handback.

These supplement, rather than override, the existing architecture, recorded authorities and research decisions. The NCAAFB raw files are **not committed or available to Claude merely because hashes are documented**.

## Executed parity and readiness (Claude Code, November 24, 2026)

- `docs/research/implementations/2026-11-24-model-transfer-readiness.md`: executed frozen replays for all five sports, readiness per release, contract gaps, prioritized backlog and research questions Q1–Q6.
- `docs/research/implementations/2026-11-24-release-readiness-inventory.csv`: runbook Step 1 machine-readable inventory.
