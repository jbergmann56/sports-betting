"""Shared pieces of the daily pipelines: capture selection, slate filtering, run folder, outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from gambling.betsheets.export import write_csv, write_excel
from gambling.config import PACKAGE_ROOT

VALIDATION_STATUS = "UNVALIDATED_GENERALIZED_WRAPPER"
CENTRAL = ZoneInfo("America/Chicago")


class PipelineError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_commit() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PACKAGE_ROOT, capture_output=True, text=True,
                             timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def latest_capture(captures: Path, sport: str) -> Path:
    """Newest capture run folder with a quotes.csv containing ``sport`` rows."""
    for run in sorted((p for p in Path(captures).iterdir() if (p / "quotes.csv").is_file()), reverse=True):
        with open(run / "quotes.csv", newline="", encoding="utf-8") as f:
            if any(r["sport"] == sport for r in csv.DictReader(f)):
                return run / "quotes.csv"
    raise PipelineError(f"no capture with {sport} quotes under {captures}")


def central_date(start_utc: str) -> str:
    return datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(CENTRAL).date().isoformat()


def write_slate_capture(quotes_csv: Path, sport: str, slate: str, dest: Path) -> int:
    """Copy the capture rows of ``sport`` games starting on ``slate`` (Central) to ``dest``; return the count."""
    with open(quotes_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = [r for r in reader if r["sport"] == sport and central_date(r["start_utc"]) == slate]
    with open(dest, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def new_run_dir(out_root: Path, sport: str, slate: str, started: datetime) -> tuple[str, Path]:
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(out_root) / "daily" / sport / slate / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "inputs").mkdir()
    return run_id, run_dir


def finish(run_dir: Path, rows: list[dict], manifest: dict, now: Optional[datetime]) -> dict:
    """Write betsheet.csv/.xlsx and manifest.json; return the manifest (with run_dir)."""
    sheet_sha = write_csv(rows, run_dir / "betsheet.csv")
    manifest["finished_utc"] = (now or datetime.now(timezone.utc)).isoformat()
    manifest["outputs"] = {**manifest.get("outputs", {}), "betsheet_csv_sha256": sheet_sha, "rows": len(rows),
                           "sheet_status": dict(sorted(Counter(r["status"] for r in rows).items()))}
    try:
        write_excel(rows, run_dir / "betsheet.xlsx", provenance={k: json.dumps(v) if isinstance(v, dict) else v
                                                                  for k, v in manifest.items() if k != "outputs"})
        manifest["outputs"]["betsheet_xlsx_sha256"] = sha(run_dir / "betsheet.xlsx")
    except RuntimeError as exc:  # openpyxl missing: the CSV is the record
        manifest["outputs"]["betsheet_xlsx_sha256"] = None
        manifest["outputs"]["betsheet_xlsx_note"] = str(exc)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "run_dir": str(run_dir)}
