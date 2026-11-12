"""Point-in-time archive of the rolling database.

Uses SQLite's online backup API for a consistent copy, then writes a new,
uniquely named ZIP with a manifest of counts, migrations and hashes. Existing
archives are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from ..timeutil import utcnow
from .queries import status


def export_snapshot(con: sqlite3.Connection, archives_dir: Path) -> Path:
    archives_dir = Path(archives_dir)
    archives_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = archives_dir / f"GAMBLING_HISTORY_{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "gambling.sqlite"
        copy = sqlite3.connect(copy_path)
        try:
            con.backup(copy)
        finally:
            copy.close()
        data = copy_path.read_bytes()
        verify = sqlite3.connect(copy_path)
        try:
            verify.row_factory = sqlite3.Row
            manifest = status(verify)
        finally:
            verify.close()
    manifest.update({"created_utc": utcnow().isoformat(), "database_file": "gambling.sqlite",
                     "database_sha256": hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED, compresslevel=7) as archive:
        archive.writestr("gambling.sqlite", data)
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2, default=str))
    return target
