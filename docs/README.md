# Documentation index

- `engineering-policy.md`: authoritative rules for model evidence, authorization, PRs and security.
- `architecture.md`: package boundaries and data source-of-truth hierarchy.
- `branch-strategy.md`: six sport/UI workstreams, shared features and promotion gate.
- `model-authority.md`: registered releases, historical attribution and release validation.
- `betsheets/shared-contract.md`: all scored rows, tiers, EV/Kelly, quoted odds, output columns.
- `sports/{nfl,ncaafb,nba,nhl,ncaabb}.md`: versioned per-sport model and bet-sheet status.
- `streamlit.md`: frontend isolation and archived application boundary.
- `cleanup-inventory.md`: candidate obsolete files and the backup/untracking gate.
- `history/migration-roadmap-2026-11.md`: preserved original migration roadmap.

Before merging a behavior change, update the relevant docs, golden test fixtures, and master `ROADMAP.md`. The repository's PR template requires documented verification.

- `handoff/README.md`: complete Claude Code onboarding and collaboration protocol, with current state, five-sport authority, bet sheets, P&L, parlays, bonuses and open gaps.
- `research/README.md`: dated ChatGPT model research decisions and Claude implementation handback records.
