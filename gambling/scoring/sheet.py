"""Assemble complete bet-sheet rows: every quoted side x every release, all statuses.

Inputs are normalized quote sides (``gambling.core.quotes``), adapter rows
(``gambling.models.base.ScoreRow``) and registry authority at quote time. Output
is one row per (quote side, release) in the fixed column order ``COLUMNS``.

What this layer does and does not do:

* Keeps the frozen model's original tier, action text and probabilities
  unchanged in their own columns.
* Adds push-aware EV/Full Kelly arithmetic (``pricing``) with explicit basis and
  null reasons, and passes through Adjusted Kelly only as the release supplied it.
* Derives a complement probability for a side the model did not evaluate only
  when mathematically justified (research decision 3, PR #4): same market,
  mirrored line, and the model's estimate covers the complete event. The
  derived value sits in ``derived_*`` columns with
  ``derived_probability_source=DERIVED_COMPLEMENT``; it gets no tier, no EV, no
  Kelly and no status other than ``NOT_EVALUATED_BY_MODEL``.
* ``status`` is a presentation label composed from the model's recorded action
  and the registry's authorization at quote time. It never re-evaluates
  eligibility, and the original fields remain beside it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from gambling.core.quotes import MARKET_ORDER, OPPOSITE, SIDE_ORDER, QuoteSide
from gambling.models.base import (
    CONDITIONAL_DECISIVE, CONDITIONAL_SCORED, NOT_EVALUATED_BY_MODEL, QUALIFIED, SCORED, UNCONDITIONAL, ScoreRow,
)
from gambling.scoring.pricing import kelly_adjusted, price

CENTRAL = ZoneInfo("America/Chicago")
ROLE_ORDER = {"CHAMPION": 0, "CHALLENGER": 1, "SHADOW": 2, "RESEARCH": 3}

COLUMNS = [
    "sport", "event_id", "start_time_utc", "start_time_ct", "away", "home",
    "market", "side", "selection", "line", "american_odds", "break_even",
    "quote_id", "bookmaker", "quote_as_of_utc", "quote_status",
    "model_release_id", "release_role", "release_scoring_authority", "release_wager_authorized",
    "recorded_role", "score_as_of_utc", "model_status", "status_reason",
    "original_tier", "model_signal", "model_action", "action_class",
    "probability_basis", "push_probability_status",
    "p_win", "p_loss", "p_push", "p_win_given_decisive",
    "derived_probability_source", "derived_probability_basis", "derived_p_win", "derived_p_loss",
    "derived_p_push", "derived_p_win_given_decisive",
    "ev", "ev_basis", "ev_null_reason",
    "full_kelly", "full_kelly_basis", "full_kelly_null_reason",
    "adjusted_kelly", "adjusted_kelly_method", "adjusted_kelly_certification", "adjusted_kelly_null_reason",
    "legacy_ev", "legacy_full_kelly", "status", "new_vs_previous",
]


@dataclass(frozen=True)
class ReleaseAuthority:
    release_id: str
    role: str
    scoring_authority: bool
    wagering_authorized: bool


class Authority:
    """Registry authority lookup at quote time (``release_status_history``)."""

    def __init__(self, history: Sequence[Mapping]):
        self._rows = sorted(history, key=lambda r: (r["release_id"], r["effective_from_utc"]))

    @classmethod
    def from_sqlite(cls, path: str) -> "Authority":
        import sqlite3
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "select release_id, role, scoring_authority, wagering_authorized, effective_from_utc, "
            "effective_until_utc from release_status_history")]
        con.close()
        return cls(rows)

    def at(self, release_id: str, when_utc: str) -> Optional[ReleaseAuthority]:
        chosen = None
        for r in self._rows:
            if r["release_id"] != release_id:
                continue
            start, end = r["effective_from_utc"], r.get("effective_until_utc")
            if (start is None or start <= when_utc) and (end is None or when_utc < end):
                chosen = r
        if chosen is None:
            return None
        return ReleaseAuthority(release_id, chosen["role"], bool(chosen["scoring_authority"]),
                                bool(chosen["wagering_authorized"]))


def _ct(utc: str) -> str:
    if not utc:
        return ""
    dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    return dt.astimezone(CENTRAL).strftime("%Y-%m-%d %I:%M %p CT")


def _mirrored(a: QuoteSide, b: QuoteSide) -> bool:
    if a.market != b.market or OPPOSITE.get(a.side) != b.side:
        return False
    if a.market == "Moneyline":
        return True
    if a.line is None or b.line is None:
        return False
    if a.market == "Spread":
        return abs(a.line + b.line) < 1e-9
    return abs(a.line - b.line) < 1e-9  # Total


def derive_complement(selected: ScoreRow, sel_q: QuoteSide, opp_q: QuoteSide) -> Optional[dict]:
    """Labelled mathematical complement for the opposite side, or None if not justified."""
    if not _mirrored(sel_q, opp_q):
        return None
    if selected.status == SCORED:
        return dict(derived_probability_source="DERIVED_COMPLEMENT", derived_probability_basis=UNCONDITIONAL,
                    derived_p_win=selected.p_loss, derived_p_loss=selected.p_win, derived_p_push=selected.p_push)
    if selected.status == CONDITIONAL_SCORED:
        return dict(derived_probability_source="DERIVED_COMPLEMENT", derived_probability_basis=CONDITIONAL_DECISIVE,
                    derived_p_win_given_decisive=1.0 - selected.p_win_given_decisive)
    return None


def _status(q: QuoteSide, s: ScoreRow, auth: Optional[ReleaseAuthority]) -> str:
    if not q.offered:
        return "QUOTE_NOT_OFFERED"
    if s.status in ("UNSCORED", "BLOCKED", NOT_EVALUATED_BY_MODEL):
        return s.status
    if s.action_class == QUALIFIED:
        if auth and auth.role == "CHAMPION" and auth.wagering_authorized:
            return "PRODUCTION_QUALIFIED"
        return "QUALIFIED_NOT_WAGER_AUTHORIZED"
    return s.action_class or "EVALUATED_NO_ACTION"


def assemble(quotes: Iterable[QuoteSide], scores: Iterable[ScoreRow], authority: Optional[Authority] = None,
             releases: Optional[Sequence[str]] = None) -> list[dict]:
    """One row per (quote side, release). Missing adapter rows become UNSCORED, never dropped."""
    quotes = list(quotes)
    by_quote: dict[tuple[str, str], ScoreRow] = {}
    for s in scores:
        key = (s.release_id, s.quote_id)
        if key in by_quote:
            raise ValueError(f"duplicate score row for {key}")
        by_quote[key] = s
    releases = list(releases or sorted({s.release_id for s in by_quote.values()}))
    q_index = {q.key: q for q in quotes}
    rows = []
    for q in quotes:
        for rid in releases:
            s = by_quote.get((rid, q.quote_id)) or ScoreRow(rid, q.quote_id, "UNSCORED",
                                                             reason="NO_ADAPTER_ROW_FOR_QUOTE")
            auth = authority.at(rid, q.quote_as_of_utc) if authority else None
            pr = price(s, q.american_odds if q.offered else None)
            ak = kelly_adjusted(s)
            row = dict.fromkeys(COLUMNS)
            row.update(
                sport=q.sport, event_id=q.event_id, start_time_utc=q.start_utc, start_time_ct=_ct(q.start_utc),
                away=q.away, home=q.home, market=q.market, side=q.side, selection=q.selection, line=q.line,
                american_odds=q.american_odds, break_even=pr.break_even, quote_id=q.quote_id,
                bookmaker=q.bookmaker, quote_as_of_utc=q.quote_as_of_utc, quote_status=q.quote_status,
                model_release_id=rid,
                release_role=auth.role if auth else None,
                release_scoring_authority=auth.scoring_authority if auth else None,
                release_wager_authorized=auth.wagering_authorized if auth else None,
                recorded_role=s.recorded_role, score_as_of_utc=s.score_as_of_utc, model_status=s.status,
                status_reason=s.reason or None, original_tier=s.original_tier or ("NONE" if s.status ==
                                                                                 NOT_EVALUATED_BY_MODEL else None),
                model_signal=s.model_signal, model_action=s.model_action, action_class=s.action_class,
                probability_basis=s.probability_basis, push_probability_status=s.push_probability_status,
                p_win=s.p_win, p_loss=s.p_loss, p_push=s.p_push, p_win_given_decisive=s.p_win_given_decisive,
                ev=pr.ev, ev_basis=pr.ev_basis, ev_null_reason=pr.ev_null_reason,
                full_kelly=pr.full_kelly, full_kelly_basis=pr.full_kelly_basis,
                full_kelly_null_reason=pr.full_kelly_null_reason,
                adjusted_kelly=ak.value, adjusted_kelly_method=ak.method,
                adjusted_kelly_certification=ak.certification, adjusted_kelly_null_reason=ak.null_reason,
                legacy_ev=s.legacy_ev, legacy_full_kelly=s.legacy_full_kelly,
                status=_status(q, s, auth))
            if s.status == NOT_EVALUATED_BY_MODEL:
                opp = q_index.get((q.sport, q.event_id, q.market, OPPOSITE.get(q.side)))
                sel = by_quote.get((rid, opp.quote_id)) if opp else None
                if opp and sel and sel.has_probability:
                    derived = derive_complement(sel, opp, q)
                    if derived:
                        row.update(derived)
            rows.append(row)
    return sort_rows(rows)


def sort_rows(rows: list[dict]) -> list[dict]:
    """Chronological: start time, sport, event, market, side, role (champion first), release."""
    return sorted(rows, key=lambda r: (
        r["start_time_utc"] or "9999", r["sport"], str(r["event_id"]), MARKET_ORDER.get(r["market"], 9),
        SIDE_ORDER.get(r["side"], 9), ROLE_ORDER.get(r["release_role"] or r["recorded_role"] or "", 9),
        r["model_release_id"]))


def mark_new_vs_previous(rows: list[dict], previous: Optional[Iterable[Mapping]]) -> list[dict]:
    """Label each row NEW / UNCHANGED / PRICE_CHANGED / LINE_CHANGED / STATUS_CHANGED vs a prior export."""
    if previous is None:
        for r in rows:
            r["new_vs_previous"] = "NO_PREVIOUS_SHEET"
        return rows
    prior = {(str(p["event_id"]), p["market"], p["side"], p["model_release_id"]): p for p in previous}

    def same(a, b) -> bool:
        if a in (None, "") and b in (None, ""):
            return True
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return str(a) == str(b)

    for r in rows:
        p = prior.get((str(r["event_id"]), r["market"], r["side"], r["model_release_id"]))
        if p is None:
            r["new_vs_previous"] = "NEW"
        elif not same(r["line"], p.get("line")):
            r["new_vs_previous"] = "LINE_CHANGED"
        elif not same(r["american_odds"], p.get("american_odds")):
            r["new_vs_previous"] = "PRICE_CHANGED"
        elif str(r["status"]) != str(p.get("status")):
            r["new_vs_previous"] = "STATUS_CHANGED"
        else:
            r["new_vs_previous"] = "UNCHANGED"
    return rows
