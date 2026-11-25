"""Normalized bookmaker quote sides shared by adapters, scoring and bet sheets.

One ``QuoteSide`` per offered (or explicitly absent/suspended) market side. Lines
are **selection-oriented**: an away spread of +3 is ``line=3.0`` on the Away row
and ``line=-3.0`` on the Home row; totals carry the same line on Over and Under.
Nothing here alters a price or a timestamp; converters only reshape.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

MARKET_ORDER = {"Moneyline": 0, "Spread": 1, "Total": 2}
SIDE_ORDER = {"Away": 0, "Home": 1, "Over": 2, "Under": 3}
SIDES = {"Moneyline": ("Away", "Home"), "Spread": ("Away", "Home"), "Total": ("Over", "Under")}
OPPOSITE = {"Away": "Home", "Home": "Away", "Over": "Under", "Under": "Over"}


@dataclass(frozen=True)
class QuoteSide:
    sport: str
    event_id: str
    start_utc: str
    away: str
    home: str
    market: str            # Moneyline | Spread | Total
    side: str              # Away | Home | Over | Under
    selection: str
    line: Optional[float]  # selection-oriented; None for moneyline
    american_odds: Optional[float]
    quote_id: str
    quote_as_of_utc: str
    quote_status: str      # OFFERED_PREGAME | SUSPENDED | NOT_OFFERED | ...
    bookmaker: str = "Bovada"
    source: str = ""

    @property
    def key(self) -> tuple:
        return (self.sport, self.event_id, self.market, self.side)

    @property
    def offered(self) -> bool:
        return self.quote_status == "OFFERED_PREGAME" and self.american_odds is not None


def _num(v) -> Optional[float]:
    if v is None or str(v).strip() in ("", "nan", "None"):
        return None
    return float(v)


def from_capture_csv(path: str | Path, sport: Optional[str] = None) -> list[QuoteSide]:
    """Read a long-format capture ``quotes.csv`` (``gambling fetch`` / 20261112 layout)."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if sport and r["sport"] != sport:
                continue
            away, home = r["description"].split(" @ ")
            out.append(QuoteSide(
                sport=r["sport"], event_id=str(r["event_id"]), start_utc=r["start_utc"], away=away, home=home,
                market=r["market"], side=r["side"], selection=r["selection"], line=_num(r.get("line")),
                american_odds=_num(r.get("odds_american")),
                quote_id=f"BOVADA:{r['price_id']}" if r.get("price_id") else f"BOVADA:{r['event_id']}:{r['market']}:{r['side']}",
                quote_as_of_utc=r["snapshot_as_of_utc"], quote_status=r["quote_status"],
                source=r.get("source_attempt_id", "")))
    return out


def complete_board(quotes: Iterable[QuoteSide]) -> list[QuoteSide]:
    """Ensure six sides per event; add explicit NOT_OFFERED rows for absent sides.

    The added rows carry no odds and no line; they exist so the bet sheet shows
    the absence instead of silently omitting it.
    """
    quotes = list(quotes)
    have = {q.key for q in quotes}
    events = {}
    for q in quotes:
        events.setdefault((q.sport, q.event_id), q)
    added = []
    for (sport, event_id), ref in events.items():
        for market, sides in SIDES.items():
            for side in sides:
                if (sport, event_id, market, side) not in have:
                    selection = ref.away if side == "Away" else ref.home if side == "Home" else side
                    added.append(QuoteSide(sport, event_id, ref.start_utc, ref.away, ref.home, market, side,
                                           selection, None, None, f"ABSENT:{event_id}:{market}:{side}",
                                           ref.quote_as_of_utc, "NOT_OFFERED", ref.bookmaker, "complete_board"))
    return quotes + added
