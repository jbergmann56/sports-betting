# Account data: Bovada exports → separate accounts database

**Status (2026-11-26):**
- Step 1 (profile) has run on the user PC and is import-ready. It reports 2,233 transactions with no gaps from Sep 20 to Nov 24, and **Sep 2–20 NOT_COVERED**.
- Step 2 (raw import) is implemented and verified on synthetic exports and on the real P&L baseline. It has not yet run on the real exports.
- Step 3 (DQ cleanse) is implemented (`python -m gambling accounts cleanse`). All hard gates pass to the cent on the real P&L baseline (raw exports synthetic in that check). It has not yet run on the real exports.

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

## Step 3: DQ-01…DQ-12 cleanse (`gambling/accounts/cleanse.py`, migration `0002_cleanse`)

```
python -m gambling accounts cleanse [--db data/accounts/accounts.sqlite] [--scoring-db data/gambling.sqlite]
```

Input is the raw layer only: `pnl_baseline_*` and `latest_transactions`, which are never changed. Each run writes a `dq_runs` row (gates, summary, fingerprint) and every rule hit to `dq_issues` (raw value, cleansed value, action, evidence). Canonical `c_*` rows are written under the run id **only if every gate passes**. The views `wagers`, `open_wagers`, `accounting_adjustments`, `accounting_exclusions`, `non_sports_ledger` and `wager_links` read the latest PASSED run. All tables are append-only. A rerun on the same raw layer gives the same fingerprint.

| Rule | What it does |
|---|---|
| DQ-01 | "Settled — aggregate only" rows → `accounting_adjustments` (AGGREGATE_SETTLEMENT); kept in account totals, not ticket counts |
| DQ-02 | Win/Loss/Push → WIN/LOSS/PUSH; Push/Void → VOID only with void/cancel/refund text in the matched raw transactions, else PUSH (logged) |
| DQ-03 | Missing odds: raw API price, else back-solved for wins (must reproduce P&L to the cent), else UNRECOVERABLE; never imputed for losses |
| DQ-04 | Key = Bovada reference; raw match by reference in any field, else unique time (±60 s) + wallet delta = −stake; else synthetic `WB-` key |
| DQ-05 | UTC + precision; `.999` artifacts → next minute; placement time checked against the raw placement debit. A Chicago-local time labelled UTC is corrected from raw and logged; other disagreements are flagged, not changed |
| DQ-06 | Puck line → Spread; Grand Salami/Parlay/Prop out of model scope; direction from selection (Over/Under or team vs matchup) |
| DQ-07 | Away/home parsed; `game_key` crosswalk pending (logged) |
| DQ-08 | Non-sports key = Bovada id, else composite; collisions fail a gate |
| DQ-09 | Score links resolved to settled or open tickets; kept only if placement ≥ quote |
| DQ-10 | Optional score-id reconciliation against `gambling.sqlite` (read-only); the scoring DB stays authoritative |
| DQ-11 | Original frozen tier / pre-bet evidence kept apart from retrospective champion tier |
| DQ-12 | Upstream-excluded duplicate recorded; prior unallocated adjustment kept undated |

Hard gates: stake, itemized, prior, sportsbook account, casino, poker, bonus and all-gambling P&L equal the baseline metadata to the cent; 683 settled rows conserved; ticket arithmetic (LOSS = −stake, PUSH/VOID = 0, WIN = payout ±1 cent); unique keys; no key collisions; cash movements recognize 0; open tickets not also settled; every link resolves.

### DQ-13 raw ticket ledger (`gambling/accounts/ledger.py`, migration `0003_raw_tickets`)

Runs inside `accounts cleanse`. One `c_raw_tickets` row per Bovada bet reference, from the raw sportsbook transactions only:
- **Lifecycle:** PL (placed, debit of the risk) → ST (settled, credit of the payout; 0 for a loss) → US (unsettled, followed by a new ST) / VD (void, refund). Net P&L = sum of the wallet deltas across fund types (bonus funds included, as in the baseline). Result from the payout: 0 → LOSS, = risk → PUSH, > risk → WIN, in between → OTHER (flagged).
- **Coverage:** a ticket whose placement is before the covered raw time is `PLACEMENT_NOT_COVERED`; its P&L is settlement − risk field (`net_pnl_basis`), never zero.
- **Scope:** sport from the event path, market mapped (Asian handicap/puck line → Spread, Over/Under → Total, Head To Head → Moneyline). Parlays, live bets and other markets are `OUT_OF_MODEL_SCOPE`.
- **Baseline cross-check (gates):** every ticket in both the baseline and the raw exports must agree on net P&L and stake to the cent.
- **After the baseline:** view `tickets_after_baseline` = tickets not in the baseline, plus baseline-open tickets that have settled since. Non-sports activity (casino, poker, bonuses, cash) after the baseline is **not** in this ledger yet.
- **DQ-04/05 additions:** a baseline row whose `source_transaction_id` is a raw transaction gets the bet reference from it. Settlement times are verified against the final raw ST/VD like placement times.

### Verification on the real baseline (2026-11-26, raw exports synthetic)
- PASSED. Stake 2,174,294; itemized −265,277; prior −13,012; sportsbook account −278,289; casino −50,968; poker −8,486; bonus 250,013; all-gambling −87,730 (cents).
- 660 tickets + 23 aggregate adjustments = 683. All 23 odds-missing wins back-solved exactly; 37 odds stay UNRECOVERABLE (36 losses, 1 push). 382 directions derived; 3 unresolved (1 parlay, 1 prop, 1 spread).
- **Finding (resolved 2026-11-26):** for 166 evidence links (all "New" cohort), `scored_utc + scored_seconds_before_bet` lands exactly **+6.00 h** after the baseline `placed_at_utc`. Either those placement times are Chicago local time labelled as UTC, or the gap field is off by the offset. Resolved: the raw transactions show the baseline's "New"-cohort placement **and settlement** times are Chicago local time labelled UTC (180/180 placements, 181 settlements). DQ-05 corrects them from raw. Until then those links are dropped as `DROPPED_PLACED_BEFORE_QUOTE_TIME_UNVERIFIED` (238 dropped in total, 54 of them for unknown wagers).
- DQ-10 against the live scoring DB: 60 score ids only in the export, 289 only in the database. Export-only scores are not imported.

### Raw ledger check (2026-11-26, real baseline + Nov 2–24 exports)
- PASSED. 184 tickets in both the baseline and the raw exports: net P&L and stake agree to the cent for all 184.
- 414 baseline times corrected from raw (230 placements, 184 settlements); evidence links kept: 199.
- Not yet in the baseline, sportsbook only: 297 new tickets (stake $2,355.29, net −$153.60) and 50 baseline-open tickets since settled (stake $731.64, net −$458.78). Four of the new tickets were placed on the evening of Nov 10 Chicago time, after the baseline's last recorded ticket.
