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
