# Model-input store (`md_*` tables in `data/gambling.sqlite`)

**Status (2026-11-25):** migration `0006_model_data`, import pipeline and reproduction proof implemented
in `gambling/modeldata/`. Proven on a copy of the history database rebuilt from the frozen archive: the
five golden fixtures replay identically from inputs materialized from the database, and the 19
pre-existing tables are unchanged. **Not yet applied to the user's real `data/gambling.sqlite`** (M1 in
`ROADMAP.md`). MySQL/Azure was dropped by user decision; there is one SQLite file and one migrator.

## 1. Purpose and scope

One versioned store that ChatGPT research and Claude development both read, so a model evaluation and
a model implementation use byte-identical inputs.

| In scope | Out of scope (separate accounts database) |
|---|---|
| Historical games and results, odds snapshots, team ratings, pregame feature snapshots, frozen replay inputs, predictions, evaluation results, run pins | Sportsbook wagers, tickets, account transactions, balances, bonuses, deposits/withdrawals, any personal account data |

Separation is enforced in two ways. First, no wager or account tables exist in `md_*`. Second, the
importer's column guard rejects account and wager exports outright: any column matching `wallet`,
`balance`, `ticket`, `wager_id`, `bovada_reference`, `transaction_id`, `deposit`, `withdraw`, `payout`
or `bonus`. The only existing bridge between scores and wagers is `wager_links` (migration 0002);
nothing here reads or writes it.

## 2. How it fits the existing data model

The store is a migration of the rolling history database, not a second database. It reuses what
already exists rather than duplicating it.

| Existing object (0001–0005) | How `md_*` uses it |
|---|---|
| `schema_migrations` + `gambling/db/migrate.py` | 0006 is applied, hash-checked and recorded by the same migrator. There is no separate `schema_versions`. |
| `model_releases`, `model_release_status`, `release_status_history` | `md_run_releases.release_id` and `md_evaluation_results.release_id` are foreign keys to `model_releases`. There is no second registry. `register_run` refuses an unregistered release; releases are added only by a reviewed registry migration. Authority is still read from `model_release_status`. |
| `model_release_aliases` | Frozen `model_scores` rows carry legacy `model_version` labels; their release is resolved through the aliases (see the `OnFrozenHistory` test). |
| `capture_batches`, `quote_cohorts` | `md_model_runs.batch_id` and `quote_cohort_id` are foreign keys, so a run says which board it scored. |
| `model_scores` | `md_run_score_links(run_id, score_id)` records which existing score rows a run reproduces. |
| `events.game_key`, `market_quotes`, `official_game_results` | `md_dataset_rows.game_key` holds the same key when an import names `--game-key-column`. The view `md_rows_by_game` joins inputs to quotes, scores and results. |
| `source_files` (capture files per batch) | Unchanged and unrelated. Model-input evidence lives in `md_source_files`, and the `md_` prefix prevents the name clash. |
| Sport vocabulary (`NBA`, `NHL`, `NCAAFB`, `NCAABB`, `NFL`) | Enforced by `CHECK` on `md_datasets.sport` and `md_model_runs.sport`. |

0006 only creates objects. It alters no existing table, view or trigger.

## 3. Design principles

1. **Original bytes are evidence.** Every file is stored whole (1 MiB chunks), keyed by SHA-256, and can be re-materialized byte-for-byte. Parsed rows are a convenience view, never a replacement.
2. **Append-only.** Triggers reject `UPDATE` and `DELETE` on every `md_*` table. Lifecycle changes (STAGED → PUBLISHED → SUPERSEDED/RETRACTED) are appended events.
3. **Versions, not edits.** A dataset changes only by adding a version, and a label can never point at different bytes.
4. **Time-safe by construction.** Each version records `available_from_utc`, the time its content was knowable. Rows can carry a per-row time column. Retrieval takes a cutoff.
5. **Runs pin their inputs.** A run records exactly which bytes sat at which path. Re-materializing the run reproduces the original working directory.
6. **Atomic writes.** Each source registration and each version import is one transaction (`BEGIN IMMEDIATE`), so a failed import leaves nothing behind.

## 4. Schema (`gambling/db/migrations/0006_model_data.sql`)

| Table | Purpose | Key columns |
|---|---|---|
| `md_source_files` | Immutable file evidence | `sha256` PK, `bytes`, `original_name`, `media_type`, `sensitivity`, `provenance`, `parent_sha256`/`parent_member_path`, `chunk_count` |
| `md_source_file_chunks` | File bytes | (`sha256`, `chunk_no`), `data` BLOB |
| `md_datasets` | Logical dataset | `dataset_id`, `domain` (games/results/odds/ratings/features/predictions/evaluations/reference/replay_input), `sport` |
| `md_dataset_versions` | Immutable version | `version_id`, `version_label` (unique per dataset), `source_sha256`, `parser`, `available_from_utc`, `time_column`, `game_key_column`, `row_count`, `content_sha256`, `parent_version_id` |
| `md_dataset_version_events` | Status history | `status`, `reason`, `actor`, `event_utc` |
| `md_dataset_columns` | Column catalog | `ordinal`, `name`, `source_dtype`, `flagged` (USER_OBSERVATION_FLAG / REVIEWED_MODEL_FIELD) |
| `md_dataset_rows` | Lossless rows | (`version_id`, `row_no`), `row_time_utc`, `game_key`, `row_sha256`, `row_json` (JSON array of source text values) |
| `md_model_runs` | Reproducible run | `run_id`, `run_kind` (GOLDEN_FIXTURE/REPLAY/LIVE/RESEARCH), `sport`, `batch_id`→`capture_batches`, `quote_cohort_id`→`quote_cohorts`, `input_cutoff_utc`, `environment_json`, `scorer_json` |
| `md_run_releases` | Releases a run executed | (`run_id`, `release_id`→`model_releases`) |
| `md_run_inputs` | Pinned bytes per staged path | (`run_id`, `stage_path`), `role` (INPUT/EXPECTED_OUTPUT/ARCHIVE/MANIFEST), `source_sha256`, `version_id` |
| `md_run_results` | Each execution | `executed_utc`, `input_source`, `status`, `report_json` |
| `md_run_score_links` | Scores a run reproduces | (`run_id`, `score_id`→`model_scores`), `basis` |
| `md_evaluation_results` | Research metrics by reference | `release_id`→`model_releases`, `metric`, `population`, `value_num`, `n_obs`, CI, `research_ref` |

Views: `md_dataset_version_status` (latest status per version) and `md_rows_by_game` (rows with a `game_key`).

## 5. Provenance and sensitivity

Every source carries free-text `provenance` (URL, capture ID, or package name + SHA-256 + member path)
and one of three classifications:

- `PUBLIC_MARKET`: bookmaker quotes, public schedules and results.
- `MODEL_INTERNAL`: model inputs, controls, outputs, archives.
- `CONTAINS_USER_OBSERVATION_FLAGS`: research data that marks which games the user observed (for example, the NCAABB master's `actual_bet_status`; stakes are zero). Required whenever unreviewed flag-like columns are present.

Model-generated columns whose names resemble staking fields (NCAABB V4 `stake_eligible`,
`health_stake_multiplier`, `cash_bet_status`) are accepted only with a written per-column
justification, and are recorded as `REVIEWED_MODEL_FIELD`.

## 6. Retrieval

```python
from gambling.modeldata import open_store
s = open_store("data/gambling.sqlite")
vid = s.version_as_of("bovada/quotes/all", "2026-11-12T14:00:00Z")   # latest PUBLISHED version knowable then
rows = s.rows(vid, as_of_utc="2026-11-12T13:45:00Z")                 # rows whose time column <= cutoff
s.materialize_run("NBA_R4_20261112", Path("work"))                    # exact original input files
```

```sql
-- model inputs for one game alongside its quotes and official result
SELECT r.dataset_id, r.row_json, q.market, q.side, q.odds_american, o.final_home_score, o.final_away_score
FROM md_rows_by_game r
JOIN latest_quotes q ON q.game_key = r.game_key
LEFT JOIN settlements o ON o.game_key = r.game_key
WHERE r.game_key = ?;
```

`version_as_of` ignores STAGED and RETRACTED versions. `rows(..., as_of_utc)` excludes untimed rows unless
`include_untimed=True` is passed. A historical model retrieves its exact original inputs through its run
pins, not by re-querying "latest" data.

## 7. Import pipeline

`python -m gambling.modeldata [--db PATH]`. The database is `--db`, else `$GAMBLING_DB`, else `data/gambling.sqlite`.

| Command | Effect |
|---|---|
| `migrate` | Apply pending migrations through `gambling/db/migrate.py` |
| `import FILE --dataset --domain --label --sensitivity --provenance [--sport] [--time-column] [--game-key-column] [--available-from] [--review-column N=why] [--publish]` | Preserve the bytes; parse (CSV, CSV.gz, Parquet via `pyarrow`, JSON array, or blob); guard columns; create the version; verify it is lossless |
| `publish` / `retract VERSION --reason` | Append a status event |
| `status DATASET` | List versions and their current status |
| `materialize-source SHA DEST`, `materialize-run RUN DEST` | Re-create the exact files |
| `verify [VERSION ...]` | Re-parse the preserved bytes and compare every row hash |
| `snapshot DEST.sqlite` | Consistent online-backup copy plus `DEST.sqlite.sha256`, for sharing with ChatGPT or offline backup. Never overwrites. |
| `golden [--external DIR]` | Import the five golden fixtures (plus the frozen ZIP and the NCAABB externals) and replay them from the database |

Staged research files (for example, the 2023 NCAAFB candidates in
`docs/handoff/LOCAL_INPUT_INVENTORY_2026-11-24.md`) are imported as `STAGED`. They are not published
without ID, deduplication and provenance review.

## 8. Reproduction proof (2026-11-25)

The database was a copy of `gambling.sqlite` rebuilt from the frozen archive: 28 batches, 6,936 quotes,
10,173 scores, 42.5 MB, SHA-256 `2b8e3365…`. Command:
`python -m gambling.modeldata --db COPY golden --external <reproducibility package>`.

| Fixture | Inputs from repo | Inputs materialized from `md_*` |
|---|---|---|
| NFL_20261110_072712CST | PASSED | PASSED |
| NHL_DAY0_20261112 | PASSED | PASSED |
| NCAAFB_20261102 | PASSED | PASSED |
| NBA_R4_20261112 | PASSED | PASSED |
| NCAABB_V4_20261101 | PASSED | PASSED |

The import produced 48 sources and 37 versions. The runs reference 13 registered releases through
`md_run_releases`. All 19 pre-existing tables hash identically before and after the migration and import.

## 9. Applying to the real database (M1)

1. Make a verified offline backup of `data/gambling.sqlite` with `snapshot` or a file copy plus SHA-256, stored outside the repository.
2. Copy the file, run `python -m gambling.modeldata --db COPY migrate`, and confirm the counts (32 batches, 10,158 quotes, 10,173 scores) and the hashes of the existing tables are unchanged.
3. Only then migrate the live file. `python -m gambling db` applies 0006 automatically the next time the database is opened, so step 1 must come first.

## 10. Backup and recovery

- `python -m gambling.modeldata snapshot <outside-repo>/gambling_YYYYMMDD.sqlite` uses SQLite's online backup, so the copy is consistent while the database is open. The `.sha256` file is written next to it.
- Keep weekly and monthly snapshots off the machine. Never commit a snapshot: `*.sqlite` is gitignored.
- Restore test: open a snapshot copy, run `verify` and `golden`; both must pass.
- Source evidence is content-addressed, so any file can be re-registered from its original copy, and the re-registration must reproduce the same SHA-256.

## 11. Known limitations

- Rows store values as text in source order: lossless, but not typed. Typed projections (odds, features) are a later migration.
- **Size:** each source is stored once as chunks and once as parsed rows. Importing the 81 MB NCAABB external inputs grows the file by about 260 MB (the proof copy went from 42 MB to 303 MB). Run the golden proof on a copy. Decide separately whether the live file should hold the NCAABB master, or only its SHA-256 and a pointer.
- The NCAABB master carries user-observation flags (`CONTAINS_USER_OBSERVATION_FLAGS`). A snapshot that includes it must not be shared publicly.
- `md_dataset_rows.game_key` is not a foreign key, because `events` is keyed by `(batch_id, sport, event_id)` and a game appears in many batches. Joins go through `md_rows_by_game`.
