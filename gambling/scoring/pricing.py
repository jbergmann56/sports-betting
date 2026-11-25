"""Push-aware EV and Full Kelly from a model probability and a quoted price.

Conventions (``docs/handoff/BETSHEETS.md``, research decision 4 in PR #4):

* ``b`` = net win multiple: ``odds/100`` for plus prices, ``100/|odds|`` for minus.
* Unconditional (p_win, p_loss, p_push sum to 1, push refunds the stake):
  ``EV = b*p_win - p_loss`` per unit risked;
  ``Full Kelly = max(0, (b*p_win - p_loss) / (b*(p_win + p_loss)))``.
* Conditional on a decisive result (p = P(win | decisive), push probability
  unknown): ``EV_decisive = b*p - (1-p)``; unconditional EV is unknown (only its
  sign is implied). Full Kelly ``max(0, (b*p - (1-p))/b)`` is the stand-alone
  maximizer for a refunded push and is labelled a conditional single-bet
  diagnostic, not a portfolio size.

These are pure arithmetic diagnostics. They never create eligibility, tiers or
authorization, and Adjusted Kelly is never computed here (see ``kelly_adjusted``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from gambling.models.base import CONDITIONAL_SCORED, SCORED, ScoreRow

EV_UNCONDITIONAL = "UNCONDITIONAL"
EV_CONDITIONAL = "CONDITIONAL_DECISIVE"
FK_SINGLE_BET = "SINGLE_BET_UNCONDITIONAL"
FK_CONDITIONAL = "CONDITIONAL_SINGLE_BET_DIAGNOSTIC"


def net_multiple(american_odds: float) -> float:
    if american_odds == 0:
        raise ValueError("American odds of 0 are invalid")
    return american_odds / 100.0 if american_odds > 0 else 100.0 / abs(american_odds)


def break_even(american_odds: float) -> float:
    b = net_multiple(american_odds)
    return 1.0 / (1.0 + b)


@dataclass(frozen=True)
class Pricing:
    ev: Optional[float]
    ev_basis: Optional[str]
    ev_null_reason: Optional[str]
    full_kelly: Optional[float]
    full_kelly_basis: Optional[str]
    full_kelly_null_reason: Optional[str]
    break_even: Optional[float]


def price(row: ScoreRow, american_odds: Optional[float]) -> Pricing:
    if american_odds is None:
        return Pricing(None, None, "NO_OFFERED_PRICE", None, None, "NO_OFFERED_PRICE", None)
    b = net_multiple(american_odds)
    be = 1.0 / (1.0 + b)
    if row.status == SCORED:
        pw, pl = row.p_win, row.p_loss
        ev = b * pw - pl
        if pw + pl <= 0:
            return Pricing(ev, EV_UNCONDITIONAL, None, None, None, "NO_DECISIVE_PROBABILITY", be)
        fk = max(0.0, (b * pw - pl) / (b * (pw + pl)))
        return Pricing(ev, EV_UNCONDITIONAL, None, fk, FK_SINGLE_BET, None, be)
    if row.status == CONDITIONAL_SCORED:
        p = row.p_win_given_decisive
        ev = b * p - (1.0 - p)
        fk = max(0.0, (b * p - (1.0 - p)) / b)
        return Pricing(ev, EV_CONDITIONAL, None, fk, FK_CONDITIONAL, None, be)
    reason = {"EVALUATED": "MODEL_ASSIGNS_NO_PROBABILITY",
              "NOT_EVALUATED_BY_MODEL": "NOT_EVALUATED_BY_MODEL",
              "UNSCORED": "UNSCORED", "BLOCKED": "BLOCKED"}[row.status]
    return Pricing(None, None, reason, None, None, reason, be)


@dataclass(frozen=True)
class AdjustedKelly:
    value: Optional[float]
    method: Optional[str]
    certification: Optional[str]
    null_reason: Optional[str]


def kelly_adjusted(row: ScoreRow) -> AdjustedKelly:
    """Pass through the release's own Adjusted Kelly with its method; never compute one.

    A missing value is reported as null with a reason, never as 0.
    """
    if row.adjusted_kelly is not None:
        return AdjustedKelly(row.adjusted_kelly, row.adjusted_kelly_method, row.adjusted_kelly_certification, None)
    if not row.has_probability:
        return AdjustedKelly(None, None, None, row.adjusted_kelly_null_reason or "NO_MODEL_PROBABILITY")
    return AdjustedKelly(None, None, None, row.adjusted_kelly_null_reason or "NOT_SUPPLIED_BY_RELEASE")
