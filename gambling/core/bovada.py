"""Parse an archived Bovada coupon response (``/services/sports/event/v2/events/A/description/...``).

Shared by sports whose frozen scorers read the raw coupon (NCAAFB, NCAABB). One QuoteSide per
outcome of the main full-game Spread / Moneyline / Total markets; ``quote_id`` is Bovada's
outcome price id. A quote is ``OFFERED_PREGAME`` only if market and outcome are open, the event
is not live and the capture precedes the scheduled start; otherwise ``NOT_PREGAME``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from gambling.core.quotes import QuoteSide

MARKET_KEYS = {"2W-HCAP": ("Spread", {"A": "Away", "H": "Home"}), "2W-12": ("Moneyline", {"A": "Away", "H": "Home"}),
               "2W-OU": ("Total", {"O": "Over", "U": "Under"})}


def _american(v) -> float:
    return 100.0 if str(v).upper() in ("EVEN", "EV", "+EVEN") else float(v)


def _line(v):
    return None if v in (None, "") else float(v)


def quotes_from_bovada(raw: list, captured_utc: str, sport: str, source: str = "") -> list[QuoteSide]:
    captured = datetime.fromisoformat(captured_utc.replace("Z", "+00:00"))
    out = []
    for block in raw:
        for e in block["events"]:
            away = next(c["name"] for c in e["competitors"] if not c["home"])
            home = next(c["name"] for c in e["competitors"] if c["home"])
            tip = datetime.fromtimestamp(e["startTime"] / 1000, tz=timezone.utc)
            pregame = not e["live"] and captured < tip
            for g in e["displayGroups"]:
                for m in g["markets"]:
                    if m["key"] not in MARKET_KEYS or not m["period"]["main"] or m["period"]["live"]:
                        continue
                    market, side_of = MARKET_KEYS[m["key"]]
                    for o in m["outcomes"]:
                        p = o["price"]
                        offered = o["status"] == "O" and m["status"] == "O" and pregame
                        out.append(QuoteSide(sport, str(e["id"]), tip.isoformat(), away, home, market,
                                             side_of[o["type"]], o["description"], _line(p.get("handicap")),
                                             _american(p["american"]), f"BOVADA:{p['id']}", captured_utc,
                                             "OFFERED_PREGAME" if offered else "NOT_PREGAME", "Bovada", source))
    return out


__all__ = ["quotes_from_bovada"]
