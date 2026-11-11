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
