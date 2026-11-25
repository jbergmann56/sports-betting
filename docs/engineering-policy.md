# Engineering policy — authoritative development contract

This file is the canonical source for rules shared by Claude Code, ChatGPT/Codex, and contributors. Root `CLAUDE.md` and `AGENTS.md` are entry points; they must link here, not independently change model rules.

## Evidence, scoring and account boundaries

1. Frozen historical datasets, model artifacts, and original recorded prediction/authorization are immutable evidence. Preserve source hashes, point-in-time timestamps, and event/quote/transaction IDs.
2. SQLite history is authority for **observed market quotes and saved model records**, not for actual financial returns. Actual sportsbook P&L requires separately reconciled user wager, settlement, and account transaction evidence. Never equate a hypothetical winning quote with a real bet.
3. Each Bovada capture retains raw response, source endpoint, response time, bookmaker event/market/outcome identifiers, and quote-as-of time. Do not silently substitute a stale, later, or different-book quote.
4. Missing odds, features, unmatched teams, stale features, model failures, and book-not-listed games must be flagged as `UNSCORED`, `BLOCKED`, or a precise coverage reason. Never invent 0.5 probabilities or turn missing-input rows into `PASS`.
5. Only frozen, registered model releases may produce authoritative probabilities, tiers, EV, or Kelly. Maintain champion/challenger/research authorization separately from model EV; a strong research score does not become a production signal.
6. Keep original pre-bet model attribution separate from current-release retrospective classification. Every score and bet-sheet row preserves model release ID, version, quote time, score time, market, side, line, price, tier, and authorization.
7. Full Kelly and model-specific adjusted Kelly must be available wherever computable; preserve assumptions and missing-value reasons. Never double-apply shrinkage. Joint portfolio sizing is not approved without joint exposure, uncertainty, and dependency checks.
8. Keep all scored bet-sheet rows, including positive/zero/negative EV, `Pass`, `Lean`, and `Unscorable`; display filters are views, not record deletion. List events chronologically with UTC provenance and Central Time presentation.
9. Parlays require one leg per physical game, actual book-quoted combined odds, push/void behavior, and verified promotion-credit rules before production eligibility; theoretical combinations remain research-only.
10. No code automatically places wagers or manages real stakes. The project is a deterministic research and accounting system.

## Code separation

- Each sport has its own `gambling/models/<sport>/` and `gambling/betsheets/<sport>/` modules and its own `docs/sports/<sport>.md` specification.
- Shared sportsbook capture, quote keys, release registry, settlement identities, bankroll conventions, and P&L stay in shared packages. Do not fork these calculations across sports.
- `legacy_models/`, `legacy_ops/`, and `legacy/v1_app/` are archived evidence. Do not edit their bytes during reorganization. New adapters are new code and require frozen parity fixtures.
- `apps/streamlit/` is a separate frontend that consumes shared Python APIs; never duplicate model scoring in the UI.
- Git holds code, small fixed regression fixtures, and vetted documents. Personal account data, SQLite runtime files, credentials, and browser profiles stay outside Git and receive separate encrypted backups.

## Documentation as a merge requirement

Every PR must update documentation **in the same commit series** as behavior changes:
- Model release, feature, tier, calibration or authority change: update `docs/sports/<sport>.md`, `docs/model-authority.md` and relevant golden fixtures.
- Bet-sheet columns, sorting, filtering or eligibility change: update `docs/betsheets/shared-contract.md`, that sport's spec and a fixture/test.
- DB schema or ingestion change: update `docs/architecture.md`, migrations and schema/ingest tests.
- Streamlit change: update `docs/streamlit.md` and UI validation.
- Work item/status change: update `ROADMAP.md`. Record decisions and known blockers; do not mark a phase complete because a directory exists.

Each PR must declare verification commands/results and whether historical score/EV/tier or real P&L changed. If unable to run required parity tests, keep the PR draft and label it unverified. Never merge a destructive archival cleanup until a separate offline backup is verified.

## Branch and release policy

`main` = validated integration/production authority. The branches `sport/nfl`, `sport/ncaafb`, `sport/nba`, `sport/nhl`, `sport/ncaabb`, and `ui/streamlit` isolate ongoing work; shared work uses short-lived `feature/core-*` branches. All promotions require PR review, CI, regression evidence, and explicit model-authorization records. Follow `docs/branch-strategy.md`.
