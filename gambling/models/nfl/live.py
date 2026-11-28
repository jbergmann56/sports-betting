"""NFL live scoring around the frozen REV2-CAL / W8-full-slope release (docs/sports/nfl.md).

Three pieces, each validated against the archived Nov 10 board:

* **Schedule/results:** the frozen ``games_snapshot.csv`` is the nflverse ``games.csv``
  (https://github.com/nflverse/nfldata/raw/master/data/games.csv): same 46 columns, and all 7,239
  rows agree on teams, dates, weeks and scores with the nflverse file of 2026-11-28 (verified
  2026-11-28; floats were written by pandas, e.g. ``17.0`` for ``17``).
* **Board converter:** capture quotes (six OFFERED_PREGAME full-game sides per event) to the scorer's
  ``board.json`` rows ``[away, home, away_spread, away_spread_odds, home_spread_odds, away_ml,
  home_ml, total, over_odds, under_odds]`` with nflverse team codes. The Nov 10 raw Bovada payload
  converts to exactly the archived ``board.json`` rows.
* **Week driver:** the frozen ``score.py`` hard-codes Week 10 (feature week, calibration phase week,
  results cut-off ``gameday < '2026-11-12'``, prior-week completeness ``== 15``). The driver is that
  same file with ONLY those literals replaced by named parameters (``WEEK_REPLACEMENTS``); every
  replacement must match exactly once. For Week 10 and cut-off 2026-11-12 the generated text is
  byte-identical to the frozen file. The model files (``model/src``, configs) are used unchanged.
  Status: UNVALIDATED_GENERALIZED_WRAPPER until dual-run/validation (CLAUDE.md rule 10).
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import date as Date, datetime
from pathlib import Path
from typing import Iterable, Optional

from gambling.core.quotes import QuoteSide
from gambling.models.nfl.rev2_legacy import FROZEN_ZIP, NOV10_PREFIX, PINNED_MEMBERS

SEASON = 2026
NFLVERSE_GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"

# Bovada team names -> nflverse codes (nflverse teams.csv, season 2026).
TEAMS = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

# (frozen literal, template) -- applied to the frozen score.py; each must occur exactly once.
WEEK_REPLACEMENTS = (
    ("(raw.week<10)&(raw.gameday<'2026-11-12')", "(raw.week<{week})&(raw.gameday<'{cutoff}')"),
    ("week9=raw[(raw.season==2026)&(raw.week==9)]", "week9=raw[(raw.season==2026)&(raw.week=={prev_week})]"),
    ("(week9.gameday<'2026-11-12')", "(week9.gameday<'{cutoff}')"),
    ("ready=ncomplete==len(week9)==15", "ready=ncomplete==len(week9)=={prev_games}"),
    ("team_features(completed,2026,10,{})", "team_features(completed,2026,{week},{{}})"),
    ("fa['off'],fh['off'],10)", "fa['off'],fh['off'],{week})"),
    ("probability(cfg,r['market'],10,mlanchor)", "probability(cfg,r['market'],{week},mlanchor)"),
    ("season=2026,week=10,away=a", "season=2026,week={week},away=a"),
    ("json.dump(dict(week=10,season=2026", "json.dump(dict(week={week},season=2026"),
)
FROZEN_SCORE_PY = NOV10_PREFIX + "scoring/score.py"
MODEL_MEMBERS = "scoring/model/"


class NflInputError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def frozen_score_py(zip_path: Path = FROZEN_ZIP) -> str:
    with zipfile.ZipFile(zip_path) as z:
        data = z.read(FROZEN_SCORE_PY)
    if _sha(data) != PINNED_MEMBERS["scoring/score.py"]:
        raise NflInputError("frozen score.py hash mismatch")
    return data.decode("utf-8")


def driver_text(week: int, cutoff: str, prev_games: int, zip_path: Path = FROZEN_ZIP) -> str:
    """The frozen score.py with only the Week-10 literals replaced."""
    text = frozen_score_py(zip_path)
    params = dict(week=week, prev_week=week - 1, cutoff=cutoff, prev_games=prev_games)
    for old, new in WEEK_REPLACEMENTS:
        if text.count(old) != 1:
            raise NflInputError(f"frozen score.py literal not found exactly once: {old!r}")
        text = text.replace(old, new.format(**params))
    return text


# ------------------------------------------------------------------ schedule (nflverse games.csv)
def read_games(games_csv: Path) -> list[dict]:
    with open(games_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    need = {"game_id", "season", "game_type", "week", "gameday", "away_team", "home_team", "away_score",
            "home_score"}
    if not rows or not need <= set(rows[0]):
        raise NflInputError(f"{games_csv} is not an nflverse games.csv")
    return rows


def _norm(t: str) -> str:
    return {"OAK": "LV", "SD": "LAC", "STL": "LA"}.get(t, t)


def week_of(games: list[dict], pairs: Iterable[tuple[str, str]], slate: str) -> int:
    """nflverse regular-season week of the board's games (all must agree; gameday within a day of the slate)."""
    d = Date.fromisoformat(slate)
    weeks = set()
    for a, h in pairs:
        hit = [g for g in games if g["season"] == str(SEASON) and g["game_type"] == "REG" and _norm(g["away_team"]) == a
               and _norm(g["home_team"]) == h and abs((Date.fromisoformat(g["gameday"]) - d).days) <= 1]
        if len(hit) != 1:
            raise NflInputError(f"{a} @ {h} on {slate}: {len(hit)} matching regular-season games in the schedule")
        weeks.add(int(hit[0]["week"]))
    if len(weeks) != 1:
        raise NflInputError(f"board spans weeks {sorted(weeks)}")
    return weeks.pop()


def week_inputs(games: list[dict], week: int) -> dict:
    """Cut-off (first gameday of the week) and prior-week completeness, as the frozen Week-10 run used them."""
    wk = [g for g in games if g["season"] == str(SEASON) and g["game_type"] == "REG" and int(g["week"]) == week]
    prev = [g for g in games if g["season"] == str(SEASON) and g["game_type"] == "REG" and int(g["week"]) == week - 1]
    cutoff = min(g["gameday"] for g in wk)
    done = sum(1 for g in prev if g["away_score"] not in ("", "NA") and g["home_score"] not in ("", "NA")
               and g["gameday"] < cutoff)
    return {"cutoff": cutoff, "prev_games": len(prev), "prev_complete": done}


# ------------------------------------------------------------------ board converter
def coded(quotes: Iterable[QuoteSide]) -> list[QuoteSide]:
    """Quote sides with nflverse team codes as away/home/selection (what the scorer and adapter use)."""
    out = []
    for q in quotes:
        a, h = TEAMS.get(q.away), TEAMS.get(q.home)
        if a is None or h is None:
            raise NflInputError(f"unknown NFL team name: {q.away if a is None else q.home!r}")
        sel = {q.away: a, q.home: h}.get(q.selection, q.selection)
        out.append(replace(q, away=a, home=h, selection=sel))
    return out


def board_rows(quotes: Iterable[QuoteSide]) -> tuple[list[list], list[str]]:
    """board.json rows for events with all six offered pregame sides; returns (rows, skipped event ids)."""
    events: dict[str, dict] = {}
    order: list[str] = []
    for q in quotes:
        if q.event_id not in events:
            events[q.event_id] = {}
            order.append(q.event_id)
        events[q.event_id][(q.market, q.side)] = q
    rows, skipped = [], []
    for eid in order:
        s = events[eid]
        need = [("Spread", "Away"), ("Spread", "Home"), ("Moneyline", "Away"), ("Moneyline", "Home"),
                ("Total", "Over"), ("Total", "Under")]
        if any(k not in s or s[k].quote_status != "OFFERED_PREGAME" or s[k].american_odds is None for k in need):
            skipped.append(eid)
            continue
        ref = s[("Spread", "Away")]
        rows.append([ref.away, ref.home, s[("Spread", "Away")].line, s[("Spread", "Away")].american_odds,
                     s[("Spread", "Home")].american_odds, s[("Moneyline", "Away")].american_odds,
                     s[("Moneyline", "Home")].american_odds, s[("Total", "Over")].line,
                     s[("Total", "Over")].american_odds, s[("Total", "Under")].american_odds])
    return rows, skipped


def _jsonable(rows: list[list]) -> list[list]:
    return [[int(v) if isinstance(v, float) and v.is_integer() and i not in (2, 7) else v for i, v in enumerate(r)]
            for r in rows]


def write_board(rows: list[list], path: Path) -> None:
    Path(path).write_bytes(json.dumps(_jsonable(rows)).encode("utf-8"))


# ------------------------------------------------------------------ run
def run_week_scorer(workdir: Path, board_json: Path, games_csv: Path, week: int, cutoff: str, prev_games: int,
                    zip_path: Path = FROZEN_ZIP) -> dict:
    """Run the week driver with the frozen model files; return rows, metadata and the driver hash."""
    workdir = Path(workdir)
    scoring = workdir / "scoring"
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith(NOV10_PREFIX + MODEL_MEMBERS) and not name.endswith("/"):
                dest = scoring / name[len(NOV10_PREFIX + "scoring/"):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(name))
        cfg = z.read(NOV10_PREFIX + "scoring/model/data/champion_config_preserved.json")
    if _sha(cfg) != PINNED_MEMBERS["scoring/model/data/champion_config_preserved.json"]:
        raise NflInputError("frozen champion config hash mismatch")
    text = driver_text(week, cutoff, prev_games, zip_path)
    (scoring / "score.py").write_bytes(text.encode("utf-8"))
    (scoring / "board.json").write_bytes(Path(board_json).read_bytes())
    (scoring / "games_snapshot.csv").write_bytes(Path(games_csv).read_bytes())
    done = subprocess.run([sys.executable, "-B", "score.py"], cwd=scoring, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-2000:])
    with open(scoring / "dual_model_bet_sheet.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    meta = json.loads((scoring / "metadata.json").read_text(encoding="utf-8"))
    return {"rows": rows, "metadata": meta, "driver_sha256": _sha(text.encode("utf-8")),
            "sheet_bytes": (scoring / "dual_model_bet_sheet.csv").read_bytes()}


__all__ = ["TEAMS", "WEEK_REPLACEMENTS", "NflInputError", "board_rows", "coded", "driver_text", "read_games",
           "run_week_scorer", "week_inputs", "week_of", "write_board"]
