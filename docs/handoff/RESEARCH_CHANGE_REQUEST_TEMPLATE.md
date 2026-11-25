# Model research change request — TEMPLATE

> Duplicate this into `docs/research/decisions/YYYY-MM-DD-<sport>-<topic>.md`. Do not mark approved until the user has explicitly approved a scoped promotion.

## Identity

- Created date / researcher:
- Sport, market and proposal slug:
- Proposed status: `RESEARCH` / `SHADOW` / `CHALLENGER` / `PRODUCTION-CANDIDATE`:
- Baseline champion release ID and repository SHA:
- Candidate release ID (new ID for any probability/tier/calibration logic change):
- Owner/branch:

## Research evidence and point-in-time population

- Source archive(s), immutable SHA256 and paths:
- Train, validation, untouched holdout, prospective windows:
- Exact eligible events/markets/price source and cutoff:
- Number of available vs scored vs excluded vs settled events:
- Missing data and leakage checks:
- Book rule for push/void/refund:
- Same-game price/quote matching protocol:
- External model source and timestamp (if applicable):

## Algorithm and output specification

- Mathematical model and feature definitions:
- Parameters/posteriors/calibration and versioned files:
- Original role/tier gates, proposed differences:
- EV, Full Kelly and Adjusted Kelly semantics:
- Expected scored output/columns and reason codes:
- What existing outputs must remain byte/row equivalent:

## Validation results

- Frozen fixture(s) and expected model P / tier / EV / Kelly:
- Reliability, log loss/Brier, sample counts, uncertainty:
- Paired champion-vs-candidate analysis at identical quoted odds:
- Out-of-sample growth/ROI outcomes and limitations:
- Risk of overfit, multiple comparisons, regime drift and parameter uncertainty:
- Golden regression/test commands and pass criteria:

## Decision, scope and safety

- Research recommendation:
- User's explicit decision (quote/date/link; or `NOT YET APPROVED`):
- Permitted implementation changes:
- Explicitly forbidden changes:
- Rollback trigger:
- Wager authorization (default `NO`):
- Claude PR and implementation report link:
- ChatGPT post-implementation assessment:
