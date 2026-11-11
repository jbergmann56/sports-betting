"""Time helpers. All stored timestamps are UTC ISO-8601; the betting day is US Central."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/Chicago")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def chicago_date(iso_time: str | None) -> str | None:
    """Central-time calendar date of a UTC timestamp (the project's 'betting day')."""
    if not iso_time:
        return None
    return parse_utc(iso_time).astimezone(LOCAL).date().isoformat()
