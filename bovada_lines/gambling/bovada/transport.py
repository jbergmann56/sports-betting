"""HTTP transport and response classification.

The transport never raises for network or HTTP problems: every outcome is
returned as an :class:`HttpResponse` so it can be recorded and classified.
"""

from __future__ import annotations

import gzip
import json
import socket
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any, Callable, Protocol

from ..timeutil import utcnow

DEFAULT_HEADERS = {
    # A plain browser-like client identity; no account or personal details.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class HttpResponse:
    url: str
    status: int | None                 # None when no HTTP response arrived
    headers: dict[str, str]
    body: bytes
    requested_utc: datetime
    received_utc: datetime
    error: str | None = None           # network/timeout description

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None


class Transport(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse: ...


def _decode_body(raw: bytes, encoding: str | None) -> bytes:
    if not encoding:
        return raw
    encoding = encoding.lower()
    if "gzip" in encoding:
        return gzip.decompress(raw)
    if "deflate" in encoding:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


class UrllibTransport:
    """Standard-library HTTP GET."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = dict(DEFAULT_HEADERS if headers is None else headers)

    def get(self, url: str, timeout: float) -> HttpResponse:
        requested = utcnow()
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                headers = dict(reply.headers.items())
                raw = reply.read()
                status = reply.status
        except urllib.error.HTTPError as exc:  # HTTP error status: keep its body
            headers = dict(exc.headers.items()) if exc.headers else {}
            try:
                raw = exc.read()
            except Exception:  # noqa: BLE001 - body is best-effort evidence
                raw = b""
            status = exc.code
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return HttpResponse(url, None, {}, b"", requested, utcnow(),
                                error=f"{type(exc).__name__}: {reason}")
        received = utcnow()
        try:
            body = _decode_body(raw, headers.get("Content-Encoding") or headers.get("content-encoding"))
        except (OSError, zlib.error, EOFError) as exc:
            return HttpResponse(url, status, headers, raw, requested, received,
                                error=f"TRUNCATED_ENCODED_BODY: {exc}")
        return HttpResponse(url, status, headers, body, requested, received)


class Outcome(str, Enum):
    OK = "OK"
    EMPTY = "EMPTY"                  # valid JSON, but no events (e.g. cached `{}`)
    STALE = "STALE"                  # CDN Age beyond freshness limit
    NON_JSON = "NON_JSON"            # HTML block page, captcha, etc.
    MALFORMED = "MALFORMED"          # JSON, but not the expected feed shape
    TRUNCATED = "TRUNCATED"          # body cut off / undecodable
    BLOCKED = "BLOCKED"              # 401/403/451: geo or access block
    NOT_FOUND = "NOT_FOUND"          # 404
    RATE_LIMITED = "RATE_LIMITED"    # 429
    HTTP_5XX = "HTTP_5XX"
    HTTP_4XX = "HTTP_4XX"
    NETWORK_ERROR = "NETWORK_ERROR"  # timeout, DNS, connection reset

    @property
    def retryable(self) -> bool:
        """Worth repeating the *same* URL. A cached EMPTY/STALE answer is not:
        the CDN will hand back the same object, so move to the next variant."""
        return self in {Outcome.RATE_LIMITED, Outcome.HTTP_5XX, Outcome.NETWORK_ERROR, Outcome.TRUNCATED}


@dataclass
class Classified:
    outcome: Outcome
    detail: str
    payload: Any = None
    event_count: int = 0
    cdn_age_seconds: int | None = None
    server_date_utc: datetime | None = None
    snapshot_as_of_utc: datetime | None = None   # best estimate of when the data was produced
    retry_after_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value.strip()) if value is not None else None
    except ValueError:
        return None


def _snapshot_time(resp: HttpResponse) -> tuple[int | None, datetime | None, datetime]:
    """Bovada's CDN may return an object generated long before the request.
    ``Date - Age`` approximates when the origin produced it."""
    age = _parse_int(resp.header("Age"))
    server_date = None
    date_header = resp.header("Date")
    if date_header:
        try:
            server_date = parsedate_to_datetime(date_header).astimezone(timezone.utc)
        except (TypeError, ValueError):
            server_date = None
    reference = server_date or resp.received_utc
    as_of = reference - timedelta(seconds=age or 0)
    return age, server_date, as_of


def feed_events(payload: Any) -> list[dict] | None:
    """Return the event list of a Bovada feed payload, or None if the shape is wrong."""
    if isinstance(payload, dict) and not payload:
        return []
    if not isinstance(payload, list):
        return None
    events: list[dict] = []
    for group in payload:
        if not isinstance(group, dict) or not isinstance(group.get("events"), list):
            return None
        events.extend(e for e in group["events"] if isinstance(e, dict))
    return events


def classify(resp: HttpResponse, max_age_seconds: int) -> Classified:
    age, server_date, as_of = _snapshot_time(resp)
    meta = dict(cdn_age_seconds=age, server_date_utc=server_date, snapshot_as_of_utc=as_of)

    if resp.status is None:
        return Classified(Outcome.NETWORK_ERROR, resp.error or "no response", **meta)
    if resp.error and resp.error.startswith("TRUNCATED"):
        return Classified(Outcome.TRUNCATED, resp.error, **meta)
    if resp.status == 429:
        retry_after = _parse_int(resp.header("Retry-After"))
        return Classified(Outcome.RATE_LIMITED, "HTTP 429", retry_after_seconds=retry_after, **meta)
    if resp.status in (401, 403, 451):
        return Classified(Outcome.BLOCKED, f"HTTP {resp.status}", **meta)
    if resp.status == 404:
        return Classified(Outcome.NOT_FOUND, "HTTP 404", **meta)
    if 500 <= resp.status:
        return Classified(Outcome.HTTP_5XX, f"HTTP {resp.status}", **meta)
    if resp.status >= 400 or resp.status < 200:
        return Classified(Outcome.HTTP_4XX, f"HTTP {resp.status}", **meta)

    text = resp.body.decode("utf-8", errors="replace").strip()
    if not text:
        return Classified(Outcome.EMPTY, "zero-length body", **meta)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        looks_json = text[:1] in "[{"
        outcome = Outcome.TRUNCATED if looks_json else Outcome.NON_JSON
        return Classified(outcome, f"{exc.msg} at char {exc.pos}; starts {text[:60]!r}", **meta)

    events = feed_events(payload)
    if events is None:
        return Classified(Outcome.MALFORMED, f"unexpected JSON shape ({type(payload).__name__})", payload=payload, **meta)
    if age is not None and age > max_age_seconds:
        return Classified(Outcome.STALE, f"CDN Age {age}s > {max_age_seconds}s; {len(events)} events",
                          payload=payload, event_count=len(events), **meta)
    if not events:
        return Classified(Outcome.EMPTY, f"no events (body {text[:20]!r})", payload=payload, **meta)
    return Classified(Outcome.OK, f"{len(events)} events", payload=payload, event_count=len(events), **meta)


@dataclass
class RetryPolicy:
    max_attempts: int = 3          # per URL
    base_delay: float = 1.0        # seconds, doubled each retry
    max_delay: float = 20.0
    jitter: float = 0.25           # +/- fraction of the delay
    timeout: float = 25.0          # per request
    polite_delay: float = 0.4      # pause between distinct requests

    def backoff(self, attempt: int, retry_after: float | None, rand: Callable[[], float]) -> float:
        if retry_after is not None:
            return min(float(retry_after), self.max_delay * 3)
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return max(0.0, delay * (1 + self.jitter * (2 * rand() - 1)))
