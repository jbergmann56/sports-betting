"""Append-only store for raw Bovada responses.

Every HTTP attempt - including failures - is written as two files:

    <run_dir>/<seq>_<label>.body        exact response bytes (decompressed)
    <run_dir>/<seq>_<label>.meta.json   URL, timings, status, headers, sha256, outcome

Files are created with exclusive mode, so an existing capture can never be
overwritten. A run directory is never reused.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from .transport import Classified, HttpResponse


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_run_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)


class CaptureStore:
    def __init__(self, root: Path, run_id: str):
        self.run_id = run_id
        self.run_dir = Path(root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._seq = 0

    def _write_new(self, path: Path, data: bytes) -> None:
        with path.open("xb") as stream:  # exclusive: refuses to overwrite
            stream.write(data)

    def record(self, label: str, resp: HttpResponse, verdict: Classified, *,
               sport: str, variant: str, attempt: int, purpose: str) -> dict[str, Any]:
        self._seq += 1
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label)[:80]
        stem = f"{self._seq:04d}_{safe}"
        body_name = f"{stem}.body"
        self._write_new(self.run_dir / body_name, resp.body)
        meta = {
            "attempt_id": f"{self.run_id}:{self._seq:04d}",
            "run_id": self.run_id,
            "sequence": self._seq,
            "sport": sport,
            "purpose": purpose,
            "variant": variant,
            "attempt": attempt,
            "url": resp.url,
            "requested_utc": _iso(resp.requested_utc),
            "received_utc": _iso(resp.received_utc),
            "http_status": resp.status,
            "network_error": resp.error,
            "response_headers": resp.headers,
            "body_file": body_name,
            "body_bytes": len(resp.body),
            "body_sha256": sha256(resp.body),
            "outcome": verdict.outcome.value,
            "outcome_detail": verdict.detail,
            "event_count": verdict.event_count,
            "cdn_age_seconds": verdict.cdn_age_seconds,
            "server_date_utc": _iso(verdict.server_date_utc),
            "snapshot_as_of_utc": _iso(verdict.snapshot_as_of_utc),
        }
        self._write_new(self.run_dir / f"{stem}.meta.json",
                        json.dumps(meta, indent=2, sort_keys=True).encode("utf-8"))
        return meta

    def write_document(self, name: str, document: Any) -> Path:
        path = self.run_dir / name
        self._write_new(path, json.dumps(document, indent=2, default=str).encode("utf-8"))
        return path


def load_attempts(run_dir: Path) -> list[tuple[dict[str, Any], bytes]]:
    """Read back every recorded attempt of a run, in sequence order."""
    run_dir = Path(run_dir)
    attempts = []
    for meta_path in sorted(run_dir.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = (run_dir / meta["body_file"]).read_bytes()
        if sha256(body) != meta["body_sha256"]:
            raise ValueError(f"Checksum mismatch for {meta_path.name}; capture altered")
        attempts.append((meta, body))
    return attempts
