"""Bovada account transactions, wagers, legs, wager-to-score links, P&L ledger.

Plan Phase 3. Layers: verbatim ``pnl_baseline_*`` import (read-only) ->
deterministic cleanse (rules DQ-01..DQ-12, every hit logged to ``dq_issues``)
-> canonical tables. Hard gates: totals reproduce to the cent and every
baseline row is accounted for. The exporter (bovada_transactions.py) moves here;
its browser profile must live outside the repository.

Implemented: ``exports`` (read-only pre-import profile of the exporter output; see
docs/accounts/README.md). Account transactions go to a SEPARATE database
(``data/accounts/accounts.sqlite``), never the model scoring database. Import and cleanse
follow after the profile is reviewed.
"""
