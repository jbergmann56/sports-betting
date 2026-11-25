"""Model adapters: one per registered release, probabilities only.

See ``base.py`` for the contract. Adapters wrap the frozen code in
``legacy_models/`` and must reproduce archived outputs (golden tests) before a
release is enabled for new scoring (ROADMAP Phase 2).
"""
from .base import Adapter, BLOCKED, SCORED, ScoreRow, UNSCORED

__all__ = ["Adapter", "ScoreRow", "SCORED", "UNSCORED", "BLOCKED"]
