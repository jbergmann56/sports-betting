"""Odds arithmetic shared across the package."""

from __future__ import annotations


def american_to_decimal(american: float) -> float:
    a = float(american)
    if -100 < a < 100:
        raise ValueError(f"Not a valid American price: {american}")
    return 1 + (a / 100 if a > 0 else 100 / -a)


def break_even_probability(american: float | None) -> float | None:
    """Implied probability of a single price, vig included. None if no price."""
    if american is None:
        return None
    a = float(american)
    if -100 < a < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)
