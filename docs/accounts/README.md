# Account data: Bovada exports → separate accounts database

**Status (2026-11-26):**
- Step 1 (profile) has run on the user PC and is import-ready. It reports 2,233 transactions with no gaps from Sep 20 to Nov 24, and **Sep 2–20 NOT_COVERED**.
- Step 2 (raw import) is implemented and verified on synthetic exports and on the real P&L baseline. It has not yet run on the real exports.
- Step 3 (DQ cleanse) is next.

## Rules (user, 2026-11-25)

- **Separate database:** actual account transactions go into a separate SQLite database, never the model scoring database (`data/gambling.sqlite`).
- **Source of truth:** the original exporter records (`*_pages.jsonl`) are what gets imported. The raw transactions are kept verbatim, and every DQ-01…DQ-12 transformation is recorded separately.
- **Report before import:** before any import, report coverage dates, transaction counts, missing periods, duplicates and reconciliation problems. A missing period is never treated as zero activity.
- **Kept out of Git:** exports, browser sessions and account information stay outside the public repository. `.gitignore` covers `bovada_transactions/*` (except the exporter script), `data/accounts/` and `*bovada_browser_profile*/`. Reports are written to `data/accounts/reports/`.

## Source files (`bovada_transactions/bovada_export/`, written by `bovada_transactions.py`)

| File | Role |
|---|---|
| `<stem>_pages.jsonl` | **Original source**: one raw API page per line, written as it arrives |
| `<stem>_run.json` | Run log: `created_at_from`, start and finish, item count per page, `stopped_because` |
| `<stem>.json`, `<stem>.csv` | Derived from the pages (first copy of each id wins). Checked against the pages and never imported in their place |

The API answers at most **31 days** back (`MAX_DAYS`). Anything older than the earliest run cannot be recovered from it.

## Step 1: profile (read-only)

```
python -m gambling accounts profile [--export-dir DIR] [--baseline gambling_pnl_2026-11-10.sqlite] [--since 2026-09-02]
```

The report is printed and written as `.md` and `.json` to `data/accounts/reports/`. The command exits with code 1 unless the exports are import-ready.

| Section | Content |
|---|---|
| Runs | Window start, finish, pages, raw and unique items, duplicates within the run, oldest and newest item, issues (incomplete run, broken page sequence, run log ≠ pages, derived file ≠ pages, missing pages file) |
| Coverage | Only **complete** runs count as covered. Every gap between their windows, and everything from `--since` to the first window, is reported as `NOT_COVERED` (activity unknown, not zero) |
| Counts | Raw vs unique transactions, items without an id, ids seen in several runs, ids whose versions differ across runs (with the fields that changed, such as a status change), wallet categories, delta totals |
| Balance chain | Each `aggregate.wallet.balance.total` = the previous balance + `delta.total`, in time order. This is checked per currency (one shared balance) and per wallet category, because Bovada's grouping is not documented. A break not explained by equal timestamps means transactions are missing |
| Baseline reconciliation | P&L baseline wagers whose `bovada_reference` / `source_transaction_id` appears in the raw items, split by whether they fall inside covered time |

**Import-ready** requires all of the following:
- every run complete;
- every item has an id;
- one balance grouping has no unexplained breaks.

## Step 2: raw import (`gambling/accounts/importer.py`)

```
python -m gambling accounts import [--export-dir DIR] [--baseline gambling_pnl_2026-11-10.sqlite] [--since 2026-09-02] [--db PATH]
```

The default target is `data/accounts/accounts.sqlite`, a separate file outside Git with its own migrations (`gambling/accounts/migrations/`). The import refuses to write to `gambling.sqlite`.

| Table | Content |
|---|---|
| `import_runs` | Each import: tool, the full profile it was gated on, counts |
| `export_runs` / `export_files` | Each exporter run, and its four files as verbatim bytes plus SHA-256 |
| `raw_pages` | Every line of `_pages.jsonl`, verbatim |
| `raw_transactions` | Every **distinct version** of a transaction: (id, content hash), canonical JSON, money as received strings |
| `transaction_sightings` | Every place each version was seen (run, line, position) |
| `coverage_windows` | `covers=1` only for complete runs; failed attempts are kept with `covers=0` |
| `latest_transactions` (view) | The latest version of each id |
| `pnl_baseline_<table>` + `pnl_baseline_imports` | All 16 tables of the P&L baseline, copied verbatim (verified row-for-row on the real file; sportsbook P&L −265,277 / stake 2,174,294 cents) |

Rules:
- **Gated:** the import refuses unless the profile is import-ready.
- **Atomic:** the whole import is one transaction.
- **Idempotent:** re-importing the same files adds nothing.
- **Immutable once imported:** changed files for an imported run are a conflict.
- **One baseline:** a different baseline file is a conflict.
- **Append-only:** every table rejects UPDATE and DELETE.

## Step 3 (next)
**Cleanse** with DQ-01…DQ-12 (`claude/IMPLEMENTATION_PLAN.md`) into canonical tables:
   - every transformation logged in `dq_issues`;
   - hard gates on totals and row conservation;
   - wager → score links kept only by key, across the two databases.
