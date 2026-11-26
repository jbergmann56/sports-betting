# Account data: Bovada exports → separate accounts database

**Status (2026-11-25):** step 1 of 3 implemented. The pre-import profile is ready; the import waits until the user has reviewed it.

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

## Steps 2–3 (after review)

2. **Import** into `data/accounts/accounts.sqlite`, a separate file:
   - verbatim raw pages and transactions, append-only and keyed by Bovada id, with every version kept;
   - coverage windows recorded as their own rows, so reports can mark unknown periods;
   - the P&L baseline as frozen rows.
3. **Cleanse** with DQ-01…DQ-12 (`claude/IMPLEMENTATION_PLAN.md`) into canonical tables:
   - every transformation logged in `dq_issues`;
   - hard gates on totals and row conservation;
   - wager → score links kept only by key, across the two databases.
