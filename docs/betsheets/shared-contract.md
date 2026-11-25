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

## Implemented contract v2 (2026-11-25)

Implemented in `gambling/models/base.py` (adapter rows), `gambling/scoring/pricing.py`, `gambling/scoring/sheet.py` and `gambling/betsheets/export.py`; tested in `tests/test_scoring_v2.py`. Column order is `gambling.scoring.sheet.COLUMNS`.

**One row per (quoted side × release).** Six sides per ordinary game (`complete_board` adds explicit `NOT_OFFERED` rows); a release with no adapter row for a quote yields `UNSCORED / NO_ADAPTER_ROW_FOR_QUOTE`; nothing is dropped.

| `model_status` | Meaning | Probability fields |
|---|---|---|
| `SCORED` | Unconditional P(win/loss/push), sum 1 | `p_win`, `p_loss`, `p_push`; `push_probability_status` = `MODEL` or `ZERO_BY_LINE` |
| `CONDITIONAL_SCORED` | P(win \| decisive) only (decision 4, PR #4) | `p_win_given_decisive`; `p_push` null; `push_probability_status=UNKNOWN` |
| `EVALUATED` | Model assigned tier/action without a probability | none |
| `NOT_EVALUATED_BY_MODEL` | Quoted side the model did not evaluate; `original_tier=NONE` | none (see derived) |
| `UNSCORED` / `BLOCKED` | Missing inputs / failed gate, with reason | none |

A release that models a binary win probability is `SCORED` with `p_push=0` on half-point lines and two-way moneylines, and `CONDITIONAL_SCORED` on integer lines (`binary_probability_row`). The model's number is never altered.

**Derived complements (decision 3).** Only for `NOT_EVALUATED_BY_MODEL` sides whose opposite side has a model probability on the same market with a mirrored line (spread ±line, same total, moneyline). Unconditional: `derived_p_win = p_loss(selected)`, etc.; conditional: `derived_p_win_given_decisive = 1 − p`. `derived_probability_source=DERIVED_COMPLEMENT`. Derived rows get **no tier, EV, Kelly or eligibility**.

**Pricing.** `ev = b·p_win − p_loss` (`ev_basis=UNCONDITIONAL`) or `b·p − (1−p)` (`CONDITIONAL_DECISIVE`); `full_kelly = max(0,(b·p_win − p_loss)/(b·(p_win+p_loss)))` or the conditional single-bet diagnostic `max(0,(b·p − (1−p))/b)`. Negative-EV Kelly is `0.0`; absent values are null with `*_null_reason`. `legacy_ev` / `legacy_full_kelly` keep the frozen scorer's own numbers beside the recomputation.

**Adjusted Kelly.** Passed through only when the release computed it, with `adjusted_kelly_method` and `adjusted_kelly_certification` (`PORTFOLIO_CERTIFIED`, `LEGACY_NOT_PORTFOLIO_CERTIFIED`, `RELEASE_METHOD_AS_RECORDED`); otherwise null with `adjusted_kelly_null_reason` (default `NOT_SUPPLIED_BY_RELEASE`). Never computed by the shared layer, never zero-filled.

**Status (presentation only).** From the model's recorded `action_class` and registry authority at quote time: `PRODUCTION_QUALIFIED` (QUALIFIED + champion + wagering authorized), `QUALIFIED_NOT_WAGER_AUTHORIZED`, `RESEARCH_POSITIVE_EV`, `LEAN`, `PASS`, `EVALUATED_NO_ACTION`, `NOT_EVALUATED_BY_MODEL`, `UNSCORED`, `BLOCKED`, `QUOTE_NOT_OFFERED`. `original_tier`, `model_action` and `recorded_role` stay unchanged beside it.

**Exports.** CSV = every row. Excel: `All rows` (every row), `Champion vs Challenger` (same quote side, releases side by side), `Positive EV view` (labelled view; never includes derived complements), `Provenance & Legend`. `new_vs_previous` ∈ NEW / UNCHANGED / PRICE_CHANGED / LINE_CHANGED / STATUS_CHANGED / NO_PREVIOUS_SHEET.
