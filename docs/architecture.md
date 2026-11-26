# Repository architecture — V1 target

## Source-of-truth hierarchy

1. Immutable original snapshots: `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip`, archived model artifacts and fixtures.
2. Append-only operational history: `data/gambling.sqlite` plus raw `data/captures/` files (both local/gitignored, backed up separately).
3. Authoritative release registry: `gambling/db/migrations/0004_model_registry.sql` and `0005_seed_model_registry.sql`, plus future append-only migrations.
4. Validated, runnable model adapters under `gambling/models/<sport>/`, only after output parity and authorization checks.
5. Derived research bet sheets and UI views under `gambling/betsheets/<sport>/` and `apps/streamlit/`. Neither is a substitute for the provenance and wagering ledger.

## Package boundaries

```text
gambling/
  core/                  cross-sport contracts and shared utilities
  bovada/                raw book capture and price normalization (existing)
  db/                    append-only schema, ingestion and exports (existing)
  models/{nfl,ncaafb,nba,nhl,ncaabb}/   new model adapters; initially placeholders
  betsheets/{nfl,ncaafb,nba,nhl,ncaabb}/  sport-specific output specifications
  scoring/               shared tiers/EV/Kelly authorization, under development
  accounts/              user wager and settlement ingestion, under development
  performance/           realized P&L and model reports, under development
  parlays/               research and price-checking module, not production
  bonuses/               rollover reporting, not production
apps/streamlit/          future frontend; archived v1 lives in legacy/v1_app/
tests/                   historic evidence and contract regression tests
docs/                    authoritative development specifications
legacy_models/, legacy_ops/, legacy/v1_app/   immutable reference material
```

These directories define **ownership**, not claims of completed functionality. As checked in before this reorganization, public quote capture, frozen historical review, rolling SQLite ingestion, model registration and offline tests exist. Fresh 5-sport scoring, complete actual wager accounting, and the new Streamlit frontend are not certified.

## Validation for model promotion

Register release and artifact hashes → fix feature cutoff/snapshot → compare P(win/push/loss), side/line, EV, Full/Adjusted Kelly and tiers to archived frozen outputs → audit every missing-input row → document promotion → enable daily scoring. Never overwrite a historical observation. `main` is the integration branch, not a mechanism for automatically declaring a release production-authorized.

## Non-Git data

`.local_archive/` is for verified local-only copies of nonessential material; files in that directory are ignored and **do not travel with a Git clone**. Personal exports and accounts require separately encrypted/offline backup. See `docs/cleanup-inventory.md`.

## Implemented shared scoring and bet-sheet layers (2026-11-25)

- `gambling/accounts/importer.py` — raw import into the separate accounts database (own migrations in `gambling/accounts/migrations/`): verbatim files/pages, every transaction version and sighting, coverage windows, verbatim P&L baseline. Refuses `gambling.sqlite`.
- `gambling/accounts/exports.py` — read-only pre-import profile of the Bovada exporter output (`*_pages.jsonl` as source; coverage, gaps, duplicates, balance chain, baseline reconciliation). Account data goes to a separate database, never `gambling.sqlite`.
- `gambling/reconcile/` — read-only replay of recorded `model_scores` batches through the frozen adapters with inputs rebuilt from the database (NHL, NBA); named history variants document explained differences.
- `gambling/results/espn.py` — ESPN scoreboard collector (migration 0007): raw captures, per-event observations, first final recorded in `official_game_results` and never overwritten (later differences go to `espn_result_conflicts`); identical re-fetches recorded as retrievals only (0008); NBA history feed for the R4 scorer. The network fetch runs on the user machine.
- `gambling/core/bovada.py` — parser for archived Bovada coupon responses (main full-game Spread/Moneyline/Total, outcome price IDs as `quote_id`, `NOT_PREGAME` when captured at or after the start); shared by NCAAFB and NCAABB.
- `gambling/core/quotes.py` — `QuoteSide` (selection-oriented lines), long-capture reader, `complete_board` (explicit `NOT_OFFERED` sides).
- `gambling/models/base.py` — adapter contract v2 (`SCORED`, `CONDITIONAL_SCORED`, `EVALUATED`, `NOT_EVALUATED_BY_MODEL`, `UNSCORED`, `BLOCKED`); v1 positional construction unchanged.
- `gambling/scoring/pricing.py` — push-aware EV / Full Kelly with basis and null reasons; Adjusted Kelly pass-through only.
- `gambling/scoring/sheet.py` — assembly (quote side × release), labelled complements, registry authority at quote time, chronological sort, new-vs-previous.
- `gambling/betsheets/export.py` — all-rows CSV and Excel workbook.
- `gambling/scoring/sheet.assemble(..., market_releases=)` — optional per-market release list, for sports whose champion/challenger differ by market (NHL). Without it every release is paired with every quote (unchanged behaviour).
- `gambling/scoring/sheet.Authority.from_connection(con)` — registry authority from an open connection (sport sheet builders, tests on a temporary migrated database).

Dependency direction: adapters → `ScoreRow`; `scoring` reads `ScoreRow` + `QuoteSide` + registry; `betsheets` reads assembled rows. No layer below `scoring` assigns tier, EV or authorization. See `docs/betsheets/shared-contract.md` for column semantics.

## Model-input database (2026-11-25)

`gambling/modeldata/` — versioned, append-only store for model inputs, in the same SQLite file as the rolling history (`data/gambling.sqlite`, migration `0006_model_data`, `md_*` tables): immutable source files by SHA-256, dataset versions with lossless rows and status events, time-safe retrieval, run input pins, column guard that rejects account/wager exports. It builds on the existing model: runs reference `model_releases`, link to `capture_batches`, `quote_cohorts` and `model_scores`, and rows carry `game_key`. Existing tables are not altered. Sportsbook account data stays out (separate accounts database). See `docs/model-data/README.md`.
