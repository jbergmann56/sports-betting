# Reconciliation of recorded history against the frozen adapters (2026-11-25)

**What was compared:** every `model_scores` row recorded in the user's `data/gambling.sqlite` (SHA-256 `ef84f3a0…`, Nov 12 state) for NHL and NBA, replayed through the frozen adapters with inputs rebuilt **from the database's own captures**. Read-only; reproduced in CI from the bundled frozen archive (`tests/test_reconcile.py`). Command: `python -m gambling reconcile --sport NHL|NBA [--batch ID]`.

## NHL (Day-0 champions + challengers), Nov 6–11

| Result | Rows |
|---|---|
| Probability and EV reproduce exactly (|Δ| ≤ 1e-9) | **552 / 552** Day-0 rows, 6 batches (Nov 7–11) |
| … of which the spread side came from `selection_display` (ingested without `selection_side`) | 64 |
| Not replayable: recorded model is not a Day-0 release (`NHL_V15_FROZEN_MORNING`, `NHL_DAY0_APPROX_FROM_ROUNDED_EV`, Nov 6) | 6 |

The capture `quotes.csv` was rebuilt from `market_quotes` + `events`; the unchanged scorer and frozen controls (`4b6119a0…`, the hash recorded on every row) did the rest.

## NBA (R4 V27 champion), Nov 6–11

| Batch (slate) | Rows | Result | History used |
|---|---|---|---|
| FIVE_SPORT Nov 6 | 27 | exact, incl. intermediates | frozen history, games before slate |
| FIVE_SPORT Nov 7 (05:59Z preview) | 21 | exact | **before the Nov 6 finals** (`BEFORE_PREVIOUS_DAY_FINALS`) |
| FIVE_SPORT Nov 8 | 21 | exact | frozen |
| FIVE_SPORT Nov 9, 10, 11 | 24 + 18 + 27 | exact | **Nov 8 Pelicans @ Clippers as "LA Clippers"** (`NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS`) |
| NBA_*_R4_R3 (Nov 9 21:54Z; Nov 10 15:34Z, 18:11Z) | 24 + 18 + 18 | **decisions exact** (tier, selection, odds, probability, EV); intermediates differ by up to 0.02 pts (unexplained) | either |

"Intermediates" are the scorer's structural values (model home margin, predicted total, structural win probability), which depend on the features/history and the market line; matching them proves the scorer saw the same inputs.

### Findings (for ChatGPT review; nothing changed)

1. **Clippers row rename in the frozen history.** The original Nov 9–11 runs had the Nov 8 Pelicans @ Clippers final under "LA Clippers"; the frozen R4 history (`nba_history_through_2026-11-11.csv`, written by the Nov 11 manual-finals script) records it as "Los Angeles Clippers". With that one row restored, all three slates reproduce exactly. The V27 features treat the two names as different teams, so the archived **Nov 12 R4 forecast (golden fixture `NBA_R4_20261112`) was scored on a different history than the Nov 9–11 runs**. The history also uses "Los Angeles Clippers" for 2018–2026-11-08 and "LA Clippers" for 6 of the 10 2026/27 rows. Any correction is a research decision and a new release; the frozen release and fixture stay as they are.
2. **The Nov 7 preview ran on stale history** (before the Nov 6 finals). Correct point-in-time behaviour for that run; recorded so the archived numbers are not mistaken for errors.
3. **Afternoon `R4_R3` batches** reproduce every decision from their own quotes, but their recorded intermediates do not match a replay from either their own or the morning quotes. The inputs that produced those intermediates are not identifiable from the database.
4. **Ingest gap:** NHL spread rows in the `FIVE_SPORT` batches were stored without `selection_side`; older NBA `*_R4_R3` captures store sides as team names with status `OPEN`. Reconciliation maps both explicitly; the ingest itself is unchanged.

## Not reconciled

- **NFL:** the frozen archive holds only the Nov 10 board (already 72/72 in the adapter tests). Other NFL batches need the capture → `board.json` converter (backlog B8/B10).
- **NCAAFB / NCAABB:** the recorded batches need the daily feature inputs of those runs, which are not in the database.
