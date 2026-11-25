# Shared bet-sheet output contract

Each sport owns its implementation under `gambling/betsheets/<sport>/` and its spec under `docs/sports/<sport>.md`. The consolidated display uses the same fixed row schema across sports but may add genuinely sport-specific diagnostic fields.

## Required record-level fields

- `event_id`, `sport`, `start_time_utc`, `start_time_ct`, home/away, `market`, `selection`, `line`, book price (American and implied break-even)
- `quote_id`, `bookmaker`, `quote_as_of_utc`, `score_as_of_utc`, source/price freshness and coverage
- `model_family`, `model_release_id`, `model_role` (champion/challenger/shadow/research), `original_tier`, `original_wager_authorized`
- model and market probabilities, no-vig market reference if defined, `EV`, `Full_Kelly`, `Adjusted_Kelly`, algorithm/version for adjustments, research/approval state
- `status`, `status_reason`, `new_vs_previous`; recommended stake only when actually authorized
- current-model retrospective tier as a separate optional field; actual wager/ticket/settlement fields only from reconciled receipts

## Preservation and display requirements

Store **every** scored market-side row, including positive/zero/negative EV, `Pass`, `Lean`, blocked and unscorable rows. A `Pass` is an evaluated eligibility decision; missing inputs are `UNSCORED` or `BLOCKED`, never silently omitted. Render sportsbook lines and model values exactly at each original quote/score time. Ties/pushes refund when the applicable Bovada market rule says so; distinguish settle outcomes from probabilities.

Default chronological order is scheduled start (Central Time) then sport/event/market/side. The positive-EV in-chat summary is a **view**; Excel/CSV exports must include all records, full/adjusted Kelly when computable, original tier, model, statuses and source identities. A challenger or outside-model comparison is shown only if it has a real sourced/reproducible value; never fabricate an outside forecast.

## Golden fixture requirements

For each sport pin at least one complete historical board before changing code. Test event count, all markets, unknown/unsuitable odds handling, model version/tier, quote timestamp, EV/Kelly arithmetic, ordering, all non-positive rows and null reasons. Use the November 11 frozen bet sheet as historical evidence, not as proof of newer feature implementation.
