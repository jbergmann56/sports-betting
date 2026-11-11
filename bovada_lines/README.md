# Gambling project — Python migration

A deterministic analysis and recordkeeping package for the Gambling project:
the frozen November 11, 2026 evidence archive, reliable read-only capture of
Bovada's public odds feed, and a persistent append-only SQLite history that
grows with every capture. It is built to become a module of a larger sports
betting app (`import gambling`), with the CLI as a thin wrapper.

**Working now:** frozen-archive audit and score review, research-only parlay
review, Bovada odds capture (`fetch`), rolling SQLite history (`db`, `ingest`,
`history`), point-in-time exports, and regression tests.

**Not yet working:** fresh model scoring of new captures (new games show as
`UNSCORED`), schedule cross-checks for games the book never listed, historical
feature updates, real parlay book prices, personal transaction import, bonus
settlement, or bet sizing. Do not mistake historical saved EV for currently
offered EV. Nothing here logs in to a sportsbook or places wagers.

## Run locally

Python 3.11+, standard library only.

```powershell
# one-time: build the rolling database from the frozen archive
python -m gambling db init

# capture odds to files, then load them into the database
python -m gambling fetch                         # all five sports
python -m gambling fetch --sports NBA,NHL
python -m gambling ingest --all                  # every capture not yet ingested
python -m gambling ingest data/captures/<run_id> # one specific run

# query the rolling history
python -m gambling history latest --sport NBA    # newest price per upcoming game/market/side
python -m gambling history find "Celtics"        # look up game keys
python -m gambling history lines NBA:BOVADA:33233970
python -m gambling history health                # how reliable Bovada fetches were, by day/sport

python -m gambling db status                     # migrations, counts, integrity
python -m gambling db export                     # new dated archive under data/archives/

# frozen evidence (read-only)
python -m gambling audit
python -m gambling scores --date 2026-11-11      # `replay` is the original alias
python -m gambling parlays --date 2026-11-11 --limit 8
python -m gambling fetch --replay data/captures/<run_id>   # rebuild a capture offline

python -m unittest discover -s tests -v
```

Set `GAMBLING_DATA_DIR` to keep the data somewhere other than `./data`.

## Layout

```
gambling/
  config.py      data locations (GAMBLING_DATA_DIR override)
  odds.py        American/decimal/break-even arithmetic
  timeutil.py    UTC helpers, US-Central betting day
  bovada/        fetch: endpoint ladder, transport + classification, parser, capture files
  db/            rolling SQLite: migrations/*.sql, frozen baseline import, ingest, queries, export
  history/       read-only queries over the frozen archive
  cli.py         argument parsing and output only
legacy_models/, legacy_ops/   archived reference code — read-only, not imported
```

## Data files

| Path | What it is | Mutable? |
|---|---|---|
| `data/GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip` | Frozen original evidence (Library v28) | Never |
| `data/history.sqlite` | Disposable read-only extraction of the archive | Regenerated |
| `data/captures/<run_id>/` | Raw Bovada responses + `manifest.json`, `board.json`, `quotes.csv` | Append-only files |
| `data/gambling.sqlite` | Rolling history: frozen rows + every ingested capture | Append-only rows |
| `data/archives/GAMBLING_HISTORY_<utc>.zip` | Point-in-time exports with manifest | Never overwritten |

Raw HTTP bodies stay as files in `data/captures/`; the database stores their
path and SHA-256, and `ingest` verifies every body before loading a run.
`gambling.sqlite` can always be rebuilt from the frozen ZIP plus the capture
folders, so back up `data/captures/` alongside the exports.

## Bovada capture (`gambling/bovada/`)

**Why fetches used to fail:** Bovada's CDN caches every distinct URL separately.
Individual URL variants of a league feed were observed (2026-11-11) serving a
cached empty `{}` with HTTP 200 for days (`Age` header up to ~350,000 s) while
another variant of the same feed was fresh. The old scripts saved that `{}` as
if it were a valid board and stamped it with the file's modification time.

**What `fetch` does now:**

- Tries a ladder of equivalent URL variants per sport (`endpoints.py`) and
  classifies every response: `OK`, `EMPTY`, `STALE` (CDN `Age` > `--max-age`,
  default 900 s), `NON_JSON`, `TRUNCATED`, `MALFORMED`, `BLOCKED`, `RATE_LIMITED`,
  `HTTP_5XX`, `NETWORK_ERROR`, etc. Only network/5xx/429/truncation are retried
  (exponential backoff, `Retry-After` honoured); a cached answer moves on to the
  next variant instead.
- Unions events across fresh variants; per event, the freshest copy wins.
- Re-fetches the event page for pregame games missing any main-market side and
  accepts it only if it is fresh and strictly better.
- Emits six sides per game (ML/spread/total) with an explicit status:
  `OFFERED_PREGAME`, `SUSPENDED`, `NOT_OFFERED`, `NOT_PREGAME`, `SPECIAL_NON_GAME`.
- Quote time is `snapshot_as_of_utc` = response `Date` − CDN `Age`, recorded per
  event with the attempt it came from. Cross-sport skew is reported, not hidden.
- Exit code 2 if any sport is `FAILED`/`BLOCKED`.

## Rolling history (`gambling/db/`)

- **Migrations** (`db/migrations/NNNN_name.sql`) are applied once and recorded
  with their SHA-256 in `schema_migrations`; an edited, already-applied
  migration is refused. `0001` is the frozen archive's exact schema.
- **Baseline:** `db init` copies every frozen row in (counts verified, archive
  hash recorded in `history_imports`), once.
- **Ingest** writes one capture run per transaction: `fetch_runs`,
  `fetch_attempts`, `sport_fetch_status`, then `capture_batches`, 120-second
  `quote_cohorts`, `events` and `market_quotes` (with Bovada market/outcome/price
  IDs). Re-ingesting an unchanged run is a no-op; changed capture JSON is an error.
- **Append-only:** triggers reject `UPDATE`/`DELETE` on evidence tables. New
  quotes must use the controlled status vocabulary.
- **Views:** `latest_quotes`, `line_movement` (one row per distinct snapshot —
  two runs that received the same cached object count once), `capture_health`,
  `sport_health`, plus the original `game_scoring_coverage`.

## Technical boundary

The database contains timestamped quotes and frozen model scores, **not**
authoritative Bovada account balances. `settlements` are matched game finals.
Simulated quote outcomes must not be presented as actual wager P&L.

Legacy rows keep their original conventions (some batches use team names as
`side`, `OPEN`/`MISSING` statuses, or non-Bovada `game_key` formats). They are
preserved as recorded; normalization belongs in separate versioned views.

The existing model code is not plug-and-play as a five-sport live pipeline.
Before promoting any adapter, run a verified parity test against the original
frozen scoring output and known point-in-time inputs.

Read `CLAUDE.md` for mandatory model and data safeguards and `ROADMAP.md` for
the incremental build.
