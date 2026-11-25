# Wager, performance, parlay and bonus research requirements

## Source separation

[REPO-VERIFIED] `gambling/db/` records historic **quotes and model scores** in SQLite, with frozen matched game finals. A simulated quote result is not a user's real wager settlement. The `bovada_transactions/bovada_transactions.py` file is present, but a complete personal wager-account and P&L integration is **not certified**.

[PRIOR-DISCUSSION] User wants actual Bovada wagers, settlements, book balance activity, rollover credits, cashbacks, promotions, external deposits/withdrawals, and exceptions consolidated into the application. This must use evidence-backed unique transaction IDs, ticket IDs, legs, odds, original stake, whether placed, stake risk, settlement status, refund/void/push, net P&L and promo credit. Do not infer stake or bonus qualification from model outputs.

Keep distinct:
1. **Theoretical ROI/P&L** of frozen paper bets and eligible model signals.
2. **Recorded recommendations** and original predicted EV, role, tier, score time and price.
3. **Actually placed wagers** and corrected/voided settlements.
4. **Account transaction records** (casino/poker vs sports vs transfer vs bonus).
5. **Earned bonus values and verified bonus rollover progress** under applicable terms.
6. Exposure/available bankroll: only from reconciled current account/ticket data, never reuse the historical `$1,000` bankroll from a research scenario.

## Performance reports

- Total settled stake, net P&L, ROI, yield, wins/losses/pushes/voids, unresolved items, realized vs modeled EV; date and source coverage.
- Break down by sport, model and *release*, market (spread/ML/total/Grand Salami), original tier, home/away, rest/B2B/3-in-4/4-in-6 when supported, seasonal period, and relevant sport-specific signal.
- [PRIOR-DISCUSSION] NHL bet sheets need model name, segment, total historical P&L and P&L **per bet**; other sports may also use these.
- Respect original-time segments and eligibility; never retroactively label an actual wager with only a newly fitted tier.
- Separate championship/playoff games and early/late-season historical segments where meaningful.
- Reconcile matched/unmatched/unverifiable wagers explicitly, with coverage tables before interpreting ROI.

## Parlay methodological requirements

[PRIOR-DISCUSSION] User wants independent **distinct physical games**, across sports **or within one sport**; no multi-leg same-game parlays of the disallowed type. Relative independence may be the default research approximation, but **do not claim exact independence**. Shared feature shocks, weather, line movement, closing market shifts and multiple correlated tickets can create material dependency; test such cases instead of asserting none.

Inputs: candidate legs with immutable quote ID, same-cohort observed bookmaker price, champion/research authorization, calibrated joint assumptions, actual offered parlay price, push/refund rules, payout and rollover promotion eligibility. Never substitute the multiplied individual prices for an observed sportsbook parlay quote. The frozen `data/20261111_theoretical_parlays.csv` contains hypothetical research combinations, not real ticket offers.

Compare candidate singles and multi-leg tickets on **both**:
- Expected log portfolio growth/risk conditional on current exposure, and
- Bonus qualification speed, value and likelihood of reaching each active deadline.

[PRIOR-DISCUSSION] With an **active** bonus, user prioritizes reaching its qualifying turnover first, portfolio growth second, **while still assessing both**. Rank opportunities among singles and parlays accordingly, with explicit rule/credit assumptions. Example prior scenario: $1,000 bankroll; two bonus turnover targets 16,000 and 2,750 at October/November 2026 deadlines. These are **expired historical inputs**, not current active targets. Never carry them into new recommendations.

## Validation protocol

1. Import source receipts and capture entire applicable wager lifecycle; deduplicate but never discard conflicts.
2. Confirm timezone, settlement rule, bet/casino categorization, promo contribution rate, cancellation/void treatment, and bonus cutoff.
3. Reconcile bank/book account activity against ticket-level settle totals; show unresolved variance separately.
4. Reconstruct both model-at-recommendation score and actually accepted price; avoid invented placed bets.
5. Test parlay quote availability, same-game prohibition, potential dependencies, push handling and turnover credit; no automatic wager execution.

No branch or statistical report may treat a theoretical backtest return as realized bankroll profit.
