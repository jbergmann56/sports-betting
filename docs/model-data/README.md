# Model-input database (`gambling_model_data`)

**Status (2026-11-25):** schema v0001, import pipeline and reproduction proof implemented in
`gambling/modeldata/`; proven on a local MySQL 8.0.46 server and on SQLite. **Not yet deployed to
Azure** (the existing Azure server could not be reached from the development session; see §8).
The existing SQLite scoring history (`gambling/db`, `data/gambling.sqlite`) is unchanged and remains
the operational record until this store is independently validated (§9).

## 1. Purpose and scope

One authoritative, versioned store that ChatGPT research and Claude development both read, so a
model evaluation and a model implementation use byte-identical inputs.

| In scope | Out of scope (separate `gambling_accounts` database, separate credentials) |
|---|---|
| Historical games and results, odds snapshots, team ratings, pregame feature snapshots, frozen replay inputs, model release mirror, predictions, evaluation results, run pins | Sportsbook wagers, tickets, account transactions, balances, bonuses, deposits/withdrawals, any personal account data |

The separation is enforced three ways: no wager/account tables exist in this schema; the importer's
column guard rejects account/wager exports outright (`wallet`, `balance`, `ticket`, `wager_id`,
`bovada_reference`, `transaction_id`, `deposit`, `withdraw`, `payout`, `bonus`); and the database
users for this schema hold no privilege on the accounts database.

## 2. Design principles

1. **Original bytes are evidence.** Every file is stored whole (1 MiB chunks) keyed by SHA-256 and can be re-materialized byte-for-byte. Parsed rows are a convenience view, never a replacement.
2. **Append-only.** Triggers reject `UPDATE`/`DELETE` on evidence tables; the writer role has no `UPDATE`/`DELETE` grant. Lifecycle changes (STAGED → PUBLISHED → SUPERSEDED/RETRACTED) are appended events.
3. **Versions, not edits.** A dataset changes only by adding a version; a label can never point at different bytes.
4. **Time-safe by construction.** Each version records `available_from_utc` (when the content was knowable); rows can carry a per-row time column. Retrieval takes a cutoff.
5. **Runs pin their inputs.** A run records exactly which bytes sat at which path; re-materializing the run reproduces the original working directory.

## 3. Schema (`gambling/modeldata/schema/{mysql,sqlite}/0001_model_data.sql`)

| Table | Purpose | Key columns |
|---|---|---|
| `source_files` | Immutable file evidence | `sha256` PK, `bytes`, `original_name`, `media_type`, `sensitivity`, `provenance`, `parent_sha256`/`parent_member_path` (archive members), `chunk_count` |
| `source_file_chunks` | File bytes | (`sha256`, `chunk_no`), `data` LONGBLOB |
| `datasets` | Logical dataset | `dataset_id`, `domain` (games/results/odds/ratings/features/predictions/evaluations/reference/replay_input), `sport` |
| `dataset_versions` | Immutable version | `version_id`, `dataset_id`, `version_label` (unique per dataset), `source_sha256`, `parser`, `available_from_utc`, `time_column`, `row_count`, `column_count`, `content_sha256`, `parent_version_id` |
| `dataset_version_events` | Status history | `status` STAGED/PUBLISHED/SUPERSEDED/RETRACTED, `reason`, `actor`, `event_utc` |
| `dataset_columns` | Column catalog | `ordinal`, `name`, `source_dtype`, `flagged` (USER_OBSERVATION_FLAG / REVIEWED_MODEL_FIELD) |
| `dataset_rows` | Lossless rows | (`version_id`, `row_no`), `row_time_utc`, `row_sha256`, `row_json` (values as text, source order) |
| `model_releases` | Mirror of the SQLite registry | `release_id`, `sport`, `markets_json`, `artifact_status`, `mirrored_from` |
| `model_runs` | Reproducible run | `run_id`, `run_kind` (GOLDEN_FIXTURE/REPLAY/LIVE/RESEARCH), releases, `input_cutoff_utc`, environment, scorer files+hashes |
| `run_inputs` | Exact inputs | (`run_id`, `stage_path`), `role` (INPUT/EXPECTED_OUTPUT/ARCHIVE/MANIFEST), `source_sha256`, `version_id` |
| `run_results` | Execution log | `input_source` (REPO_FIXTURE/MODEL_DATA_DB), `status`, `report_json` |
| `evaluation_results` | Research metrics | `release_id`, `population_version`, `metric`, `value_num`, `n_obs`, `ci_low/high`, `research_ref` |
| view `dataset_version_status` | Current status per version | latest event |

`content_sha256` = SHA-256 over the ordered row hashes; `row_sha256` = SHA-256 of the canonical JSON
array. `verify_version` re-parses the preserved bytes and compares every row hash.

Typed projections (e.g. `odds_snapshots`, `feature_snapshots`) are a planned v0002: they will be
populated from published raw versions by validated mappers, never by editing raw rows.

## 4. Provenance and sensitivity

Every source carries free-text `provenance` (URL, capture id, package name + SHA-256 + member path)
and one of three classifications:

- `PUBLIC_MARKET` — bookmaker quotes, public schedules/results.
- `MODEL_INTERNAL` — model inputs, controls, outputs, archives.
- `CONTAINS_USER_OBSERVATION_FLAGS` — research data that marks which games the user observed (e.g. NCAABB master `actual_bet_status`; stakes are zero). Required whenever unreviewed flag-like columns are present.

Model-generated columns whose names resemble staking fields (NCAABB V4 `stake_eligible`,
`health_stake_multiplier`, `cash_bet_status`) are accepted only with a written per-column
justification and recorded as `REVIEWED_MODEL_FIELD`.

## 5. Retrieval

```python
from gambling.modeldata import connect
s = connect(os.environ["GAMBLING_MODELDATA_URL"])
vid = s.version_as_of("bovada/quotes/all", "2026-11-12T14:00:00Z")   # latest PUBLISHED version knowable then
rows = s.rows(vid, as_of_utc="2026-11-12T13:45:00Z")                 # rows whose time column <= cutoff
s.materialize_run("NBA_R4_20261112", Path("work"))                    # exact original input files
```

`version_as_of` ignores STAGED and RETRACTED versions. `rows(..., as_of_utc)` excludes untimed rows unless
`include_untimed=True`. A historical model retrieves its exact original inputs through its run pins, not by
re-querying "latest" data.

## 6. Import pipeline

`python -m gambling.modeldata` (URL from `--url` or `GAMBLING_MODELDATA_URL`):

| Command | Effect |
|---|---|
| `migrate` | Apply schema files once (hash-checked; MySQL preflight for trigger privileges) |
| `import FILE --dataset --domain --label --sensitivity --provenance [--time-column] [--available-from] [--review-column N=why] [--publish]` | Preserve bytes, parse (CSV, CSV.gz, Parquet via `pyarrow`, JSON array, or blob), guard columns, create version, verify lossless |
| `publish` / `retract VERSION --reason` | Append a status event |
| `status DATASET` | Versions and current status |
| `materialize-source SHA DEST`, `materialize-run RUN DEST` | Re-create exact files |
| `verify [VERSION ...]` | Re-parse preserved bytes; compare all row hashes |
| `golden [--external DIR]` | Import the five golden fixtures (+ frozen ZIP, + NCAABB externals) and replay them from the database |

Frozen replay artifacts: the frozen archive ZIP and each fixture's inputs, expected outputs and manifest
are stored as sources and pinned to `GOLDEN_FIXTURE` runs. Staged research files (e.g. the 2023 NCAAFB
candidates in `docs/handoff/LOCAL_INPUT_INVENTORY_2026-11-24.md`) are imported as `STAGED` and are not
published without ID/deduplication/provenance review.

## 7. Reproduction proof (2026-11-25)

`python -m gambling.modeldata golden --external <reproducibility package>`: every fixture's files were
re-materialized **from the database only** and the unchanged scorers were run against them.

| Backend | Sources | Versions | Rows | NFL | NHL | NCAAFB | NBA | NCAABB |
|---|---:|---:|---:|---|---|---|---|---|
| MySQL 8.0.46 (local) | 48 | 37 | 88,432 | PASSED | PASSED | PASSED | PASSED | PASSED |
| SQLite 3 | 48 | 37 | 88,432 | PASSED | PASSED | PASSED | PASSED | PASSED |

Also verified on MySQL: 37/37 versions lossless; triggers reject UPDATE/DELETE on `dataset_rows`,
`source_files`, `dataset_versions`, `run_inputs`; re-import is idempotent (48/37/88,432 unchanged); ~100 MB
of preserved source bytes (dominated by the 81 MB NCAABB inputs). Model probabilities, EV and tiers are
unchanged because the scorers and their outputs are compared under the golden rule
(`docs/golden-fixtures.md`).

## 8. Azure Database for MySQL setup (reuse existing server)

The archived v1 app (`legacy/v1_app/config.py`) connected to Azure MySQL via `AZURE_MYSQL_HOST`,
`AZURE_MYSQL_USER`, `AZURE_MYSQL_PASSWORD`, `AZURE_MYSQL_DATABASE`, `AZURE_MYSQL_PORT`. Its database also holds
v1 `bets`/`bankroll_history` tables, so **do not reuse that database** — create `gambling_model_data` on the
same server.

1. Confirm the server still exists and is MySQL 8.0 (Azure portal; Flexible Server recommended).
2. Server parameters: `require_secure_transport=ON`; `log_bin_trust_function_creators=ON` (binary logging is on in Azure; without this the migrator cannot create the append-only triggers — the preflight stops before any DDL).
3. Run `gambling/modeldata/schema/mysql/grants.example.sql` as admin: `modeldata_migrator` (DDL), `modeldata_writer` (SELECT/INSERT only), `modeldata_reader` (SELECT).
4. Download the Azure CA certificate; set `GAMBLING_MODELDATA_URL=mysql://modeldata_migrator:…@<host>:3306/gambling_model_data?ssl_ca=<path>` in `.env` (never committed).
5. `pip install -e .[mysql,models]`; `python -m gambling.modeldata migrate`; then switch the URL to `modeldata_writer` and run `python -m gambling.modeldata golden --external <package>`. Acceptance = 5/5 PASSED recorded in `run_results` with `input_source=MODEL_DATA_DB`.
6. Firewall: allow only the development machine / CI egress addresses.

## 9. Migration process (gated; SQLite stays authoritative until M5)

| Gate | Work | Acceptance |
|---|---|---|
| M0 ✅ | Schema, importer, local MySQL + SQLite proof | 5/5 golden from DB; lossless; append-only |
| M1 | Provision on Azure (§8) | `migrate` clean; preflight passes |
| M2 | Golden import + proof on Azure | 5/5 PASSED in `run_results` |
| M3 | Read-only import of history: capture `quotes.csv` files → `odds` versions (`time_column=snapshot_as_of_utc`); frozen archive members; ESPN finals; recovered feature inputs | `verify` lossless; counts reconcile to `gambling db status` |
| M4 | Dual run: adapters read inputs from the model-data store while `data/gambling.sqlite` remains the record; per-run parity reports | identical scores for every run over ≥ 2 weeks |
| M5 | Independent validation (ChatGPT) and a recorded decision to make the model-data store authoritative for model inputs | decision record in `docs/research/decisions/` |

Rollback at any gate: stop reading from MySQL; the SQLite history and repo fixtures are untouched.

## 10. Backup and recovery

- **Platform:** Azure automated backups with point-in-time restore (retention configurable 1–35 days; set ≥ 14) and geo-redundant backup storage if available on the tier.
- **Logical:** weekly `mysqldump --single-transaction --triggers --routines --hex-blob gambling_model_data | gzip`; record the dump's SHA-256 and row counts; keep 12 weekly + 12 monthly copies off-server (encrypted). Never commit dumps to Git.
- **Restore test (monthly):** restore the latest dump into a scratch database, run `python -m gambling.modeldata verify` and `golden`; both must pass. Record the result in `run_results` of the scratch database and in `ROADMAP.md`.
- Source evidence is content-addressed, so any file can also be re-registered from its original copy; a re-registration must reproduce the same SHA-256.

## 11. Known limitations

- Rows store values as text in source order (lossless, not typed); typed projections are v0002.
- Local MySQL 8.0.46 is not Azure; Azure-specific behaviour (TLS, parameters, firewall) is unverified until M1.
- MariaDB is not a supported target (JSON and trigger semantics differ).
- The NCAABB inputs (81 MB) are stored as source evidence; at larger scale move chunks to Azure Blob Storage keyed by the same SHA-256 (schema unchanged except a storage URI column).
