# Gambling project — Python migration, Phase 0

This is a **portable, offline, read-only export** of the November 11, 2026
Gambling project history and research observations. It is designed to be opened
in VS Code and developed with Claude Code, but ordinary Python can run it.

**Working now:** historical SQLite extraction, integrity audit, frozen scoring
replay, research-only parlay observation review, **reliable read-only Bovada
odds capture (`fetch`)**, and regression tests. The original model source files
and release manifests are bundled under `legacy_models/` for careful porting.

**Not yet working:** automatic fresh model scoring, appending captures to the
rolling SQLite history, historical feature update, real parlay book-price
capture, wager execution, personal transaction import, bonus settlement, or
autonomous bet sizing. Do not mistake historical saved EV for currently offered EV.

## Run locally

Requires Python 3.11+; the initial audit commands use only the standard library.

```powershell
python -m gambling init
python -m gambling audit
python -m gambling replay --date 2026-11-11
python -m gambling parlays --date 2026-11-11 --limit 8
python -m gambling fetch                       # all five sports, live
python -m gambling fetch --sports NBA,NHL      # subset
python -m gambling fetch --replay data/captures/<run_id>   # rebuild offline
python -m unittest discover -s tests -v
```

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
- Writes every attempt, including failures, append-only under
  `data/captures/<run_id>/` (raw body + headers + sha256), plus `manifest.json`,
  `board.json` and `quotes.csv`. Exit code 2 if any sport is `FAILED`/`BLOCKED`.

No sportsbook substitution, login, or wagering occurs.

The `data/` archive is the saved authoritative snapshot at Library version 28.
The extracted `history.sqlite` is a disposable local working copy. Keep the
archive immutable and back up any later local modifications separately.

## Technical boundary

The main SQLite file contains timestamped quotes and frozen model scores,
**not** authoritative Bovada account balances. `settlements` are matched game
finals. Simulated quote outcomes must not be presented as actual wager P&L.

The existing model code and data are not plug-and-play as a five-sport live
pipeline; those source packages have differing vintage and assumptions.
Before promoting any adapter, run a verified parity test with the original
frozen scoring output and known point-in-time inputs.

Read `CLAUDE.md` for mandatory model and data safeguards and `ROADMAP.md` for
the recommended incremental build.
