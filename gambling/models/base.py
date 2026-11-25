"""Contract between frozen model code and the scoring layer.

An adapter turns one game's pregame inputs into one ``ScoreRow`` per quoted
market side. It never assigns tier, EV or authorization -- that is
``gambling.scoring``'s job, using the model registry. Missing inputs produce
``UNSCORED``/``BLOCKED`` rows with a reason, never a guessed probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence

SCORED = "SCORED"
UNSCORED = "UNSCORED"   # inputs missing or market outside model scope
BLOCKED = "BLOCKED"     # inputs present but failed a gate (stale, post-start, unmatched team)
_STATUSES = {SCORED, UNSCORED, BLOCKED}
_TOL = 1e-9


@dataclass(frozen=True)
class ScoreRow:
    release_id: str
    quote_id: str
    status: str
    p_win: Optional[float] = None
    p_loss: Optional[float] = None
    p_push: Optional[float] = None
    reason: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        probs = (self.p_win, self.p_loss, self.p_push)
        if self.status == SCORED:
            if any(p is None for p in probs):
                raise ValueError("SCORED rows need p_win, p_loss and p_push")
            if any(p < -_TOL or p > 1 + _TOL for p in probs):
                raise ValueError("probabilities must lie in [0, 1]")
            if abs(sum(probs) - 1.0) > 1e-6:
                raise ValueError("p_win + p_loss + p_push must equal 1")
        else:
            if any(p is not None for p in probs):
                raise ValueError(f"{self.status} rows must not carry probabilities")
            if not self.reason:
                raise ValueError(f"{self.status} rows need a reason")


class Adapter(Protocol):
    """One registered model release (see ``model_releases``)."""

    release_id: str
    sport: str
    markets: Sequence[str]

    def score(self, game: Mapping[str, Any], quotes: Sequence[Mapping[str, Any]],
              features: Optional[Mapping[str, Any]]) -> list[ScoreRow]:
        """Return one row per quote in ``quotes`` (never silently skip one)."""
        ...
