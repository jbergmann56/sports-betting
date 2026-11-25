# Implemented application, evidence and repository map

**Status:** [REPO-VERIFIED] against `main` at reorganization merge `306d387a7dd1ba8bc79e63ce1c944eac232b3e49`. This status is an audit baseline, not a live guarantee; recheck HEAD when developing.

## Repository topology

- Python >=3.11; installable `gambling` package; `pyproject.toml`. Legacy Streamlit app is at `legacy/v1_app/`; new `apps/streamlit/` holds only a workstream README.
- Shared operational packages: `gambling/bovada/`, `gambling/db/`, `gambling/history/`, `gambling/odds.py`, `gambling/timeutil.py`, `gambling/config.py`, `gambling/cli.py`.
- Contract and placeholders: `gambling/models/base.py`, `gambling/models/{nfl,ncaafb,nba,nhl,ncaabb}/`, `gambling/betsheets/{nfl,ncaafb,nba,nhl,ncaabb}/`, `gambling/{scoring,features,results,accounts,performance,parlays,bonuses}/`.
- Historical sources: `legacy_models/{nfl,ncaafb,nba_r4,ncaabb_v4,ncaabb_v5,nhl_day0}/`; `legacy_ops/`; `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip`; `data/20261111_frozen_bet_sheet.md`; `data/20261111_theoretical_parlays.csv`.
- Tests/CI: `tests/`, `.github/workflows/verify.yml`, `scripts/check_documentation.py`, `.github/PULL_REQUEST_TEMPLATE.md`.
- Existing branch families: `main`, `sport/nfl`, `sport/ncaafb`, `sport/nba`, `sport/nhl`, `sport/ncaabb`, `ui/streamlit`. `reorg/phase0` and `feature/rolling-sqlite` retained for provenance.

## What works per checked-in docs

1. Frozen Nov 11 evidence audit, score replay/read-only queries and theoretical parlay report. `README.md` and `ROADMAP.md`.
2. Bovada public odds capture: multi-endpoint URL ladder, CDN freshness classification, per-market sides/price states, raw bodies and manifests; `gambling/bovada/`.
3. Append-only SQLite history and numbered hashed migrations `0001` through `0005`; archive import, quote ingestion, snapshot export and point-in-time views. `gambling/db/`.
4. Model release registry with status history, aliases, artifact SHA256 and score attribution; `0004_model_registry.sql` and `0005_seed_model_registry.sql`. **18 seeded releases**, **29 legacy aliases**, **10,173 archived score rows**. `model_predictions` collapses **858** duplicate NCAAFB shared-component observations without changing source rows.
5. The Nov-11 audit evidence reports **28 capture batches, 1,156 events, 6,936 quotes and 148 matched settled games** in `ROADMAP.md`. These are frozen baseline counts, not up-to-date live totals.
6. The first reorganization PR's documentation gate, offline unit tests and frozen-history audit passed in GitHub Actions, but this does **not** establish new live scorer parity.

## What does NOT yet work as a certified integrated live system

- Fresh five-sport scoring from new odds captures (new games can be `UNSCORED`).
- Complete current-season feature rebuilding with point-in-time leakage checks.
- Full real account transaction ingestion and reconciliation, bonus settlements, normalized actual P&L.
- Certified post-Nov-11 model and bet-sheet changes; proper current odds outside the archived quote cohort.
- Verified sportsbook multi-leg parlay prices and live rollout.
- New Streamlit analytics application; its folder is a placeholder, not deployed functionality.
- Historical game schedule cross-check against independent source for books that never listed an event.

## Important identifiers and storage

The model-adapter `ScoreRow` contract in `gambling/models/base.py` requires `release_id`, `quote_id`, and status in {`SCORED`, `UNSCORED`, `BLOCKED`}. Scored rows carry coherent P(win), P(loss), P(push) summing to 1; non-scored rows have no probabilities and must include a reason. Market eligibility, EV, tiers and staking authorization belong to shared `gambling/scoring/`, **not** the model adapter.

`GAMBLING_DATA_DIR` can redirect all writable working data; default is `./data`. `data/gambling.sqlite` and `data/captures/` are Git-ignored working records. A database snapshot exporter exists at `gambling/db/export.py`; it is not a backup of the raw capture folders or of bookmaker account records.

Never treat `settlements` in a historical game-quote archive as a user's settled wagers unless a separate user-wager/transaction join proves that link.

## Reproduction and health commands

```bash
python -m unittest discover -s tests -v
python -m gambling audit
python -m gambling scores --date 2026-11-11
python -m gambling models list
python -m gambling models show NBA_R4_V27_20261030
python -m gambling models attribution
python -m gambling models verify
python -m gambling db status
python -m gambling history health
python -m gambling db export
```

Run only read-only/audit commands initially and report actual counts/results. Do not invoke `fetch`, `ingest`, or account exporters during model-research review unless needed for a scoped task and its source handling has been checked. Do not confuse a static repo with a current live database.

## Reorganization completion status

`main` contains the V1 modular scaffolding, documentation requirements, and workflows. Dedicated sport and Streamlit branches were created from that integrated commit. Model porting, merged UI implementation and backup-verified cleanup remain separate work. Some `ROADMAP.md` checklist entries may still describe a pre-merge state; verify against the PR and GitHub branch history before changing status.
