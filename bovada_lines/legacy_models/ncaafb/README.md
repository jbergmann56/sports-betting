# NCAA football champion/challenger tiers — November 2, 2026

All 62 games / 186 markets use the Bovada quote snapshot captured November2 at9:13AM Central. The odds were not refreshed again during this tier comparison. Model inputs are updated through completed Week9 games endingOctober31. No calibration refit, model promotion, historical-dataset replacement or wager execution occurred.

Champion: partial-pooling V2, adoptedOctober28, unchanged probability calibration. Challenger: original frozen continuous posterior fromOctober23, unchanged; the separate updated continuous RESEARCH version is not substituted. Only the spread component differs between these two model configurations. ML and PFPA Under research rules are shared components, not independent corroborating forecasts.

Spread results: TexasState+6.5−105 is B+ provisional in both. Cincinnati+11−110, MissouriState+4.5−112, Vanderbilt+3−108, OleMiss+3.5−110 and WestVirginia+17−110 are challenger B provisional and champion Pass. All remaining spreads Pass.

Shared ML: Akron+390, Arkansas+325, Marshall+310, NorthernIllinois+310 and UTEP+290 carry the existing TierA rule label. Fixed+0.10logodds uplift and unresolved historical ML calibration-population limitation remain. IowaState+290 is B descriptive because Baylor publishedSRS10.06 is above the<10 gate; it receives no uplift or normal allocation. CharlotteML+320 is unresolved because current published UAB SRS was not recoverable from primary pages; a stale4-3 page is not substituted. Do not classify that missing gate as Pass.

Shared totals: UTSA–FAUUnder72−110 and Marshall–GeorgiaSouthernUnder55−112 are researchLean with zero normal allocation. Existing54/99 research calibration is preserved. No validated production total is promoted.

Probability/EV/FullKelly for spreads are conditional on a decisive result. Whole lines have unestimated push probability; no exact-line uplift or unconditional EV is invented. AdjustedKelly means posterior-aware joint portfolio allocation, not an extra sample-size haircut. It was not calculated here because current exposure is not reconciled. Missing adjusted values are unavailable, not zero; researchLean adjusted allocation is explicitly zero. Neither probability magnitude nor FullKelly alone promotes a tier.

Data reconstruction: original FBS-v-FBS least-squares SRS, +2.5 nonneutral home field, four-checkpoint slope, and expanding Week8+ Z denominator are preserved. Features for all56 Week9 games reproduce saved slopes and Z to <1e-10 before rolling forward to Week10. Scores are sourced from the prior verified Week8/9 result files and ESPN's October27 scoreboard, all included. Pregame model probabilities are not refitted on those recent results. The historical master remains unchanged.

Files: results/ALL_62_GAMES_BOTH_MODEL_TIERS.csv includes every Pass and the one unresolved ML gate; results/POSITIVE_EV_BOTH_MODEL_TIERS.csv lists rows positive in either configuration. It includes researchLeans, which are not production bets. FullKelly and adjusted-sizing availability are shown. Model authority, raw odds, result provenance, weekly ratings and parity verification are bundled.

Reproduce with Python and pandas/numpy/scipy: run `python build_features.py`, then `python score_both.py` from this extracted folder. These commands use frozen bundled inputs and do not fetch or place bets.
