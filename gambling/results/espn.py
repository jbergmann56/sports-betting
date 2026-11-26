"""ESPN scoreboard results collector (all five sports).

Fetches the public ESPN site-API scoreboard for a sport and date, stores the raw response with
URL, request date, retrieval time and SHA-256 (``espn_result_captures``, migration 0007), parses
every event (``espn_result_observations``), and records completed games in the existing
``official_game_results`` table.

Rules:

* **Finals only.** A game becomes a recorded final only when ESPN reports ``completed`` with
  state ``post``. Postponed, canceled and in-progress games are observed but not recorded.
* **Never overwrite.** The first recorded final stands. A later observation with different scores
  is appended to ``espn_result_conflicts`` for review, and ``official_game_results`` is not changed.
* **Names are verbatim.** Team names are ESPN's ``displayName``. Nothing is renamed to match another
  source. Mismatches against a model's history (for example "LA Clippers" vs "Los Angeles Clippers")
  are reported by ``nba_history_rows``.
* **Dates.** ``game_date`` is the US/Eastern calendar date of the start (the convention of the
  existing NBA history and ``official_game_results`` rows).

The network fetch runs on the user's machine (``python -m gambling results fetch``). The workspace
sandbox cannot reach ESPN, so tests use archived ESPN responses from the golden fixtures.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

COLLECTOR = "gambling.results.espn/1"
BASE = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {
    "NBA": ("basketball/nba", {}),
    "NHL": ("hockey/nhl", {}),
    "NFL": ("football/nfl", {}),
    "NCAAFB": ("football/college-football", {"groups": "80", "limit": "1000"}),        # FBS
    "NCAABB": ("basketball/mens-college-basketball", {"groups": "50", "limit": "1000"}),  # Division I
}
EASTERN = ZoneInfo("America/New_York")


class ResultsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Capture:
    sport: str
    url: str
    requested_date: str
    retrieved_utc: str
    body: bytes

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def capture_id(self) -> str:
        return hashlib.sha256(self.body + self.retrieved_utc.encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    sport: str
    espn_game_id: str
    start_utc: Optional[str]
    game_date: str
    status_name: str
    completed: bool
    away_id: Optional[str]
    home_id: Optional[str]
    away_team: Optional[str]
    home_team: Optional[str]
    away_score: Optional[int]
    home_score: Optional[int]
    neutral_site: Optional[bool]

    @property
    def is_final(self) -> bool:
        return self.completed and self.away_score is not None and self.home_score is not None


def scoreboard_url(sport: str, day: str) -> str:
    if sport not in LEAGUES:
        raise ResultsError(f"unknown sport {sport!r}")
    path, extra = LEAGUES[sport]
    params = {"dates": Date.fromisoformat(day).strftime("%Y%m%d"), **extra}
    return f"{BASE}/{path}/scoreboard?" + "&".join(f"{k}={v}" for k, v in params.items())


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "gambling-results-collector/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https ESPN host
        if resp.status != 200:
            raise ResultsError(f"{url}: HTTP {resp.status}")
        return resp.read()


def fetch(sport: str, day: str, getter: Optional[Callable[[str], bytes]] = None,
          now: Optional[Callable[[], datetime]] = None) -> Capture:
    url = scoreboard_url(sport, day)
    body = (getter or _http_get)(url)
    retrieved = (now or (lambda: datetime.now(timezone.utc)))().isoformat()
    json.loads(body)  # must be JSON; stored even if it has no events
    return Capture(sport, url, day, retrieved, body)


def _int(v) -> Optional[int]:
    if v in (None, ""):
        return None
    if isinstance(v, dict):  # some ESPN payloads wrap the score
        v = v.get("value", v.get("displayValue"))
    return int(float(v))


def parse(capture: Capture) -> list[Observation]:
    data = json.loads(capture.body)
    out = []
    for e in data.get("events", []):
        comp = e["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        if set(teams) != {"home", "away"}:
            raise ResultsError(f"event {e.get('id')} does not have one home and one away competitor")
        status = (comp.get("status") or e.get("status"))["type"]
        start = e.get("date")
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
        game_date = start_dt.astimezone(EASTERN).date().isoformat() if start_dt else capture.requested_date
        completed = bool(status.get("completed")) and status.get("state") == "post"
        a, h = teams["away"], teams["home"]
        out.append(Observation(
            capture.sport, str(e["id"]), start_dt.isoformat() if start_dt else None, game_date,
            status.get("name", ""), completed, str(a["team"].get("id")), str(h["team"].get("id")),
            a["team"].get("displayName"), h["team"].get("displayName"),
            _int(a.get("score")) if completed else None, _int(h.get("score")) if completed else None,
            comp.get("neutralSite")))
    return out


def record(con: sqlite3.Connection, capture: Capture) -> dict:
    """Store a capture, its observations and any new finals. Returns counts."""
    obs = parse(capture)
    counts = {"events": len(obs), "finals_observed": 0, "finals_recorded": 0, "finals_already_recorded": 0,
              "conflicts": 0}
    own_tx = not con.in_transaction
    if own_tx:
        con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO espn_result_captures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (capture.capture_id, capture.sport, capture.url, capture.requested_date, capture.retrieved_utc,
                     capture.body_sha256, len(capture.body), capture.body, COLLECTOR))
        for o in obs:
            con.execute("INSERT INTO espn_result_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (capture.capture_id, o.espn_game_id, o.sport, o.start_utc, o.game_date, o.status_name,
                         int(o.completed), o.away_id, o.home_id, o.away_team, o.home_team, o.away_score,
                         o.home_score, None if o.neutral_site is None else int(o.neutral_site)))
            if not o.is_final:
                continue
            counts["finals_observed"] += 1
            prior = con.execute("SELECT away_score, home_score, source_file FROM official_game_results "
                                "WHERE sport = ? AND espn_game_id = ?", (o.sport, o.espn_game_id)).fetchone()
            if prior is None:
                con.execute("INSERT INTO official_game_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (o.sport, o.espn_game_id, o.game_date, o.away_id, o.home_id, o.away_team, o.home_team,
                             o.away_score, o.home_score, "Final", capture.retrieved_utc,
                             f"espn:{capture.capture_id[:16]}"))
                counts["finals_recorded"] += 1
            elif (prior[0], prior[1]) == (o.away_score, o.home_score):
                counts["finals_already_recorded"] += 1
            else:
                con.execute("INSERT INTO espn_result_conflicts (sport, espn_game_id, recorded_away_score, "
                            "recorded_home_score, recorded_source, observed_away_score, observed_home_score, "
                            "capture_id, detected_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (o.sport, o.espn_game_id, prior[0], prior[1], prior[2], o.away_score, o.home_score,
                             capture.capture_id, capture.retrieved_utc))
                counts["conflicts"] += 1
        if own_tx:
            con.execute("COMMIT")
    except BaseException:
        if own_tx and con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return counts


def collect(con: sqlite3.Connection, sport: str, days: Iterable[str],
            getter: Optional[Callable[[str], bytes]] = None) -> list[dict]:
    return [dict(sport=sport, date=d, **record(con, fetch(sport, d, getter))) for d in days]


# ---------------------------------------------------------------------- NBA history feed
NBA_HISTORY_COLUMNS = ["game_key", "date", "season", "away", "home", "away_score", "home_score", "source",
                       "original_game_id", "holdout_flag", "market_model_eligible"]


def _nba_season(day: str) -> str:
    d = Date.fromisoformat(day)
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}/{start + 1}"


def nba_history_rows(con: sqlite3.Connection, base_history: Path, through: str) -> dict:
    """New NBA history rows from recorded ESPN finals after the base file's last date, up to ``through``.

    Never alters base rows. Returns ``rows`` (to append), ``unknown_teams`` (names the base
    history has never used, e.g. ESPN "LA Clippers" if the history only had "Los Angeles
    Clippers") and ``duplicates`` (finals whose game_key is already in the base).
    """
    with open(base_history, newline="", encoding="utf-8") as f:
        base = list(csv.DictReader(f))
    if list(base[0]) != NBA_HISTORY_COLUMNS:
        raise ResultsError("unexpected NBA history columns")
    last = max(r["date"] for r in base)
    keys = {r["game_key"] for r in base}
    known = {r["home"] for r in base} | {r["away"] for r in base}
    finals = con.execute("SELECT espn_game_id, game_date, away_team, home_team, away_score, home_score, source_file "
                         "FROM official_game_results WHERE sport = 'NBA' AND game_date > ? AND game_date <= ? "
                         "AND source_file LIKE 'espn:%' ORDER BY game_date, espn_game_id", (last, through)).fetchall()
    rows, unknown, dupes = [], set(), []
    for gid, day, away, home, a_s, h_s, src in finals:
        key = f"{day}|{away}|{home}"
        if key in keys:
            dupes.append(key)
            continue
        unknown |= {t for t in (away, home) if t not in known}
        rows.append({"game_key": key, "date": day, "season": _nba_season(day), "away": away, "home": home,
                     "away_score": str(a_s), "home_score": str(h_s), "source": f"ESPN_SCOREBOARD:{src[5:]}",
                     "original_game_id": f"ESPN-{gid}", "holdout_flag": "False", "market_model_eligible": "False"})
    return {"base_last_date": last, "rows": rows, "unknown_teams": sorted(unknown), "duplicates": dupes}


def write_nba_history(base_history: Path, rows: Sequence[dict], dest: Path) -> str:
    """Write base history + new rows to a NEW file (never overwrite); return its SHA-256."""
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"{dest} exists; history outputs are immutable")
    data = Path(base_history).read_bytes()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=NBA_HISTORY_COLUMNS, lineterminator="\n")
    w.writerows(rows)
    sep = b"" if data.endswith(b"\n") else b"\n"
    out = data + sep + buf.getvalue().encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    return hashlib.sha256(out).hexdigest()


__all__ = ["Capture", "LEAGUES", "Observation", "ResultsError", "collect", "fetch", "nba_history_rows", "parse",
           "record", "scoreboard_url", "write_nba_history"]
