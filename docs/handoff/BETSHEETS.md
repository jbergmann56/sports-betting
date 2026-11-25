# Bet-sheet contracts and presentation requirements for Claude

## Purpose and status

The user treats each sport's bet sheet as the **complete scored research ledger**, not just a short list of suggested bets. [PRIOR-DISCUSSION] The approved requirements below come from the Gambling research workflow; they are design requirements, **not proof of current code implementation**. [REPO-VERIFIED] The baseline contract lives in `docs/betsheets/shared-contract.md`; `gambling/betsheets/{nfl,ncaafb,nba,nhl,ncaabb}/` currently contains scaffolding.

## Non-negotiable master export

Create a reproducible **Excel workbook** for each requested refresh, plus CSV/JSON outputs where useful. [PRIOR-DISCUSSION] Every scored game/market/side row is present, including:

- positive EV, zero EV, negative EV
- `A` / `B+` / `B` / `Lean` / `Pass`, with **original** tier, role and release
- `UNSCORED` / `BLOCKED`, with why a prediction, quote, odds, model, feature or sizing value is absent
- research-only and shadow/challenger predictions **clearly not authorized** as wagers.

Separate **model scoring state**, **eligibility/tier**, and **wager-authorization status**. A market can be positively scored but unauthorized; a missing quote cannot be labelled "Pass".

Required fields: start time **in Central Time** and UTC, book, capture as-of timestamp, matchup, event ID, market/side/line, original quoted odds, champion/challenger/model release ID, original tier, model P(win)/P(push)/P(loss), EV, Full Kelly, **Adjusted Kelly where genuinely calculated**, signal status, original approval/authorization, comparison-model probabilities/EV where sourced, new vs previously seen, and actual wager IDs only where receipt evidence exists. Record null reason separately rather than setting missing Kelly to 0.

**Chronology:** sort by actual kickoff/tip/puck-drop time first, with stable tie-breakers. [PRIOR-DISCUSSION] Distinguish new candidate signals from unchanged previously seen signals.

**ChatGPT summary:** show positive-EV rows only when user asks for a chat bet sheet, including model, EV, original tier, Full Kelly and Adjusted Kelly when available. This is a **view**; the complete workbook must retain all scored, negative and Pass rows. A research-only positive-EV result cannot become a recommendation solely because it appears in this view.

**Odds:** Bovada primary source; preserve exact observed quoted lines and American odds, do not replace missing prices with alternatives. Support ties/pushes as refund whenever applicable to the actual Bovada market rules, including any Grand Salami rules. Different markets may settle differently: retain specific market metadata, not blanket win/loss assumptions.

## Separate layers

1. `raw_quotes` / capture: book response, raw line, side, timestamp, status.
2. `score_records`: immutable point-in-time model P and reasons; do not overwrite previous scores.
3. `derived_pricing`: quoted EV, break-even, push probability, Full and Adjusted Kelly with methodology and version.
4. `eligibility`: original tier, candidate status, production approval/authorization, provenance.
5. `betsheet_export`: all rows plus optional filtered views; user-facing presentation never edits historical data.
6. `actual_wagers`: confirmed tickets, stakes, outcomes, promos and settlements, separately reconciled.

## Sport-specific notes

| Sport | Notes |
|---|---|
| NFL | Spread, ML, totals, champion REV2-CAL versus challengers; historical SRS/rest regimes and provenance. |
| NCAAFB | Spread PP V2 vs continuous challenger; shared ML and research Under component not counted twice; explicit conditional-decisive/push caveats. |
| NBA | Champion R4/V27 vs R3 challenger; outside `Dunks & Threes` EV comparison [PRIOR-DISCUSSION] only with real same-time sourced forecast. Never blanket Pass earlier-supported Spread B / ML B+ cohorts without evaluation. |
| NHL | ML, puck line, totals and **separately governed** Grand Salami totals/spread; research status, adjusted Kelly blocked as documented; model/segment historical P&L and P&L per bet where real outcomes are available. |
| NCAABB | V4 production candidate, V5 shadow, T-Rank outside challenger [PRIOR-DISCUSSION]; defer KenPom paid integration until evaluated. |

## EV and Kelly math (reference only)

For American odds, the net win multiple is `b = odds/100` for plus prices, `b=100/abs(odds)` for minus prices. For three outcomes (win, loss, refund push) when `p_win+p_loss+p_push=1`:

- `EV = b*p_win - p_loss` per $1 risk, assuming push returns stake and no fees.
- `Full Kelly = max(0, (b*p_win - p_loss)/(b*(p_win+p_loss)))` for independent repeated bets with push refund, if computed for the standard one-bet fractional stake and `p_win+p_loss>0`. In no-push cases this reduces to `max(0, (b*p_win-p_loss)/b)`. Validate conventions against the frozen sport authority before reporting.
- Adjusted Kelly is **not a uniform fractional multiplier**. It is the relevant frozen algorithm's uncertainty-aware/joint portfolio result, if implemented; otherwise `N/A` with a reason (for example unresolved exposure or no validated algorithm).

Keep model calibration, uncertainty and stake recommendations separate; producing a mathematical Kelly diagnostic does not authorize a bet. Do not substitute implied market probability for a missing independently calibrated model.

## Acceptance tests before using a sport bet sheet operationally

- All six main sides per ordinary game where offered; store explicit missing/suspended statuses.
- Complete history, negative and zero EV, Pass, Lean, blocked, no-quote rows; no silent omissions.
- Golden replay vs same archived bookmaker snapshot, model release, actual original tier and probability.
- Sort stability, same-game de-duplication, equivalent team normalization, original/new status.
- Correct push refunds, whole-number lines, market-specific settlement treatment.
- Model plus outside baseline comparisons only where time-aligned and provenance-complete.
- No stale / post-start / unknown-line signals falsely shown as current available bets.
- All percentages and Kelly fields have explicit units and null reasons.
