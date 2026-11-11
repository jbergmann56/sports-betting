"""Read-side queries over the rolling history (plain dicts, ready for CLI or app)."""

from __future__ import annotations

import sqlite3
from typing import Any

from .migrate import applied_migrations

STATUS_TABLES = ("capture_batches", "quote_cohorts", "events", "market_quotes", "model_scores",
                 "settlements", "fetch_runs", "fetch_attempts")


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


def status(con: sqlite3.Connection) -> dict[str, Any]:
    migrations = applied_migrations(con)
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in STATUS_TABLES}
    last_run = con.execute("SELECT run_id, started_utc, all_sports_ok, snapshot_skew_seconds FROM fetch_runs "
                           "ORDER BY started_utc DESC LIMIT 1").fetchone()
    return {
        "schema_version": con.execute("PRAGMA user_version").fetchone()[0],
        "migrations": [{"version": r["version"], "name": r["name"], "sha256": r["sha256"],
                        "applied_utc": r["applied_utc"]} for r in migrations.values()],
        "imports": _rows(con.execute("SELECT import_id, kind, source_sha256, imported_utc FROM history_imports")),
        "counts": counts,
        "last_fetch_run": dict(last_run) if last_run else None,
        "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_errors": len(con.execute("PRAGMA foreign_key_check").fetchall()),
    }


def latest_quotes(con: sqlite3.Connection, sport: str | None = None, *, upcoming_after: str | None = None,
                  offered_only: bool = True, limit: int = 500) -> list[dict[str, Any]]:
    """Newest observation per game/market/side, optionally for games starting after a UTC time."""
    sql = ["SELECT sport, game_key, game, start_utc, market, side, selection, line, odds_american,",
           "quote_status, quote_captured_utc, batch_id FROM latest_quotes WHERE physical_game = 1"]
    args: list[Any] = []
    if sport:
        sql.append("AND sport = ?")
        args.append(sport)
    if upcoming_after:
        sql.append("AND start_utc > ?")
        args.append(upcoming_after)
    if offered_only:
        sql.append("AND quote_status IN ('OFFERED_PREGAME', 'OPEN')")
    sql.append("ORDER BY start_utc, game_key, market, side LIMIT ?")
    args.append(limit)
    return _rows(con.execute(" ".join(sql), args))


def line_history(con: sqlite3.Connection, game_key: str) -> list[dict[str, Any]]:
    return _rows(con.execute(
        "SELECT market, side, selection, quote_captured_utc, batch_id, quote_status, line, odds_american, "
        "line_change, odds_change, observation_number FROM line_movement WHERE game_key = ? "
        "ORDER BY market, side, observation_number", (game_key,)))


def find_games(con: sqlite3.Connection, text: str, limit: int = 20) -> list[dict[str, Any]]:
    return _rows(con.execute(
        "SELECT game_key, sport, game, start_utc, COUNT(*) AS observations, MAX(quote_captured_utc) AS last_seen "
        "FROM events WHERE game LIKE ? GROUP BY game_key ORDER BY last_seen DESC LIMIT ?",
        (f"%{text}%", limit)))


def capture_health(con: sqlite3.Connection, since_date: str | None = None) -> dict[str, Any]:
    where, args = ("WHERE run_date_utc >= ?", [since_date]) if since_date else ("", [])
    return {
        "sports": _rows(con.execute(f"SELECT * FROM sport_health {where} ORDER BY run_date_utc, sport", args)),
        "attempts": _rows(con.execute(f"SELECT * FROM capture_health {where} "
                                      "ORDER BY run_date_utc, sport, purpose, variant, outcome", args)),
    }
