"""NBA daily pipeline around the frozen R4 (V27) scorer.

Steps (each recorded in ``manifest.json`` with SHA-256 hashes):

1. **Quotes:** a Bovada capture ``quotes.csv`` (``gambling fetch``). The scorer's quote JSON is built with
   the archived builder's rules (complete six-side pregame boards whose Central-time start date is the
   slate date; a quote at or after the start is an error).
2. **History:** the frozen base history (through 2026-11-11, hash-checked) plus recorded ESPN finals
   from ``official_game_results`` up to the day before the slate, written to a NEW file in the run
   folder. Team names the base never used stop the run unless explicitly allowed. The scorer itself
   rejects history more than 7 days stale.
3. **Scoring:** the unchanged ``legacy_models/nba_r4/nba.py score`` (it verifies its own release hashes).
4. **Sheet:** every quoted side of the slate x R4 champion and the BLOCKED R3 challenger, authority from
   the release registry at quote time, written as CSV and Excel.

Nothing is written to ``gambling.sqlite``; the scoring database is opened read-only. Each run gets its own
new folder ``<data>/daily/NBA/<date>/<run_id>/``; nothing is overwritten.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from gambling.core.quotes import complete_board, from_capture_csv
from gambling.models.nba import r4_legacy as r4
from gambling.results.espn import nba_history_rows, write_nba_history
from gambling.pipeline.common import CENTRAL, VALIDATION_STATUS, PipelineError, finish, git_commit, new_run_dir, sha
from gambling.pipeline.common import latest_capture as _latest_capture
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous

PIPELINE_ID = "gambling.pipeline.nba/1"
BASE_HISTORY = r4.FIXTURE / "inputs" / "nba_history_through_2026-11-11.csv"
STALE_DAYS = 7  # the frozen scorer's own limit
_sha = sha


def latest_capture(captures: Path, sport: str = "NBA") -> Path:
    return _latest_capture(captures, sport)


def slate_quotes(quotes_csv: Path, slate: str) -> list:
    """All NBA quote sides whose game starts on the slate date (Central), completed to six sides."""
    qs = [q for q in from_capture_csv(quotes_csv, sport="NBA")
          if datetime.fromisoformat(q.start_utc.replace("Z", "+00:00")).astimezone(CENTRAL).date().isoformat() == slate]
    return complete_board(qs)


def run_nba_daily(slate: str, quotes_csv: Path, out_root: Path, scoring_db: Optional[Path],
                  base_history: Path = BASE_HISTORY, allow_new_names: bool = False,
                  scorer: Optional[Callable[[Path, Path], list[dict]]] = None,
                  authority: Optional[Authority] = None, now: Optional[datetime] = None) -> dict:
    """Run the pipeline for one slate date; return the manifest. ``scorer`` is for tests (default: frozen)."""
    started = now or datetime.now(timezone.utc)
    Date.fromisoformat(slate)
    quotes_csv, base_history = Path(quotes_csv), Path(base_history)
    if base_history.resolve() == BASE_HISTORY.resolve() and _sha(base_history) != r4.HISTORY_SHA:
        raise PipelineError("frozen base history hash mismatch")
    run_id, run_dir = new_run_dir(out_root, "NBA", slate, started)
    inputs = run_dir / "inputs"

    # 1) quotes
    quotes_json = r4.quotes_json_from_capture(quotes_csv, slate)
    # bytes, not text mode: Windows would write CRLF and the file would no longer match the frozen hash
    (inputs / f"{slate}_nba_quotes.json").write_bytes(quotes_json.encode("utf-8"))
    quotes = slate_quotes(quotes_csv, slate)
    if not quotes:
        raise PipelineError(f"capture has no NBA games starting on {slate} (Central)")
    slate_games = len(json.loads(quotes_json))

    # 2) history
    through = (Date.fromisoformat(slate) - timedelta(days=1)).isoformat()
    new = {"rows": [], "unknown_teams": [], "duplicates": []}
    if scoring_db:
        con = sqlite3.connect(f"file:{Path(scoring_db)}?mode=ro", uri=True)
        try:
            new = nba_history_rows(con, base_history, through)
        finally:
            con.close()
    if new["unknown_teams"] and not allow_new_names:
        raise PipelineError(f"ESPN finals use team names the history never used: {sorted(new['unknown_teams'])}; "
                            "pass allow_new_names only after review")
    history = inputs / f"nba_history_through_{through}.csv"
    history_sha = write_nba_history(base_history, new["rows"], history)
    with open(history, newline="", encoding="utf-8") as f:
        last = max(r["date"] for r in csv.DictReader(f))
    stale = (Date.fromisoformat(slate) - Date.fromisoformat(last)).days
    if stale > STALE_DAYS:
        raise PipelineError(f"history ends {last}, {stale} days before the slate (scorer limit {STALE_DAYS}); "
                            "run `results fetch --sport NBA` for the missing dates")

    # 3) scoring
    forecasts = (scorer or r4.run_frozen_scorer)(inputs / f"{slate}_nba_quotes.json", history)
    with open(run_dir / "forecasts.csv", "w", newline="", encoding="utf-8") as f:
        if forecasts:
            w = csv.DictWriter(f, fieldnames=list(forecasts[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(forecasts)
    scores = r4.adapt(forecasts, quotes)

    # 4) sheet
    if authority is None and scoring_db:
        authority = Authority.from_sqlite(str(scoring_db))
    rows = mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(r4.RELEASES)), None)
    as_of = sorted({q.quote_as_of_utc for q in quotes if q.quote_as_of_utc})
    manifest = {
        "pipeline": PIPELINE_ID, "validation_status": VALIDATION_STATUS, "sport": "NBA", "slate_date": slate,
        "run_id": run_id, "started_utc": started.isoformat(), "code_commit": git_commit(),
        "releases": {"champion": r4.CHAMPION, "challenger": r4.CHALLENGER, "scorer_label": r4.SCORER_LABEL,
                     "scorer_verifies": "legacy_models/nba_r4/RELEASE_HASHES.json"},
        "authority_source": str(scoring_db) if authority is not None and scoring_db else
        ("injected" if authority is not None else "NONE (no registry: sheet statuses cannot be production)"),
        "inputs": {
            "capture_quotes_csv": {"path": str(quotes_csv), "sha256": _sha(quotes_csv),
                                   "quote_as_of_utc_min": as_of[0] if as_of else None,
                                   "quote_as_of_utc_max": as_of[-1] if as_of else None},
            "scorer_quotes_json": {"sha256": _sha(inputs / f"{slate}_nba_quotes.json"), "games": slate_games},
            "history": {"base": str(base_history), "base_sha256": _sha(base_history), "sha256": history_sha,
                        "espn_rows_added": len(new["rows"]), "last_date": last, "days_before_slate": stale,
                        "duplicates_skipped": len(new["duplicates"]), "new_team_names": sorted(new["unknown_teams"])},
        },
        "outputs": {"forecasts_sha256": _sha(run_dir / "forecasts.csv"),
                    "games_quoted": len({q.event_id for q in quotes}), "games_scored": slate_games},
    }
    return finish(run_dir, rows, manifest, now)
