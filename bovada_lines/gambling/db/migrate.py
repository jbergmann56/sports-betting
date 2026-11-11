"""Numbered SQL migrations with recorded hashes.

Each ``migrations/NNNN_name.sql`` is applied once, inside a transaction, and
recorded in ``schema_migrations`` with its SHA-256. If an already-applied file
later changes, :func:`apply_migrations` refuses to run: schema history is
append-only just like the data.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..timeutil import utcnow

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    sha256: str


def available_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"Badly named migration file: {path.name}")
        # Hash with normalized line endings so a CRLF checkout is not a "changed" migration.
        sql = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        found.append(Migration(int(match.group(1)), match.group(2), sql,
                               hashlib.sha256(sql.encode("utf-8")).hexdigest()))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"Migrations must be numbered 0001.. without gaps, found {versions}")
    return found


def connect(path: Path) -> sqlite3.Connection:
    """Read-write connection with foreign keys enforced and manual transactions."""
    # uri=True lets the baseline import ATTACH the frozen file read-only (file:...?mode=ro).
    con = sqlite3.connect(Path(path).resolve().as_uri(), isolation_level=None, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def applied_migrations(con: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
    if not exists:
        return {}
    return {r["version"]: r for r in con.execute("SELECT * FROM schema_migrations ORDER BY version")}


def apply_migrations(con: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order. Returns the names applied."""
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL)""")
    done = applied_migrations(con)
    known = {m.version for m in available_migrations(directory)}
    unknown = sorted(set(done) - known)
    if unknown:
        raise MigrationError(f"Database has migrations this code does not know: {unknown}")
    applied = []
    for migration in available_migrations(directory):
        if migration.version in done:
            recorded = done[migration.version]["sha256"]
            if recorded != migration.sha256:
                raise MigrationError(
                    f"Migration {migration.version:04d}_{migration.name} changed after it was applied "
                    f"(recorded {recorded[:12]}, file {migration.sha256[:12]}). Add a new migration instead.")
            continue
        try:
            con.execute("BEGIN")
            for statement in _statements(migration.sql):
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations (version, name, sha256, applied_utc) VALUES (?,?,?,?)",
                        (migration.version, migration.name, migration.sha256, utcnow().isoformat()))
            con.execute(f"PRAGMA user_version = {migration.version}")
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        applied.append(f"{migration.version:04d}_{migration.name}")
    return applied


def _statements(sql: str) -> list[str]:
    """Split a migration into statements, keeping CREATE TRIGGER ... END blocks whole."""
    statements, buffer = [], []
    for line in sql.split("\n"):
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        candidate = "\n".join(buffer)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer = []
    if "".join(buffer).strip():
        raise MigrationError("Migration ends with an incomplete statement")
    return statements
