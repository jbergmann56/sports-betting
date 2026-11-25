"""Persistent, append-only rolling history (SQLite)."""

from __future__ import annotations

import sqlite3

from ..config import Paths
from ..history.frozen import extract_frozen
from .baseline import baseline_imported, import_frozen
from .ingest import IngestError, ingest_capture, load_capture, pending_captures
from .migrate import MigrationError, apply_migrations, connect


def open_database(paths: Paths) -> sqlite3.Connection:
    """Open the rolling database, applying any pending migrations."""
    if not paths.database.exists():
        raise FileNotFoundError(f"{paths.database} does not exist; run `python -m gambling db init` first")
    con = connect(paths.database)
    apply_migrations(con)
    return con


def init_database(paths: Paths) -> dict:
    """Create (or upgrade) the rolling database and import the frozen archive once."""
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    con = connect(paths.database)
    try:
        applied = apply_migrations(con)
        counts = None
        if not baseline_imported(con):
            counts = import_frozen(con, extract_frozen(paths), paths.frozen_archive)
        return {"database": str(paths.database), "migrations_applied": applied,
                "baseline_imported_counts": counts}
    finally:
        con.close()


__all__ = ["open_database", "init_database", "connect", "apply_migrations", "import_frozen",
           "ingest_capture", "load_capture", "pending_captures", "IngestError", "MigrationError"]
