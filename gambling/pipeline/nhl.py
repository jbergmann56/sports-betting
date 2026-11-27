"""NHL daily pipeline around the frozen Day-0 scorer (research only: no NHL release is wager-authorized).

1. **Quotes:** the capture rows of NHL games starting on the slate date (Central) are copied to
   ``inputs/quotes.csv`` (the scorer input; hashed).
2. **Scoring:** the unchanged ``day0_production.py`` and original capture adapter on the frozen controls
   (``OBSERVED_PRICE_ALL_CONTROLS.csv``, frozen through 2025), all hash-checked before running. No other
   daily input exists for this release: 2026-27 games are scored on prior-season control segments.
3. **Sheet:** every quoted side x the champion and challenger of its market, registry authority.

Output and recording as for NBA (``gambling/pipeline/common.py``, ``record.py``).
"""
from __future__ import annotations

from datetime import date as Date, datetime, timezone
from pathlib import Path
from typing import Optional

from gambling.betsheets.nhl import build_capture_sheet
from gambling.models.nhl import day0_legacy as d0
from gambling.pipeline.common import (VALIDATION_STATUS, PipelineError, finish, git_commit, new_run_dir, sha,
                                      write_slate_capture)
from gambling.scoring.sheet import Authority

PIPELINE_ID = "gambling.pipeline.nhl/1"


def run_nhl_daily(slate: str, quotes_csv: Path, out_root: Path, scoring_db: Optional[Path],
                  inputs: Optional[d0.Day0Inputs] = None, authority: Optional[Authority] = None,
                  now: Optional[datetime] = None) -> dict:
    started = now or datetime.now(timezone.utc)
    Date.fromisoformat(slate)
    quotes_csv = Path(quotes_csv)
    inputs = inputs or d0.Day0Inputs.from_fixture()
    inputs.verify()
    run_id, run_dir = new_run_dir(out_root, "NHL", slate, started)
    slate_csv = run_dir / "inputs" / "quotes.csv"
    n = write_slate_capture(quotes_csv, "NHL", slate, slate_csv)
    if n == 0:
        raise PipelineError(f"capture has no NHL games starting on {slate} (Central)")
    if authority is None and scoring_db:
        authority = Authority.from_sqlite(str(scoring_db))
    rows = build_capture_sheet(slate_csv, authority, inputs)
    as_of = sorted({r["quote_as_of_utc"] for r in rows if r.get("quote_as_of_utc")})
    manifest = {
        "pipeline": PIPELINE_ID, "validation_status": VALIDATION_STATUS, "sport": "NHL", "slate_date": slate,
        "run_id": run_id, "started_utc": started.isoformat(), "code_commit": git_commit(),
        "releases": {"market_releases": {m: list(p) for m, p in d0.MARKET_RELEASES.items()},
                     "wagering": "NONE: every NHL release is research-only"},
        "authority_source": str(scoring_db) if authority is not None and scoring_db else
        ("injected" if authority is not None else "NONE (no registry: sheet statuses cannot be production)"),
        "inputs": {
            "capture_quotes_csv": {"path": str(quotes_csv), "sha256": sha(quotes_csv),
                                   "quote_as_of_utc_min": as_of[0] if as_of else None,
                                   "quote_as_of_utc_max": as_of[-1] if as_of else None},
            "scorer_quotes_csv": {"sha256": sha(slate_csv), "rows": n},
            "frozen": {"scorer_sha256": d0.SCORER_SHA, "controls_sha256": d0.CONTROLS_SHA,
                       "original_adapter_sha256": d0.ADAPTER_SHA, "controls_frozen_through": "2025"},
        },
        "outputs": {"games_quoted": len({r["event_id"] for r in rows})},
    }
    return finish(run_dir, rows, manifest, now)
