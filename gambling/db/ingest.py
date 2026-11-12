"""Ingest a ``fetch`` capture directory's JSON files into the rolling database.

Reads ``manifest.json``, ``board.json`` and every ``*.meta.json`` written by
:func:`gambling.bovada.fetch_board`. Raw response bodies stay on disk; the
database stores their path and SHA-256, and ingest verifies each body against
the hash recorded at capture time before writing anything.

A run is written in one transaction. Ingesting the same unchanged run again is
a no-op; ingesting a run whose JSON changed since it was ingested is an error.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..bovada.parse import is_placeholder_matchup
from ..odds import break_even_probability
from ..timeutil import parse_utc, utcnow

SOURCE_NAME = "BOVADA_PUBLIC_EVENT_FEED"
COHORT_MAX_SECONDS = 120


class IngestError(RuntimeError):
    pass


@dataclass
class CaptureRun:
    run_dir: Path
    manifest: dict[str, Any]
    board: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    manifest_sha256: str
    board_sha256: str

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_capture(run_dir: Path, verify_bodies: bool = True) -> CaptureRun:
    run_dir = Path(run_dir)
    try:
        manifest_bytes = (run_dir / "manifest.json").read_bytes()
        board_bytes = (run_dir / "board.json").read_bytes()
    except FileNotFoundError as exc:
        raise IngestError(f"{run_dir} is not a complete capture: {exc.filename} missing") from exc
    manifest = json.loads(manifest_bytes)
    board = json.loads(board_bytes)
    if manifest.get("run_id") != run_dir.name:
        raise IngestError(f"manifest run_id {manifest.get('run_id')!r} does not match folder {run_dir.name!r}")

    attempts = []
    for meta_path in sorted(run_dir.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if verify_bodies:
            body_path = run_dir / meta["body_file"]
            if not body_path.exists():
                raise IngestError(f"raw body {meta['body_file']} is missing")
            if _sha(body_path.read_bytes()) != meta["body_sha256"]:
                raise IngestError(f"raw body {meta['body_file']} does not match its recorded sha256")
        attempts.append(meta)

    known = {a["attempt_id"] for a in attempts}
    for event in board:
        attempt_id = (event.get("provenance") or {}).get("attempt_id")
        if attempt_id not in known:
            raise IngestError(f"event {event.get('event_id')} cites unknown attempt {attempt_id!r}")
    return CaptureRun(run_dir, manifest, board, attempts, _sha(manifest_bytes), _sha(board_bytes))


def _as_of(event: dict[str, Any]) -> str:
    prov = event.get("provenance") or {}
    stamp = prov.get("snapshot_as_of_utc") or prov.get("received_utc")
    if not stamp:
        raise IngestError(f"event {event.get('event_id')} has no observation time")
    return stamp


def _cohorts(run_id: str, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Group events whose observation times lie within COHORT_MAX_SECONDS of the cohort's first."""
    ordered = sorted(events, key=lambda e: (parse_utc(_as_of(e)), e["sport"], e["event_id"]))
    cohorts: list[dict[str, Any]] = []
    assignment: dict[str, str] = {}
    current: list[dict[str, Any]] = []

    def close() -> None:
        times = [parse_utc(_as_of(e)) for e in current]
        cohort_id = f"{run_id}:C{len(cohorts) + 1:02d}"
        cohorts.append({
            "cohort_id": cohort_id, "batch_id": run_id,
            "min_quote_utc": min(times).isoformat(), "max_quote_utc": max(times).isoformat(),
            "quote_skew_seconds": (max(times) - min(times)).total_seconds(),
            "sports_json": json.dumps(sorted({e["sport"] for e in current})),
            "physical_games": sum(1 for e in current if e["physical_game"]),
        })
        for e in current:
            assignment[f"{e['sport']}:{e['event_id']}"] = cohort_id

    start: datetime | None = None
    for event in ordered:
        moment = parse_utc(_as_of(event))
        if current and start is not None and (moment - start).total_seconds() > COHORT_MAX_SECONDS:
            close()
            current = []
        if not current:
            start = moment
        current.append(event)
    if current:
        close()
    return cohorts, assignment


def _quote_id(run_id: str, sport: str, event_id: str, market: str, side: str) -> str:
    return hashlib.sha256("|".join((run_id, sport, event_id, market, side, "main")).encode()).hexdigest()[:24]


def _insert(con: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    con.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", list(row.values()))


def ingest_capture(con: sqlite3.Connection, run_dir: Path, *, verify_bodies: bool = True) -> dict[str, Any]:
    """Ingest one capture directory. Returns a summary; idempotent for unchanged runs."""
    run = load_capture(run_dir, verify_bodies)
    existing = con.execute("SELECT manifest_sha256, board_sha256 FROM fetch_runs WHERE run_id=?",
                           (run.run_id,)).fetchone()
    if existing:
        if (existing["manifest_sha256"], existing["board_sha256"]) == (run.manifest_sha256, run.board_sha256):
            return {"run_id": run.run_id, "status": "ALREADY_INGESTED"}
        raise IngestError(f"{run.run_id} was already ingested with different JSON; capture files were altered")

    events = []
    for event in run.board:
        event = dict(event)
        if "physical_game" not in event:  # captures written before the flag existed
            event["physical_game"] = not is_placeholder_matchup(event.get("away"), event.get("home"))
        events.append(event)

    now = utcnow().isoformat()
    cohorts, cohort_of = _cohorts(run.run_id, events) if events else ([], {})
    manifest = run.manifest
    con.execute("BEGIN")
    try:
        batch_id = None
        if events:
            batch_id = run.run_id
            times = sorted(parse_utc(_as_of(e)) for e in events)
            skew = (times[-1] - times[0]).total_seconds()
            ok = bool(manifest.get("all_sports_ok"))
            _insert(con, "capture_batches", {
                "batch_id": batch_id, "source_name": SOURCE_NAME,
                "min_quote_utc": times[0].isoformat(), "max_quote_utc": times[-1].isoformat(),
                "quote_skew_seconds": skew,
                "coherent_all_sports": int(ok and skew <= COHORT_MAX_SECONDS),
                "cohort_max_seconds": COHORT_MAX_SECONDS, "source_snapshot_library_id": None,
                "ingested_utc": now,
                "notes": "; ".join(f"{s} {v['status']}" for s, v in manifest.get("sports", {}).items()),
            })
            for cohort in cohorts:
                _insert(con, "quote_cohorts", cohort)
            for name, sha in (("manifest.json", run.manifest_sha256), ("board.json", run.board_sha256)):
                _insert(con, "source_files", {"batch_id": batch_id, "source_name": name,
                                              "file_sha256": sha, "source_library_id": None})

        _insert(con, "fetch_runs", {
            "run_id": run.run_id, "batch_id": batch_id, "capture_dir": str(run.run_dir),
            "started_utc": manifest["started_utc"], "finished_utc": manifest["finished_utc"],
            "all_sports_ok": int(bool(manifest.get("all_sports_ok"))),
            "snapshot_skew_seconds": manifest.get("snapshot_skew_seconds"),
            "config_json": json.dumps(manifest.get("config", {}), sort_keys=True),
            "manifest_sha256": run.manifest_sha256, "board_sha256": run.board_sha256, "ingested_utc": now,
        })
        for meta in run.attempts:
            _insert(con, "fetch_attempts", {k: meta.get(k) for k in (
                "attempt_id", "run_id", "sequence", "sport", "purpose", "variant", "attempt", "url",
                "requested_utc", "received_utc", "http_status", "network_error", "outcome",
                "outcome_detail", "event_count", "cdn_age_seconds", "server_date_utc",
                "snapshot_as_of_utc", "body_file", "body_bytes", "body_sha256")})
        for sport, summary in manifest.get("sports", {}).items():
            _insert(con, "sport_fetch_status", {
                "run_id": run.run_id, "sport": sport, "status": summary["status"],
                "detail": summary.get("detail"), "events": summary.get("events"),
                "pregame_events": summary.get("pregame_events"),
                "pregame_with_any_line": summary.get("pregame_with_any_line"),
                "pregame_complete": summary.get("pregame_complete"),
                "special_non_games": summary.get("special_non_games"),
                "recovered_from_event_page": summary.get("recovered_from_event_page"),
                "still_incomplete_json": json.dumps(summary.get("still_incomplete", [])),
                "attempt_outcomes_json": json.dumps(summary.get("attempt_outcomes", {}), sort_keys=True),
                "variant_event_counts_json": json.dumps(summary.get("variant_event_counts", {}), sort_keys=True),
                "snapshot_as_of_min_utc": summary.get("snapshot_as_of_min_utc"),
                "snapshot_as_of_max_utc": summary.get("snapshot_as_of_max_utc"),
            })

        quotes = 0
        for event in events:
            sport, event_id = event["sport"], str(event["event_id"])
            prov = event.get("provenance") or {}
            game_key = f"{sport}:BOVADA:{event_id}"
            cohort_id = cohort_of[f"{sport}:{event_id}"]
            captured = _as_of(event)
            board_row = {k: v for k, v in event.items() if k != "quotes"}
            _insert(con, "events", {
                "batch_id": batch_id, "sport": sport, "event_id": event_id, "game_key": game_key,
                "game": event.get("description") or f"{event.get('away')} @ {event.get('home')}",
                "away": event.get("away") or "", "home": event.get("home") or "",
                "start_utc": event.get("start_utc"), "quote_captured_utc": captured,
                "quote_cohort_id": cohort_id, "pregame_quote": int(not event.get("live")),
                "physical_game": int(bool(event["physical_game"])), "bovada_url": event.get("public_url"),
                "raw_board_json": json.dumps(board_row, sort_keys=True),
                "attempt_id": prov.get("attempt_id"), "received_utc": prov.get("received_utc"),
                "cdn_age_seconds": prov.get("cdn_age_seconds"),
                "last_modified_utc": event.get("last_modified_utc"),
            })
            for q in event.get("quotes", []):
                status = q["quote_status"]
                if not event["physical_game"]:
                    status = "SPECIAL_NON_GAME"
                odds = q.get("odds_american")
                _insert(con, "market_quotes", {
                    "quote_id": _quote_id(run.run_id, sport, event_id, q["market"], q["side"]),
                    "batch_id": batch_id, "sport": sport, "event_id": event_id, "game_key": game_key,
                    "quote_cohort_id": cohort_id, "quote_captured_utc": captured,
                    "market": q["market"], "period": q.get("period") or "Game", "side": q["side"],
                    "line": q.get("line"), "odds_american": odds,
                    "break_even_probability": break_even_probability(odds),
                    "quote_status": status, "source_file": f"{run.run_id}/board.json",
                    "source_sha256": run.board_sha256, "selection": q.get("selection"),
                    "odds_decimal": q.get("odds_decimal"), "status_detail": q.get("status_detail"),
                    "market_id": q.get("market_id"), "outcome_id": q.get("outcome_id"),
                    "price_id": q.get("price_id"), "attempt_id": prov.get("attempt_id"),
                    "received_utc": prov.get("received_utc"),
                })
                quotes += 1
        problems = con.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise IngestError(f"{len(problems)} foreign-key violations")
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return {"run_id": run.run_id, "status": "INGESTED", "events": len(events), "quotes": quotes,
            "cohorts": len(cohorts), "attempts": len(run.attempts),
            "sports": {s: v["status"] for s, v in manifest.get("sports", {}).items()}}


def pending_captures(con: sqlite3.Connection, captures_root: Path) -> list[Path]:
    """Capture directories (with a manifest) not yet in fetch_runs, oldest first."""
    done = {r["run_id"] for r in con.execute("SELECT run_id FROM fetch_runs")}
    run_dirs = (manifest.parent for manifest in sorted(Path(captures_root).glob("*/manifest.json")))
    return [run_dir for run_dir in run_dirs if run_dir.name not in done]
