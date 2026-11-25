# Streamlit frontend — workstream contract

The **October 2025** Streamlit tracker is archived unchanged under `legacy/v1_app/`. It is not the current multi-sport model UI and does not meet the 2026 frozen release/quote authority contract.

The new frontend belongs at `apps/streamlit/` and on workstream branch `ui/streamlit`. It must import stable shared APIs from `gambling/`; no UI-specific copies of EV, Kelly, tier or settlement logic. Required views: full sport bet sheets including Pass/Lean/Unscorable; champion/challenger source/provenance; live quote freshness; actual settled wager P&L separate from hypothetical score outcomes; model registry/validation; research-only parlays and bonuses.

**Current state:** UI directory is reserved; not yet implemented or deployed. Promotion requires a smoke test and sample fixture checks. Do not use historical `legacy/v1_app/app.py` as a production entrypoint without a separate migration and review.
