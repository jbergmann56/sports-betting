"""CLI for auditing saved Gambling project evidence and capturing Bovada odds.

`fetch` reads Bovada's public odds feed (read-only). No sportsbook
authentication, stake submission, or unverified model approximation takes
place in this package.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARCHIVE = DATA / "GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip"
DATABASE = DATA / "history.sqlite"
CAPTURES = DATA / "captures"
LOCAL = ZoneInfo("America/Chicago")


def initialize(force: bool = False) -> Path:
    if DATABASE.exists() and not force:
        return DATABASE
    if not ARCHIVE.exists():
        raise FileNotFoundError(f"Missing frozen history archive: {ARCHIVE}")
    DATA.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as source:
        payload = source.read("GAMBLING_ROLLING_SCORING_HISTORY.sqlite")
    DATABASE.write_bytes(payload)
    return DATABASE


def connect() -> sqlite3.Connection:
    if not DATABASE.exists():
        initialize()
    con = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def latest_batch(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT batch_id FROM capture_batches ORDER BY min_quote_utc DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("No frozen capture batches available")
    return str(row["batch_id"])


def audit() -> dict:
    with connect() as con:
        tables = ["capture_batches", "quote_cohorts", "events", "market_quotes", "model_scores", "settlements"]
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
        result = {"integrity": integrity, "foreign_key_errors": len(foreign_keys),
                  "counts": counts, "latest_batch": latest_batch(con)}
    return result


def chicago_date(iso_time: str | None) -> str | None:
    if not iso_time:
        return None
    return datetime.fromisoformat(str(iso_time).replace("Z", "+00:00")).astimezone(LOCAL).date().isoformat()


def price_label(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:+g}" if value > 0 else f"{value:g}"


def replay(date: str, batch: str | None = None) -> dict:
    with connect() as con:
        selected = batch or latest_batch(con)
        games = con.execute("SELECT sport, event_id, game, start_utc FROM events WHERE batch_id=?", (selected,)).fetchall()
        game_ids = {(r["sport"], r["event_id"]) for r in games if chicago_date(r["start_utc"]) == date}
        scores = con.execute("""
            SELECT sport,event_id,market,selection_side,quoted_line,quoted_odds,
                   model_role,model_version,tier,model_probability,expected_value,
                   full_kelly,adjusted_kelly,action_status
            FROM model_scores WHERE batch_id=?
            ORDER BY sport,event_id,model_role,market
        """, (selected,)).fetchall()
        flagged = [dict(r) for r in scores if (r["sport"],r["event_id"]) in game_ids]
        statuses = Counter(r["action_status"] for r in flagged)
    return {"date": date, "batch": selected, "games": len(game_ids),
            "status_counts": dict(statuses),
            "qualified_and_research": [r for r in flagged if r["action_status"] in
                                       ("PRODUCTION_QUALIFIED","RESEARCH_POSITIVE_EV")]}


def research_parlays(date: str, limit: int = 8) -> dict:
    # These are historical frozen shadow observations, not live bet tickets.
    path = DATA / f"{date.replace('-', '')}_theoretical_parlays.csv"
    if not path.exists():
        return {"date": date, "status": "NO_FROZEN_PARLAY_COHORT", "rows": []}
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return {"date": date, "status": "RESEARCH_ONLY_UNVERIFIED_BOOK_PRICE",
            "total": len(rows), "rows": rows[:limit]}


def fetch(args: argparse.Namespace) -> tuple[dict, int]:
    from .bovada import FetchConfig, fetch_board, replay_run
    from .bovada.endpoints import LEAGUES

    if args.replay:
        run = replay_run(Path(args.replay))
    else:
        sports = [s.strip().upper() for s in args.sports.split(",")] if args.sports else list(LEAGUES)
        config = FetchConfig(max_age_seconds=args.max_age, all_variants=not args.first_ok,
                             recover_events=not args.no_recover)
        run = fetch_board(sports, Path(args.out), config=config)
    manifest = run.manifest()
    manifest["run_dir"] = str(run.run_dir) if run.run_dir else None
    return manifest, 0 if run.ok else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Five-sport Gambling history audit and Bovada odds capture")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Extract the read-only history snapshot from the bundled ZIP")
    init.add_argument("--force", action="store_true", help="Re-extract the provided history snapshot")
    commands.add_parser("audit", help="Count records and verify database integrity")
    score = commands.add_parser("replay", help="Show frozen production/research score rows for a historical date")
    score.add_argument("--date", default="2026-11-11")
    score.add_argument("--batch", help="Explicit original capture batch ID")
    parlay = commands.add_parser("parlays", help="Inspect captured research-only theoretical parlay slate")
    parlay.add_argument("--date", default="2026-11-11")
    parlay.add_argument("--limit", type=int, default=8)
    grab = commands.add_parser("fetch", help="Capture Bovada main-market odds (read-only, every attempt recorded)")
    grab.add_argument("--sports", help="Comma list of NFL,NCAAFB,NBA,NCAABB,NHL (default: all)")
    grab.add_argument("--out", default=str(CAPTURES), help="Capture root directory")
    grab.add_argument("--max-age", type=int, default=900, help="Reject CDN responses older than N seconds")
    grab.add_argument("--first-ok", action="store_true", help="Stop at the first usable URL variant per sport")
    grab.add_argument("--no-recover", action="store_true", help="Skip event-page recovery of incomplete games")
    grab.add_argument("--replay", metavar="RUN_DIR", help="Rebuild a captured run offline instead of fetching")
    args = parser.parse_args()
    if args.command == "init":
        print(f"Initialized local history: {initialize(force=args.force)}")
        return
    if args.command == "fetch":
        result, code = fetch(args)
        print(json.dumps(result, indent=2, default=str))
        sys.exit(code)
    if args.command == "audit":
        result = audit()
    elif args.command == "replay":
        result = replay(args.date, args.batch)
    else:
        result = research_parlays(args.date, args.limit)
    print(json.dumps(result, indent=2, default=str))
    if args.command == "audit" and (result["integrity"] != "ok" or result["foreign_key_errors"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
