"""Bovada public event-feed URLs.

Bovada's CDN caches every distinct URL independently, and individual URL
variants have been observed serving a cached empty ``{}`` body for days while
another variant of the same league feed was fresh (probe 2026-11-11). The
fetcher therefore tries an ordered *ladder* of equivalent URL variants and
judges each response on its own merits instead of trusting any single URL.

Adding an arbitrary cache-busting query parameter is rejected by the origin
(HTTP 404), so only parameters the feed already understands are varied.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE = "https://www.bovada.lv/services/sports/event"

# Sport code used throughout the project -> Bovada league path.
LEAGUES: dict[str, str] = {
    "NFL": "football/nfl",
    "NCAAFB": "football/college-football",
    "NBA": "basketball/nba",
    "NCAABB": "basketball/college-basketball",
    "NHL": "hockey/nhl",
}


@dataclass(frozen=True)
class Endpoint:
    variant: str
    url: str


def league_variants(sport: str) -> list[Endpoint]:
    """Equivalent league-board URLs, most reliable first."""
    path = LEAGUES[sport]
    coupon = f"{BASE}/coupon/events/A/description/{path}"
    v2 = f"{BASE}/v2/events/A/description/{path}"
    return [
        Endpoint("coupon_prematch", f"{coupon}?marketFilterId=def&preMatchOnly=true&eventsLimit=5000&lang=en"),
        Endpoint("coupon_prematch_nolimit", f"{coupon}?marketFilterId=def&preMatchOnly=true&lang=en"),
        Endpoint("v2_league", f"{v2}?lang=en"),
        Endpoint("v2_league_prematch", f"{v2}?preMatchOnly=true&lang=en"),
    ]


def event_variants(event_link: str) -> list[Endpoint]:
    """URLs for a single event, given the event's ``link`` field
    (e.g. ``/basketball/nba/boston-celtics-toronto-raptors-202611111900``)."""
    link = "/" + event_link.lstrip("/")
    return [
        Endpoint("v2_event", f"{BASE}/v2/events/A/description{link}?lang=en"),
        Endpoint("coupon_event", f"{BASE}/coupon/events/A/description{link}?marketFilterId=def&lang=en"),
    ]


def public_page_url(event_link: str) -> str:
    return "https://www.bovada.lv/sports/" + event_link.lstrip("/")
