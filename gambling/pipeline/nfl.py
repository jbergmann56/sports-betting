"""NFL daily pipeline: capture -> board.json -> frozen REV2-CAL/W8 model via the week driver -> sheet.

1. **Quotes:** NFL games in the capture starting on the slate date (Central), team names mapped to
   nflverse codes. Events without six offered pregame full-game sides are on the sheet as UNSCORED.
2. **Schedule/results:** an nflverse ``games.csv`` (``python -m gambling nfl-schedule``), copied into the
   run folder and hashed. The board's games must be one regular-season week W. The scorer uses
   completed games before the first gameday of W, as the frozen Week-10 run did; the run is BLOCKED
   unless every Week W-1 game is final (stale features are never scored).
3. **Scoring:** ``gambling.models.nfl.live.run_week_scorer`` (frozen score.py with only its Week-10
   literals parameterized; frozen model files).
4. **Sheet/record:** as for NBA/NHL.
"""
from __future__ import annotations

import json
from datetime import date as Date, datetime, timezone
from pathlib import Path
from typing import Optional

from gambling.core.quotes import from_capture_csv
from gambling.models.base import UNSCORED, ScoreRow
from gambling.models.nfl import live
from gambling.models.nfl.rev2_legacy import RELEASES, adapt_dual_sheet
from gambling.pipeline.common import (VALIDATION_STATUS, PipelineError, central_date, finish, git_commit,
                                      new_run_dir, sha)
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous

PIPELINE_ID = "gambling.pipeline.nfl/1"


def run_nfl_daily(slate: str, quotes_csv: Path, out_root: Path, scoring_db: Optional[Path], games_csv: Path,
                  authority: Optional[Authority] = None, now: Optional[datetime] = None) -> dict:
    started = now or datetime.now(timezone.utc)
    Date.fromisoformat(slate)
    quotes_csv, games_csv = Path(quotes_csv), Path(games_csv)
    if not games_csv.is_file():
        raise PipelineError(f"no NFL schedule at {games_csv}; run `python -m gambling nfl-schedule`")
    try:
        games = live.read_games(games_csv)
        quotes = live.coded(q for q in from_capture_csv(quotes_csv, sport="NFL") if central_date(q.start_utc) == slate)
    except live.NflInputError as exc:
        raise PipelineError(str(exc)) from exc
    if not quotes:
        raise PipelineError(f"capture has no NFL games starting on {slate} (Central)")
    board, skipped = live.board_rows(quotes)
    if not board:
        raise PipelineError(f"no NFL game on {slate} has six offered pregame sides")
    try:
        week = live.week_of(games, [(r[0], r[1]) for r in board], slate)
    except live.NflInputError as exc:
        raise PipelineError(str(exc)) from exc
    wi = live.week_inputs(games, week)
    if wi["prev_complete"] != wi["prev_games"]:
        raise PipelineError(f"Week {week - 1} has {wi['prev_complete']}/{wi['prev_games']} final games before "
                            f"{wi['cutoff']} in the schedule file; refresh it (`nfl-schedule`) after the week ends")
    run_id, run_dir = new_run_dir(out_root, "NFL", slate, started)
    inputs = run_dir / "inputs"
    live.write_board(board, inputs / "board.json")
    (inputs / "games_snapshot.csv").write_bytes(games_csv.read_bytes())
    res = live.run_week_scorer(run_dir / "work", inputs / "board.json", inputs / "games_snapshot.csv", week,
                               wi["cutoff"], wi["prev_games"])
    (run_dir / "dual_model_bet_sheet.csv").write_bytes(res["sheet_bytes"])
    score_time = started.isoformat()
    on_board = {(r[0], r[1]) for r in board}
    board_quotes = [q for q in quotes if (q.away, q.home) in on_board and q.event_id not in skipped]
    scores = adapt_dual_sheet(res["rows"], board_quotes, score_time, res["metadata"].get("adjusted_reason") or "")
    for q in quotes:
        if q.event_id in skipped:
            for rel in RELEASES:
                scores.append(ScoreRow(rel, q.quote_id, UNSCORED,
                                       reason="INCOMPLETE_OR_NOT_PREGAME_BOARD: scorer needs six OFFERED_PREGAME sides"))
    if authority is None and scoring_db:
        authority = Authority.from_sqlite(str(scoring_db))
    rows = mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(RELEASES)), None)
    as_of = sorted({q.quote_as_of_utc for q in quotes if q.quote_as_of_utc})
    manifest = {
        "pipeline": PIPELINE_ID, "validation_status": VALIDATION_STATUS, "sport": "NFL", "slate_date": slate,
        "run_id": run_id, "started_utc": started.isoformat(), "code_commit": git_commit(),
        "releases": {"champion": RELEASES[0], "challenger": RELEASES[1],
                     "driver": "frozen score.py with parameterized Week-10 literals (gambling.models.nfl.live)",
                     "driver_sha256": res["driver_sha256"]},
        "authority_source": str(scoring_db) if authority is not None and scoring_db else
        ("injected" if authority is not None else "NONE (no registry: sheet statuses cannot be production)"),
        "inputs": {
            "capture_quotes_csv": {"path": str(quotes_csv), "sha256": sha(quotes_csv),
                                   "quote_as_of_utc_min": as_of[0] if as_of else None,
                                   "quote_as_of_utc_max": as_of[-1] if as_of else None},
            "board_json": {"sha256": sha(inputs / "board.json"), "games": len(board), "skipped_events": skipped},
            "schedule": {"path": str(games_csv), "sha256": sha(inputs / "games_snapshot.csv"),
                         "source": live.NFLVERSE_GAMES_URL, "week": week, "feature_cutoff": wi["cutoff"],
                         "prior_week_final": f"{wi['prev_complete']}/{wi['prev_games']}"},
        },
        "outputs": {"scorer_metadata": res["metadata"], "games_quoted": len({q.event_id for q in quotes})},
    }
    return finish(run_dir, rows, manifest, now)
