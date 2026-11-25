"""Model adapters: one per registered release, probabilities only.

See ``base.py`` for the v2 contract. Adapters wrap the frozen code in
``legacy_models/`` and must reproduce archived outputs (``tests/golden``)
before a release is enabled for new scoring.
"""
from .base import (
    ACTION_CLASSES, LEAN, PASS, QUALIFIED, RESEARCH_POSITIVE_EV,
    BLOCKED, CONDITIONAL_DECISIVE, CONDITIONAL_SCORED, EVALUATED, NOT_EVALUATED_BY_MODEL,
    PUSH_MODEL, PUSH_NOT_APPLICABLE, PUSH_UNKNOWN, PUSH_ZERO_BY_LINE, SCORED, STATUSES,
    UNCONDITIONAL, UNSCORED, Adapter, ScoreRow, binary_probability_row, push_possible,
)

__all__ = [
    "Adapter", "ScoreRow", "binary_probability_row", "push_possible", "STATUSES",
    "SCORED", "CONDITIONAL_SCORED", "EVALUATED", "NOT_EVALUATED_BY_MODEL", "UNSCORED", "BLOCKED",
    "UNCONDITIONAL", "CONDITIONAL_DECISIVE",
    "ACTION_CLASSES", "QUALIFIED", "RESEARCH_POSITIVE_EV", "LEAN", "PASS",
    "PUSH_MODEL", "PUSH_ZERO_BY_LINE", "PUSH_UNKNOWN", "PUSH_NOT_APPLICABLE",
]
