"""One-time import of the frozen archive's rows into the rolling database.

The frozen SQLite file is attached read-only and copied table by table with
explicit column lists. Counts and the archive hash are recorded in
``history_imports``; the import refuses to run twice.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..timeutil import utcnow

# Parent tables first so foreign keys hold during the copy.
BASELINE_TABLES = ("capture_batches", "quote_cohorts", "events", "market_quotes", "model_scores",
                   "source_files", "settlements", "wager_links", "official_game_results", "quote_outcomes")
IMPORT_ID = "FROZEN_ARCHIVE_20261111_V28"


class BaselineError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def baseline_imported(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT 1 FROM history_imports WHERE import_id=?", (IMPORT_ID,)).fetchone() is not None


def import_frozen(con: sqlite3.Connection, frozen_db: Path, archive: Path) -> dict[str, int]:
    """Copy every frozen row into the (migrated) rolling database. Returns row counts."""
    if baseline_imported(con):
        raise BaselineError("Frozen archive already imported")
    occupied = [t for t in BASELINE_TABLES if con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()]
    if occupied:
        raise BaselineError(f"Baseline must be imported into empty tables; found rows in {occupied}")

    con.execute("ATTACH DATABASE ? AS frozen", (f"file:{Path(frozen_db).as_posix()}?mode=ro",))
    try:
        counts: dict[str, int] = {}
        con.execute("BEGIN")
        try:
            for table in BASELINE_TABLES:
                columns = [r["name"] for r in con.execute(f"PRAGMA frozen.table_info({table})")]
                cols = ", ".join(columns)
                con.execute(f"INSERT INTO main.{table} ({cols}) SELECT {cols} FROM frozen.{table}")
                source = con.execute(f"SELECT COUNT(*) FROM frozen.{table}").fetchone()[0]
                copied = con.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
                if source != copied:
                    raise BaselineError(f"{table}: copied {copied} of {source} rows")
                counts[table] = copied
            problems = con.execute("PRAGMA main.foreign_key_check").fetchall()
            if problems:
                raise BaselineError(f"{len(problems)} foreign-key violations after import")
            con.execute("INSERT INTO history_imports VALUES (?,?,?,?,?,?)",
                        (IMPORT_ID, "FROZEN_ARCHIVE", str(archive), file_sha256(archive),
                         utcnow().isoformat(), json.dumps(counts, sort_keys=True)))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.execute("DETACH DATABASE frozen")
    return counts
