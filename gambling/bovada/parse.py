"""Pure parser: Bovada feed JSON -> events with six main-market sides each.

Only full-game, pregame main markets are extracted: Moneyline (2W-12),
Spread / Puck Line (2W-HCAP) and Total (2W-OU). Every event always yields all
six sides; anything not usable carries an explicit status instead of being
dropped:

    OFFERED_PREGAME  open price on an open pregame main market
    SUSPENDED        market or outcome posted but not open (status != "O")
    NOT_OFFERED      market or side absent, or price unusable
    NOT_PREGAME      only a live market exists, or the event had started
    SPECIAL_NON_GAME placeholder "event" such as "Away Goals @ Home Goals"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .endpoints import public_page_url
from .transport import feed_events

MARKET_KEYS = {"2W-12": "Moneyline", "2W-HCAP": "Spread", "2W-OU": "Total"}
SIDES = {"Moneyline": ("Away", "Home"), "Spread": ("Away", "Home"), "Total": ("Over", "Under")}
OUTCOME_TYPE = {"Away": "A", "Home": "H", "Over": "O", "Under": "U"}

OFFERED = "OFFERED_PREGAME"
SUSPENDED = "SUSPENDED"
NOT_OFFERED = "NOT_OFFERED"
NOT_PREGAME = "NOT_PREGAME"
SPECIAL_NON_GAME = "SPECIAL_NON_GAME"


def is_placeholder_matchup(away: str | None, home: str | None) -> bool:
    """Bovada lists aggregate specials as fake matchups like "Away Goals @ Home Goals"."""
    return bool(away and home and away.startswith("Away ") and home.startswith("Home "))


@dataclass
class Quote:
    market: str
    side: str
    selection: str | None
    line: float | None
    odds_american: int | None
    odds_decimal: float | None
    quote_status: str
    status_detail: str = ""
    market_id: str | None = None
    outcome_id: str | None = None
    price_id: str | None = None
    period: str | None = None

    @property
    def usable(self) -> bool:
        return self.quote_status == OFFERED and self.odds_american is not None


@dataclass
class Event:
    sport: str
    event_id: str
    description: str
    link: str
    public_url: str
    start_utc: str | None
    live: bool
    event_status: str | None
    last_modified_utc: str | None
    away: str | None
    home: str | None
    away_competitor_id: str | None
    home_competitor_id: str | None
    physical_game: bool = True
    quotes: list[Quote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_main_lines(self) -> bool:
        return any(q.usable for q in self.quotes)

    @property
    def complete(self) -> bool:
        return all(q.usable for q in self.quotes)

    def quote(self, market: str, side: str) -> Quote:
        return next(q for q in self.quotes if q.market == market and q.side == side)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["has_main_lines"] = self.has_main_lines
        data["complete"] = self.complete
        return data


def parse_american(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in ("EVEN", "EV"):
        return 100
    try:
        number = int(text.replace("+", ""))
    except ValueError:
        return None
    if -100 < number < 100:  # not a valid American price
        return None
    return number


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ms_to_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _main_markets(event: dict) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """Return (pregame, live) main full-game markets keyed by our market name."""
    pregame: dict[str, dict] = {}
    live: dict[str, dict] = {}
    warnings: list[str] = []
    for group in event.get("displayGroups") or []:
        for market in group.get("markets") or []:
            name = MARKET_KEYS.get(market.get("key"))
            period = market.get("period") or {}
            if name is None or not period.get("main"):
                continue
            target = live if period.get("live") else pregame
            if name in target:
                if target[name].get("id") != market.get("id"):
                    warnings.append(f"duplicate main {name} market {market.get('id')} ignored")
                continue
            target[name] = market
    return pregame, live, warnings


def _quote_from(market_name: str, side: str, market: dict, event_live: bool) -> Quote:
    period = (market.get("period") or {}).get("description")
    outcome = next((o for o in market.get("outcomes") or [] if o.get("type") == OUTCOME_TYPE[side]), None)
    base = dict(market=market_name, side=side, market_id=str(market.get("id")), period=period)
    if outcome is None:
        detail = "market has no outcomes" if not market.get("outcomes") else f"no {side} outcome posted"
        return Quote(selection=None, line=None, odds_american=None, odds_decimal=None,
                     quote_status=NOT_OFFERED, status_detail=detail, **base)
    price = outcome.get("price") or {}
    american = parse_american(price.get("american"))
    line = _float(price.get("handicap")) if market_name != "Moneyline" else None
    quote = Quote(selection=outcome.get("description"), line=line, odds_american=american,
                  odds_decimal=_float(price.get("decimal")), quote_status=OFFERED,
                  outcome_id=str(outcome.get("id")), price_id=str(price.get("id")) if price.get("id") else None,
                  **base)
    if event_live:
        quote.quote_status, quote.status_detail = NOT_PREGAME, "event is live"
    elif market.get("status") != "O":
        quote.quote_status, quote.status_detail = SUSPENDED, f"market status {market.get('status')}"
    elif outcome.get("status") != "O":
        quote.quote_status, quote.status_detail = SUSPENDED, f"outcome status {outcome.get('status')}"
    elif american is None:
        quote.quote_status, quote.status_detail = NOT_OFFERED, f"unusable price {price.get('american')!r}"
    elif market_name != "Moneyline" and line is None:
        quote.quote_status, quote.status_detail = NOT_OFFERED, "missing handicap"
    return quote


def parse_event(raw: dict, sport: str, as_of: datetime | None = None) -> Event:
    competitors = raw.get("competitors") or []
    home = next((c for c in competitors if c.get("home") is True), None)
    away = next((c for c in competitors if c.get("home") is False), None)
    start = _ms_to_iso(raw.get("startTime"))
    started = bool(as_of and start and datetime.fromisoformat(start) <= as_of)
    event_live = bool(raw.get("live")) or started
    event = Event(
        sport=sport, event_id=str(raw.get("id")), description=raw.get("description", ""),
        link=raw.get("link", ""), public_url=public_page_url(raw.get("link", "")),
        start_utc=start, live=event_live, event_status=raw.get("status"),
        last_modified_utc=_ms_to_iso(raw.get("lastModified")),
        away=away.get("name") if away else None, home=home.get("name") if home else None,
        away_competitor_id=away.get("id") if away else None,
        home_competitor_id=home.get("id") if home else None,
    )
    if home is None or away is None:
        event.warnings.append("home/away competitors not identified")
    if is_placeholder_matchup(event.away, event.home):
        event.physical_game = False
        event.quotes = [Quote(market=m, side=s, selection=None, line=None, odds_american=None,
                              odds_decimal=None, quote_status=SPECIAL_NON_GAME,
                              status_detail="placeholder matchup, not a physical game")
                        for m, sides in SIDES.items() for s in sides]
        return event
    pregame, live, warnings = _main_markets(raw)
    event.warnings.extend(warnings)
    for market_name, sides in SIDES.items():
        for side in sides:
            if market_name in pregame:
                event.quotes.append(_quote_from(market_name, side, pregame[market_name], event_live))
            elif market_name in live:
                quote = _quote_from(market_name, side, live[market_name], True)
                quote.status_detail = "only a live market is posted"
                event.quotes.append(quote)
            else:
                event.quotes.append(Quote(market=market_name, side=side, selection=None, line=None,
                                          odds_american=None, odds_decimal=None,
                                          quote_status=NOT_PREGAME if event_live else NOT_OFFERED,
                                          status_detail="no main full-game market posted"))
    return event


def parse_feed(payload: Any, sport: str, as_of: datetime | None = None) -> list[Event]:
    events = feed_events(payload)
    if events is None:
        raise ValueError("Not a Bovada event feed payload")
    return [parse_event(raw, sport, as_of) for raw in events if raw.get("type", "GAMEEVENT") == "GAMEEVENT"]
