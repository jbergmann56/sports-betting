"""Contract between frozen model code and the scoring layer (adapter interface v2).

An adapter turns one game's pregame inputs into one ``ScoreRow`` per **quoted
market side** (normally six per ordinary game). It reports what the frozen
model actually produced and nothing more:

* probabilities exactly as the model defines them (unconditional, or
  conditional on a decisive / non-push result),
* the model's own recorded tier, signal and action text,
* a model-specific Adjusted Kelly only when the release computes one, with its
  method and certification,
* explicit reasons whenever something is absent.

It never computes EV, Full Kelly, tier policy or wager authorization -- those
belong to ``gambling.scoring`` and the model registry. It never invents a
probability: a side the model did not evaluate is ``NOT_EVALUATED_BY_MODEL``.
Complementary probabilities for such sides are derived (and labelled) by
``gambling.scoring.complement``, never by adapters.

Statuses (``ScoreRow.status``):

``SCORED``                unconditional P(win), P(loss), P(push) summing to 1
``CONDITIONAL_SCORED``    P(win | decisive) only; push probability unknown
``EVALUATED``             model evaluated the side (tier/signal) without a probability
``NOT_EVALUATED_BY_MODEL`` quoted side the model did not evaluate; no tier, no P
``UNSCORED``              inputs missing or market outside model scope (reason required)
``BLOCKED``               inputs present but a gate failed (stale, post-start, unmatched team)

v1 compatibility: positional construction ``ScoreRow(release_id, quote_id,
status, p_win, p_loss, p_push, reason)`` is unchanged; every v2 field is
keyword-only with a neutral default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence

SCORED = "SCORED"
CONDITIONAL_SCORED = "CONDITIONAL_SCORED"
EVALUATED = "EVALUATED"
NOT_EVALUATED_BY_MODEL = "NOT_EVALUATED_BY_MODEL"
UNSCORED = "UNSCORED"
BLOCKED = "BLOCKED"
STATUSES = (SCORED, CONDITIONAL_SCORED, EVALUATED, NOT_EVALUATED_BY_MODEL, UNSCORED, BLOCKED)

# probability_basis
UNCONDITIONAL = "UNCONDITIONAL"
CONDITIONAL_DECISIVE = "CONDITIONAL_DECISIVE"

# push_probability_status
PUSH_MODEL = "MODEL"                 # push probability supplied by the release
PUSH_ZERO_BY_LINE = "ZERO_BY_LINE"   # half-point line / two-way moneyline: push impossible
PUSH_UNKNOWN = "UNKNOWN"             # push possible, release supplies no estimate
PUSH_NOT_APPLICABLE = "NOT_APPLICABLE"

# action_class: the frozen scorer's own recorded decision, mapped (not recomputed)
QUALIFIED = "QUALIFIED"                    # model's production-tier qualifying signal
RESEARCH_POSITIVE_EV = "RESEARCH_POSITIVE_EV"
LEAN = "LEAN"
PASS = "PASS"
ACTION_CLASSES = (QUALIFIED, RESEARCH_POSITIVE_EV, LEAN, PASS)

# adjusted_kelly_certification
AK_PORTFOLIO_CERTIFIED = "PORTFOLIO_CERTIFIED"
AK_LEGACY_NOT_CERTIFIED = "LEGACY_NOT_PORTFOLIO_CERTIFIED"
AK_RELEASE_METHOD = "RELEASE_METHOD_AS_RECORDED"

_TOL = 1e-9
_PROB_STATUSES = (SCORED, CONDITIONAL_SCORED)
_NO_PROB_STATUSES = (EVALUATED, NOT_EVALUATED_BY_MODEL, UNSCORED, BLOCKED)


def _in_unit(p: float) -> bool:
    return -_TOL <= p <= 1 + _TOL


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
    # ---- v2 (keyword-only) ------------------------------------------------
    p_win_given_decisive: Optional[float] = field(default=None, kw_only=True)
    probability_basis: Optional[str] = field(default=None, kw_only=True)
    push_probability_status: Optional[str] = field(default=None, kw_only=True)
    recorded_role: Optional[str] = field(default=None, kw_only=True)
    original_tier: Optional[str] = field(default=None, kw_only=True)
    model_signal: Optional[str] = field(default=None, kw_only=True)
    model_action: Optional[str] = field(default=None, kw_only=True)
    action_class: Optional[str] = field(default=None, kw_only=True)
    legacy_ev: Optional[float] = field(default=None, kw_only=True)
    legacy_full_kelly: Optional[float] = field(default=None, kw_only=True)
    adjusted_kelly: Optional[float] = field(default=None, kw_only=True)
    adjusted_kelly_method: Optional[str] = field(default=None, kw_only=True)
    adjusted_kelly_certification: Optional[str] = field(default=None, kw_only=True)
    adjusted_kelly_null_reason: Optional[str] = field(default=None, kw_only=True)
    score_as_of_utc: Optional[str] = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        s = self.status
        if s not in STATUSES:
            raise ValueError(f"unknown status {s!r}")
        probs = (self.p_win, self.p_loss, self.p_push)
        if s == SCORED:
            if any(p is None for p in probs):
                raise ValueError("SCORED rows need p_win, p_loss and p_push")
            if not all(_in_unit(p) for p in probs):
                raise ValueError("probabilities must lie in [0, 1]")
            if abs(sum(probs) - 1.0) > 1e-6:
                raise ValueError("p_win + p_loss + p_push must equal 1")
            if self.probability_basis not in (None, UNCONDITIONAL):
                raise ValueError("SCORED rows are unconditional")
            if self.push_probability_status == PUSH_UNKNOWN:
                raise ValueError("SCORED rows cannot have an unknown push probability")
        elif s == CONDITIONAL_SCORED:
            if self.p_win_given_decisive is None or not _in_unit(self.p_win_given_decisive):
                raise ValueError("CONDITIONAL_SCORED rows need p_win_given_decisive in [0, 1]")
            if any(p is not None for p in probs):
                raise ValueError("CONDITIONAL_SCORED rows must not carry unconditional probabilities")
            if self.probability_basis != CONDITIONAL_DECISIVE:
                raise ValueError("CONDITIONAL_SCORED rows need probability_basis=CONDITIONAL_DECISIVE")
            if self.push_probability_status != PUSH_UNKNOWN:
                raise ValueError("CONDITIONAL_SCORED rows need push_probability_status=UNKNOWN")
        else:
            if any(p is not None for p in probs) or self.p_win_given_decisive is not None:
                raise ValueError(f"{s} rows must not carry probabilities")
            if s == EVALUATED and not (self.original_tier or self.model_signal or self.model_action):
                raise ValueError("EVALUATED rows need the model's tier, signal or action")
            if s == NOT_EVALUATED_BY_MODEL and self.original_tier not in (None, "NONE"):
                raise ValueError("NOT_EVALUATED_BY_MODEL rows cannot carry a model tier")
            if s in (UNSCORED, BLOCKED, NOT_EVALUATED_BY_MODEL) and not self.reason:
                raise ValueError(f"{s} rows need a reason")
        if self.action_class is not None and self.action_class not in ACTION_CLASSES:
            raise ValueError(f"unknown action_class {self.action_class!r}")
        if self.action_class is not None and s in (NOT_EVALUATED_BY_MODEL, UNSCORED, BLOCKED):
            raise ValueError(f"{s} rows cannot carry a model action")
        if self.adjusted_kelly is not None:
            if not self.adjusted_kelly_method or not self.adjusted_kelly_certification:
                raise ValueError("adjusted_kelly needs adjusted_kelly_method and adjusted_kelly_certification")

    @property
    def has_probability(self) -> bool:
        return self.status in _PROB_STATUSES


def binary_probability_row(*, release_id: str, quote_id: str, p_win: float, push_possible: bool,
                           **kwargs: Any) -> ScoreRow:
    """Build a row from a release that models a binary win/loss probability.

    If a push is impossible for the quoted line (half-point spread/total, two-way
    moneyline) the probability is unconditional with P(push)=0 explicit.
    Otherwise the release's number is, by construction, P(win | decisive) and the
    push probability is UNKNOWN (research decision 4, PR #4). The model's number
    is never altered.
    """
    if push_possible:
        return ScoreRow(release_id, quote_id, CONDITIONAL_SCORED,
                        p_win_given_decisive=p_win, probability_basis=CONDITIONAL_DECISIVE,
                        push_probability_status=PUSH_UNKNOWN, **kwargs)
    return ScoreRow(release_id, quote_id, SCORED, p_win, 1.0 - p_win, 0.0,
                    probability_basis=UNCONDITIONAL, push_probability_status=PUSH_ZERO_BY_LINE, **kwargs)


def push_possible(market: str, line: Optional[float]) -> bool:
    """True when the quoted line can push (integer spread/total). Two-way moneyline never pushes."""
    if market.lower() in ("moneyline", "ml"):
        return False
    if line is None:
        return True  # unknown line: do not assume a push is impossible
    return abs(line - round(line)) < 1e-9


class Adapter(Protocol):
    """One registered model release (see ``model_releases``)."""

    release_id: str
    sport: str
    markets: Sequence[str]

    def score(self, game: Mapping[str, Any], quotes: Sequence[Mapping[str, Any]],
              features: Optional[Mapping[str, Any]]) -> list[ScoreRow]:
        """Return exactly one row per quote in ``quotes`` (never silently skip one)."""
        ...
