"""Fetch orchestration: variant ladder, retries, merge, event-page recovery.

Typical use::

    from gambling.bovada import fetch_board
    result = fetch_board(["NBA", "NHL"], capture_root=Path("data/captures"))

Every request (including failures) is recorded by the sink before anything
else happens, and the resulting board says, per event, which recorded attempt
its prices came from and how old the CDN said that data was.
"""

from __future__ import annotations

import csv
import io
import json
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from .capture import CaptureStore, load_attempts, new_run_id
from .endpoints import LEAGUES, Endpoint, event_variants, league_variants
from .parse import Event, parse_feed
from .transport import (Classified, HttpResponse, Outcome, RetryPolicy, Transport,
                        UrllibTransport, classify, utcnow)

# Sport-level verdicts
SPORT_OK = "OK"                    # at least one fresh, valid board
SPORT_NO_EVENTS = "NO_EVENTS"      # fresh responses agree there is nothing listed
SPORT_BLOCKED = "BLOCKED"          # access refused (geo/403) and nothing usable
SPORT_FAILED = "FAILED"            # no usable board: network, stale or malformed only


class Sink(Protocol):
    run_id: str

    def record(self, label: str, resp: HttpResponse, verdict: Classified, *, sport: str,
               variant: str, attempt: int, purpose: str) -> dict[str, Any]: ...


class MemorySink:
    """Records attempt metadata without writing files (used for replay)."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._seq = 0

    def record(self, label, resp, verdict, *, sport, variant, attempt, purpose):
        self._seq += 1
        return {"attempt_id": f"{self.run_id}:{self._seq:04d}", "sport": sport, "purpose": purpose,
                "variant": variant, "attempt": attempt, "url": resp.url, "http_status": resp.status,
                "received_utc": resp.received_utc.isoformat(), "outcome": verdict.outcome.value,
                "outcome_detail": verdict.detail, "event_count": verdict.event_count,
                "cdn_age_seconds": verdict.cdn_age_seconds,
                "snapshot_as_of_utc": verdict.snapshot_as_of_utc.isoformat() if verdict.snapshot_as_of_utc else None}


@dataclass
class FetchConfig:
    max_age_seconds: int = 900          # reject CDN objects older than this
    all_variants: bool = True           # union every fresh variant (coverage) vs stop at first OK
    recover_events: bool = True         # refetch event pages for incomplete pregame events
    max_recoveries_per_sport: int = 40
    policy: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass
class Source:
    verdict: Classified
    meta: dict[str, Any]


@dataclass
class SportResult:
    sport: str
    status: str
    detail: str
    events: list[Event]
    provenance: dict[str, dict[str, Any]]           # event_id -> source info
    variant_coverage: dict[str, list[str]]          # variant -> event ids it returned
    attempts: list[dict[str, Any]]
    recovered: list[str] = field(default_factory=list)
    unrecovered: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        outcomes: dict[str, int] = {}
        for attempt in self.attempts:
            outcomes[attempt["outcome"]] = outcomes.get(attempt["outcome"], 0) + 1
        pregame = [e for e in self.events if not e.live and e.physical_game]
        as_of = sorted(p["snapshot_as_of_utc"] for p in self.provenance.values() if p.get("snapshot_as_of_utc"))
        return {
            "sport": self.sport, "status": self.status, "detail": self.detail,
            "events": len(self.events), "pregame_events": len(pregame),
            "pregame_with_any_line": sum(e.has_main_lines for e in pregame),
            "pregame_complete": sum(e.complete for e in pregame),
            "special_non_games": sum(not e.physical_game for e in self.events),
            "recovered_from_event_page": len(self.recovered),
            "still_incomplete": self.unrecovered,
            "attempt_outcomes": outcomes,
            "variant_event_counts": {k: len(v) for k, v in self.variant_coverage.items()},
            "snapshot_as_of_min_utc": as_of[0] if as_of else None,
            "snapshot_as_of_max_utc": as_of[-1] if as_of else None,
        }


@dataclass
class RunResult:
    run_id: str
    started_utc: datetime
    finished_utc: datetime
    sports: dict[str, SportResult]
    run_dir: Path | None = None
    config: FetchConfig = field(default_factory=FetchConfig)

    @property
    def ok(self) -> bool:
        return all(r.status in (SPORT_OK, SPORT_NO_EVENTS) for r in self.sports.values())

    def manifest(self) -> dict[str, Any]:
        stamps = [p["snapshot_as_of_utc"] for r in self.sports.values() for p in r.provenance.values()
                  if p.get("snapshot_as_of_utc")]
        skew = None
        if stamps:
            parsed = sorted(datetime.fromisoformat(s) for s in stamps)
            skew = (parsed[-1] - parsed[0]).total_seconds()
        return {
            "run_id": self.run_id, "source": "BOVADA_PUBLIC_EVENT_FEED",
            "started_utc": self.started_utc.isoformat(), "finished_utc": self.finished_utc.isoformat(),
            "all_sports_ok": self.ok, "snapshot_skew_seconds": skew,
            "config": {"max_age_seconds": self.config.max_age_seconds,
                       "all_variants": self.config.all_variants,
                       "recover_events": self.config.recover_events,
                       "max_recoveries_per_sport": self.config.max_recoveries_per_sport,
                       "max_attempts": self.config.policy.max_attempts},
            "note": "Prices are observations of Bovada's public feed at snapshot_as_of_utc "
                    "(response Date minus CDN Age); not guaranteed executable.",
            "sports": {s: r.summary() for s, r in self.sports.items()},
        }

    def board(self) -> list[dict[str, Any]]:
        rows = []
        for sport, result in self.sports.items():
            for event in result.events:
                row = event.to_dict()
                row["provenance"] = result.provenance.get(event.event_id)
                rows.append(row)
        return rows

    def quotes_csv(self) -> str:
        columns = ["sport", "event_id", "description", "start_utc", "live", "physical_game", "market", "side",
                   "selection",
                   "line", "odds_american", "odds_decimal", "quote_status", "status_detail", "market_id",
                   "outcome_id", "price_id", "snapshot_as_of_utc", "cdn_age_seconds", "source_attempt_id",
                   "source_variant"]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, columns, lineterminator="\n")
        writer.writeheader()
        for sport, result in self.sports.items():
            for event in result.events:
                prov = result.provenance.get(event.event_id, {})
                for q in event.quotes:
                    writer.writerow({
                        "sport": sport, "event_id": event.event_id, "description": event.description,
                        "start_utc": event.start_utc, "live": int(event.live),
                        "physical_game": int(event.physical_game), "market": q.market,
                        "side": q.side, "selection": q.selection, "line": q.line,
                        "odds_american": q.odds_american, "odds_decimal": q.odds_decimal,
                        "quote_status": q.quote_status, "status_detail": q.status_detail,
                        "market_id": q.market_id, "outcome_id": q.outcome_id, "price_id": q.price_id,
                        "snapshot_as_of_utc": prov.get("snapshot_as_of_utc"),
                        "cdn_age_seconds": prov.get("cdn_age_seconds"),
                        "source_attempt_id": prov.get("attempt_id"), "source_variant": prov.get("variant"),
                    })
        return buffer.getvalue()


class Fetcher:
    def __init__(self, transport: Transport, sink: Sink, config: FetchConfig | None = None, *,
                 sleep: Callable[[float], None] = time.sleep, rand: Callable[[], float] = random.random):
        self.transport = transport
        self.sink = sink
        self.config = config or FetchConfig()
        self.sleep = sleep
        self.rand = rand
        self._requests = 0

    # -- low level -------------------------------------------------------
    def _get(self, endpoint: Endpoint, *, sport: str, purpose: str, label: str,
             attempts: list[dict[str, Any]]) -> Source:
        policy = self.config.policy
        verdict: Classified | None = None
        meta: dict[str, Any] = {}
        for attempt in range(1, policy.max_attempts + 1):
            if self._requests and policy.polite_delay > 0:
                self.sleep(policy.polite_delay)
            self._requests += 1
            resp = self.transport.get(endpoint.url, policy.timeout)
            verdict = classify(resp, self.config.max_age_seconds)
            meta = self.sink.record(label, resp, verdict, sport=sport, variant=endpoint.variant,
                                    attempt=attempt, purpose=purpose)
            attempts.append(meta)
            if verdict.outcome is Outcome.OK or not verdict.outcome.retryable or attempt == policy.max_attempts:
                break
            self.sleep(policy.backoff(attempt, verdict.retry_after_seconds, self.rand))
        assert verdict is not None
        return Source(verdict, meta)

    @staticmethod
    def _provenance(source: Source) -> dict[str, Any]:
        v, m = source.verdict, source.meta
        return {"attempt_id": m.get("attempt_id"), "variant": m.get("variant"), "url": m.get("url"),
                "purpose": m.get("purpose"), "received_utc": m.get("received_utc"),
                "cdn_age_seconds": v.cdn_age_seconds,
                "snapshot_as_of_utc": v.snapshot_as_of_utc.isoformat() if v.snapshot_as_of_utc else None}

    # -- per sport -------------------------------------------------------
    def fetch_sport(self, sport: str) -> SportResult:
        attempts: list[dict[str, Any]] = []
        good: list[Source] = []
        verdicts: list[Classified] = []
        for endpoint in league_variants(sport):
            source = self._get(endpoint, sport=sport, purpose="league_board",
                               label=f"{sport}_{endpoint.variant}", attempts=attempts)
            verdicts.append(source.verdict)
            if source.verdict.outcome is Outcome.OK:
                good.append(source)
                if not self.config.all_variants:
                    break

        events: dict[str, Event] = {}
        provenance: dict[str, dict[str, Any]] = {}
        coverage: dict[str, list[str]] = {}
        chosen_as_of: dict[str, datetime] = {}
        for source in good:
            as_of = source.verdict.snapshot_as_of_utc
            parsed = parse_feed(source.verdict.payload, sport, as_of)
            coverage[source.meta["variant"]] = [e.event_id for e in parsed]
            for event in parsed:
                previous = chosen_as_of.get(event.event_id)
                better = (previous is None or (as_of and as_of > previous)
                          or (as_of == previous and event.complete and not events[event.event_id].complete))
                if better:
                    events[event.event_id] = event
                    provenance[event.event_id] = self._provenance(source)
                    chosen_as_of[event.event_id] = as_of

        recovered: list[str] = []
        unrecovered: list[str] = []
        if self.config.recover_events:
            incomplete = [e for e in events.values()
                          if e.physical_game and not e.live and not e.complete and e.link]
            for event in incomplete[: self.config.max_recoveries_per_sport]:
                replacement = self._recover(event, sport, attempts)
                if replacement is not None:
                    new_event, source = replacement
                    events[event.event_id] = new_event
                    provenance[event.event_id] = self._provenance(source)
                    recovered.append(event.event_id)
                if not events[event.event_id].complete:
                    unrecovered.append(event.event_id)

        status, detail = self._sport_status(good, verdicts)
        ordered = sorted(events.values(), key=lambda e: (e.start_utc or "", e.event_id))
        return SportResult(sport, status, detail, ordered, provenance, coverage, attempts, recovered, unrecovered)

    def _recover(self, event: Event, sport: str, attempts: list[dict[str, Any]]) -> tuple[Event, Source] | None:
        """Try the event's own page. Accept it only if it is fresh and strictly better."""
        usable_before = sum(q.usable for q in event.quotes)
        for endpoint in event_variants(event.link):
            source = self._get(endpoint, sport=sport, purpose=f"event_recovery:{event.event_id}",
                               label=f"{sport}_{event.event_id}_{endpoint.variant}", attempts=attempts)
            if source.verdict.outcome is not Outcome.OK:
                continue
            for candidate in parse_feed(source.verdict.payload, sport, source.verdict.snapshot_as_of_utc):
                if candidate.event_id == event.event_id and sum(q.usable for q in candidate.quotes) > usable_before:
                    return candidate, source
            return None  # page fetched fine; book simply has nothing more posted
        return None

    @staticmethod
    def _sport_status(good: list[Source], verdicts: list[Classified]) -> tuple[str, str]:
        if good:
            return SPORT_OK, f"{len(good)}/{len(verdicts)} variants usable"
        outcomes = [v.outcome for v in verdicts]
        if any(o is Outcome.BLOCKED for o in outcomes):
            return SPORT_BLOCKED, "access refused: " + ", ".join(v.detail for v in verdicts)
        fresh_empty = [v for v in verdicts if v.outcome is Outcome.EMPTY]
        if fresh_empty and all(o in (Outcome.EMPTY, Outcome.STALE, Outcome.NOT_FOUND) for o in outcomes):
            return SPORT_NO_EVENTS, "fresh responses list no events (verify against schedule)"
        return SPORT_FAILED, "; ".join(f"{v.outcome.value}: {v.detail}" for v in verdicts)

    # -- whole run -------------------------------------------------------
    def fetch(self, sports: Iterable[str]) -> dict[str, SportResult]:
        results: dict[str, SportResult] = {}
        for sport in sports:
            if sport not in LEAGUES:
                raise ValueError(f"Unknown sport {sport!r}; expected one of {sorted(LEAGUES)}")
            results[sport] = self.fetch_sport(sport)
        return results


def fetch_board(sports: Iterable[str], capture_root: Path, *, config: FetchConfig | None = None,
                transport: Transport | None = None, sleep: Callable[[float], None] = time.sleep,
                rand: Callable[[], float] = random.random, clock: Callable[[], datetime] = utcnow) -> RunResult:
    """Fetch, record every attempt under ``capture_root/<run_id>/`` and write
    ``manifest.json``, ``board.json`` and ``quotes.csv`` for the run."""
    config = config or FetchConfig()
    started = clock()
    store = CaptureStore(Path(capture_root), new_run_id(started))
    fetcher = Fetcher(transport or UrllibTransport(), store, config, sleep=sleep, rand=rand)
    results = fetcher.fetch(list(sports))
    run = RunResult(store.run_id, started, clock(), results, store.run_dir, config)
    store.write_document("manifest.json", run.manifest())
    store.write_document("board.json", run.board())
    with (store.run_dir / "quotes.csv").open("x", encoding="utf-8", newline="") as stream:
        stream.write(run.quotes_csv())
    return run


class ReplayTransport:
    """Serves previously captured responses, per URL in original order."""

    def __init__(self, attempts: list[tuple[dict[str, Any], bytes]]):
        self._queues: dict[str, deque] = {}
        for meta, body in attempts:
            resp = HttpResponse(
                url=meta["url"], status=meta["http_status"], headers=meta.get("response_headers") or {},
                body=body, requested_utc=datetime.fromisoformat(meta["requested_utc"]),
                received_utc=datetime.fromisoformat(meta["received_utc"]), error=meta.get("network_error"))
            self._queues.setdefault(meta["url"], deque()).append(resp)

    def get(self, url: str, timeout: float) -> HttpResponse:
        queue = self._queues.get(url)
        if not queue:
            raise LookupError(f"Replay has no captured response for {url}")
        return queue.popleft()


def replay_run(run_dir: Path, config: FetchConfig | None = None) -> RunResult:
    """Rebuild a run's board from its captured bytes, without any network access."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    attempts = load_attempts(run_dir)
    if config is None:
        saved = manifest.get("config", {})
        config = FetchConfig(
            max_age_seconds=saved.get("max_age_seconds", 900),
            all_variants=saved.get("all_variants", True),
            recover_events=saved.get("recover_events", True),
            max_recoveries_per_sport=saved.get("max_recoveries_per_sport", 40),
            policy=RetryPolicy(max_attempts=saved.get("max_attempts", 3)))
    # The capture holds every original retry in order, so the same decisions replay exactly.
    fetcher = Fetcher(ReplayTransport(attempts), MemorySink(manifest["run_id"]), config,
                      sleep=lambda _: None, rand=lambda: 0.5)
    results = fetcher.fetch(manifest["sports"].keys())
    return RunResult(manifest["run_id"], datetime.fromisoformat(manifest["started_utc"]),
                     datetime.fromisoformat(manifest["finished_utc"]), results, run_dir, config)
