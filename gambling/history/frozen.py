"""Read-only queries over the frozen Nov 11, 2026 archive (the original evidence).

These never write to the archive. The extracted ``history.sqlite`` is a
disposable working copy that is always opened read-only.
"""

from __future__ import annotations

import csv
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

from ..config import FROZEN_ARCHIVE_MEMBER, Paths
from ..timeutil import chicago_date

AUDIT_TABLES = ("capture_batches", "quote_cohorts", "events", "market_quotes", "model_scores", "settlements")
REPORTED_STATUSES = ("PRODUCTION_QUALIFIED", "RESEARCH_POSITIVE_EV")


def extract_frozen(paths: Paths, force: bool = False) -> Path:
    """Extract the frozen SQLite snapshot from the bundled archive (if needed)."""
    target = paths.frozen_db
    if target.exists() and not force:
        return target
    if not paths.frozen_archive.exists():
        raise FileNotFoundError(f"Missing frozen history archive: {paths.frozen_archive}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(paths.frozen_archive) as source:
        target.write_bytes(source.read(FROZEN_ARCHIVE_MEMBER))
    return target


def connect_frozen(paths: Paths) -> sqlite3.Connection:
    """Read-only connection to the frozen snapshot, extracting it on first use."""
    database = extract_frozen(paths)
    con = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def latest_batch(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT batch_id FROM capture_batches ORDER BY min_quote_utc DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("No frozen capture batches available")
    return str(row["batch_id"])


def audit(con: sqlite3.Connection) -> dict:
    """Record counts plus SQLite integrity and foreign-key checks."""
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in AUDIT_TABLES}
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = con.execute("PRAGMA foreign_key_check").fetchall()
    return {"integrity": integrity, "foreign_key_errors": len(foreign_keys),
            "counts": counts, "latest_batch": latest_batch(con)}


def frozen_scores(con: sqlite3.Connection, date: str, batch: str | None = None) -> dict:
    """Saved production/research score rows for games on a Central-time date in one batch."""
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
    flagged = [dict(r) for r in scores if (r["sport"], r["event_id"]) in game_ids]
    statuses = Counter(r["action_status"] for r in flagged)
    return {"date": date, "batch": selected, "games": len(game_ids),
            "status_counts": dict(statuses),
            "qualified_and_research": [r for r in flagged if r["action_status"] in REPORTED_STATUSES]}


def research_parlays(paths: Paths, date: str, limit: int = 8) -> dict:
    """Archived hypothetical parlay observations. Never live bet tickets."""
    path = paths.data_dir / f"{date.replace('-', '')}_theoretical_parlays.csv"
    if not path.exists():
        return {"date": date, "status": "NO_FROZEN_PARLAY_COHORT", "rows": []}
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return {"date": date, "status": "RESEARCH_ONLY_UNVERIFIED_BOOK_PRICE",
            "total": len(rows), "rows": rows[:limit]}
