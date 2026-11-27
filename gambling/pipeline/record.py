"""Record a finished daily pipeline run in the rolling database (migration 0009, append-only).

The run folder is the source: ``manifest.json`` and ``betsheet.csv`` are re-hashed and must match the
manifest before anything is written. Recording the same run again is a no-op; a different manifest
under the same run key is refused.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class RecordError(RuntimeError):
    pass


def _f(v):
    return None if v in (None, "") else float(v)


def record_run(con: sqlite3.Connection, run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    m = json.loads(manifest_bytes)
    sheet = run_dir / "betsheet.csv"
    sheet_sha = hashlib.sha256(sheet.read_bytes()).hexdigest()
    if sheet_sha != m["outputs"]["betsheet_csv_sha256"]:
        raise RecordError("betsheet.csv does not match the manifest hash; not recorded")
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'pipeline_runs'").fetchone():
        raise RecordError("database lacks migration 0009 (pipeline_runs)")
    key = f"{m['sport']}:{m['slate_date']}:{m['run_id']}"
    msha = hashlib.sha256(manifest_bytes).hexdigest()
    old = con.execute("SELECT manifest_sha256 FROM pipeline_runs WHERE run_key = ?", (key,)).fetchone()
    if old:
        if old[0] != msha:
            raise RecordError(f"{key} is already recorded with a different manifest")
        return {"run_key": key, "recorded": False, "rows": 0}
    with open(sheet, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != m["outputs"]["rows"]:
        raise RecordError("row count differs from the manifest")
    with con:
        con.execute("INSERT INTO pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            key, m["sport"], m["slate_date"], m["run_id"], m["pipeline"], m["validation_status"], m["started_utc"],
            m["finished_utc"], m.get("code_commit"), m["releases"].get("champion"), m["releases"].get("challenger"),
            m["inputs"]["capture_quotes_csv"]["sha256"], (m["inputs"].get("history") or {}).get("sha256"),
            sheet_sha, len(rows), manifest_bytes.decode("utf-8"), msha, str(run_dir),
            datetime.now(timezone.utc).isoformat()))
        con.executemany(
            "INSERT INTO pipeline_sheet_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(key, n, r["sport"], r["event_id"], r["start_time_utc"], r["away"], r["home"], r["market"], r["side"],
              r["selection"], _f(r["line"]), _f(r["american_odds"]), r["quote_id"], r["quote_as_of_utc"],
              r["model_release_id"], r["release_role"], r["model_status"], r["original_tier"], _f(r["p_win"]),
              _f(r["ev"]), _f(r["full_kelly"]), _f(r["adjusted_kelly"]), r["status"], r["score_as_of_utc"],
              json.dumps(r, sort_keys=True)) for n, r in enumerate(rows, 1)])
    return {"run_key": key, "recorded": True, "rows": len(rows)}
