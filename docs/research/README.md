# Research decision and implementation evidence

This area is the durable interface between ChatGPT model evaluation and Claude Code implementation.

- `decisions/`: ChatGPT research proposals, user approval, dataset SHA256, frozen comparison specification.
- `implementations/`: Claude PR/commit hashes, implementation summary, exact tests and outcomes.
- `docs/handoff/RESEARCH_CHANGE_REQUEST_TEMPLATE.md`: template for a research proposal.
- `docs/handoff/RESEARCH_TO_DEVELOPMENT.md`: end-to-end collaboration protocol.

Only small human-readable specifications and safe test fixtures should be committed. Do not store actual betting-account exports, credentials, personal finance details, raw unrestricted data or unverified reports in Git.

A discussion is never evidence that a model was promoted. The model registry and historical status history establish past scoring/authorization, and approved implementations record new release IDs.

- `decisions/2026-11-24-claude-replay-six-questions.md`: six methodological answers to Claude's five-sport replay questions, with verified repository evidence and unresolved provenance separated.
