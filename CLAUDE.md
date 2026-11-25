# Gambling Python — Claude Code working rules

You are working on a historical sports-model research system, not an automated
wagering bot. Prioritize provenance, determinism, explicit missing-data states,
and accurate champion/challenger boundaries.

1. The SQLite history exported in `data/` is the source of truth for **observed
   quote/model records**. User-placed wager settlement/P&L requires a separate
   reconciled Bovada account export and must never be inferred from hypothetical
   quote outcomes.
2. Every odds fetch must retain full bookmaker response, source URL, retrieval
   timestamp, bookmaker event ID, and market-side quote ID. Never assign a
   single timestamp to differently timed pulls. Do not silently substitute a
   different sportsbook or historical/late quote for a missing Bovada quote.
3. Only score pregame main-market spread/ML/total as configured. Label absent
   odds, unresolved teams, stale features, and model failures `UNSCORED` or
   `BLOCKED`, not `PASS` or assumed probability 0.5.
4. Preserve the **frozen original model and original pre-bet authorization**.
   Later model tier reclassifications belong in separately versioned records.
   Challenger/research predictions do not become production bets due to EV.
5. Model P/EV/Kelly must come from a verifiable frozen model release, not
   hand-derived approximations. Display Full Kelly and Adjusted Kelly; never
   double-count calibration shrinkage. Joint portfolio Kelly needs calibrated
   probability uncertainty, available prices, open exposures, and dependence.
6. For same-day parlays, one leg per physical game. Exact book-quoted combined
   odds, promotion controls, push behavior, and historical validation are
   required before a parlay could be considered production-authorized. The
   archived Nov11 combinations are hypothetical **research-only/sizing blocked**.
   Bonus rollover speed is not proven without actual qualifying credit rules.
7. Do not submit actual wagers, place orders, or manage real stakes. This app
   is a deterministic analysis and recordkeeping tool.
8. Every code change must pass tests. Prefer a failing golden replay fixture
   before changing a production scorer. Record hashes of model binaries,
   schema migrations, source snapshots, release parameters, and run times.
9. Never modify or overwrite the bundled original archived evidence. Create
   append-only migrations and a new result archive only after tests pass.
10. Explain any incomplete migration honestly. A wrapper around a legacy
    date-specific scorer is not yet a validated generalized live pipeline.

## Starting commands

```bash
python -m gambling audit
python -m gambling replay --date 2026-11-11
python -m unittest discover -s tests -v
```

## V1 architecture and documentation workflow

The canonical cross-assistant policy is `docs/engineering-policy.md` — read it **before any repository change**. Also read `docs/architecture.md`, `docs/branch-strategy.md`, and the relevant `docs/sports/<sport>.md` / `docs/betsheets/shared-contract.md` when changing that workstream. Existing frozen evidence is immutable.

Every change PR must update corresponding documentation, tests/fixtures, and `ROADMAP.md`; record commands and actual results. Do not claim that placeholder sport or Streamlit modules are implemented. Never untrack old files before a verified local/offline backup. See `docs/cleanup-inventory.md`.

## ChatGPT ↔ Claude Code model-research handoff

**Read `docs/handoff/README.md` and its linked `CURRENT_STATE.md`, `SPORT_MODELS.md`, `BETSHEETS.md`, `WAGERS_PARLAYS_BONUSES.md`, `RESEARCH_TO_DEVELOPMENT.md` and `MISSING_AND_UNCERTAIN.md` before making sport-model, betting-sheet, bankroll or performance changes.** ChatGPT leads independent research and model evaluation; Claude Code leads software development, fixture generation, CI and Streamlit. Only immutable, referenced artifact evidence plus explicit user approval can promote a model. Chat conversations are context, not code authority; the research handoff labels prior decisions, repo evidence and open verification separately.

For approved changes, implement from the `docs/handoff/RESEARCH_CHANGE_REQUEST_TEMPLATE.md` ticket, preserve all previous model outputs and original tier history, attach implementation evidence to a PR, and return the results to ChatGPT for assessment. Do not call a missing model file "verified" or reuse a historical bankroll as current exposure.

## Verified November 24 five-sport transfer audit

Before any model migration read `docs/handoff/MODEL_TRANSFER_AUDIT_2026-11-24.md`, `docs/handoff/LOCAL_INPUT_INVENTORY_2026-11-24.md` and `docs/handoff/CLAUDE_MODEL_TRANSFER_RUNBOOK.md`. These distinguish historical release registration from executable live scoring, identify missing model inputs and document checksum-only access to ChatGPT-side NCAAFB attachments. Do not import staged 2023 historical data as authoritative without ID/deduplication/provenance review. Research evaluation remains with ChatGPT.
