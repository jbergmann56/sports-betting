"""NBA: replay recorded R4 batches through the frozen scorer and compare.

For each recorded R4 row (scorer labels ``NBA_PREVIOUS_PRODUCTION_R4_20261030``,
``NBA_PREVIOUS_PRODUCTION_R4``, ``PREVIOUS_DEPLOYED_SCORER_RESTORED_R4``) the recorded
``source_row_json`` is the scorer's own forecasts row. Per batch and slate date:

1. The scorer's 12-field quote JSON is rebuilt from that batch's ``market_quotes`` + ``events``
   (games on that Central-time date with a complete six-side pregame board). Older ``NBA_*_R4_R3``
   captures store team names as sides and status ``OPEN``; these are mapped to Away/Home, and
   ``OPEN`` counts as pregame only when the capture precedes the start.
2. The history is the frozen R4 history (``nba_history_through_2026-11-11.csv``) cut to games
   dated before the slate: what was knowable then, given the accepted manual finals (PR #4
   decision 5).
3. The unchanged ``nba.py score`` runs; each recorded row is matched on (Game, Market).

Where the frozen history does not reproduce a batch, ``reconcile_all`` tries the documented
``HISTORY_VARIANTS`` (each a named explanation, applied to a copy) and, failing those, reports the
decision fields alone.

Compared: Tier, Selection, Odds, Model_P, EV, and the structural intermediates
(Model_Home_Margin, Predicted_Total, Structural_Home_Win_P), which test the features and
history, not only the final probability. Numbers use the golden rule |Δ| ≤ 1e-9.
Needs the model environment.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gambling.models.nba.r4_legacy import FIXTURE, run_frozen_scorer

R4_LABELS = ("NBA_PREVIOUS_PRODUCTION_R4_20261030", "NBA_PREVIOUS_PRODUCTION_R4",
             "PREVIOUS_DEPLOYED_SCORER_RESTORED_R4")
HISTORY = FIXTURE / "inputs" / "nba_history_through_2026-11-11.csv"
NUMERIC = ("Odds", "Model_P", "EV", "Model_Home_Margin", "Predicted_Total", "Structural_Home_Win_P")
TEXT = ("Tier", "Selection")
TOL = 1e-9
CENTRAL = ZoneInfo("America/Chicago")


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _num(v):
    return None if v in (None, "") else float(v)


def quotes_for(con: sqlite3.Connection, batch_id: str, slate: str) -> list[list]:
    rows = con.execute(
        "SELECT q.event_id, e.away, e.home, e.start_utc, q.market, q.side, q.line, q.odds_american, q.quote_status, "
        "q.quote_captured_utc FROM market_quotes q JOIN events e ON e.batch_id = q.batch_id AND e.sport = q.sport "
        "AND e.event_id = q.event_id WHERE q.batch_id = ? AND q.sport = 'NBA'", (batch_id,)).fetchall()
    games: dict = defaultdict(dict)
    meta = {}
    for eid, away, home, start, market, side, line, odds, status, captured in rows:
        # Older captures store team names as sides and status OPEN; map to Away/Home and count OPEN as
        # pregame only if captured before the start.
        side = {away: "Away", home: "Home"}.get(side, side)
        if status == "OPEN":
            status = "OFFERED_PREGAME" if _utc(captured) < _utc(start) else "OPEN_AFTER_START"
        games[eid][(market, side)] = (line, odds, status)
        meta[eid] = (away, home, start)
    out = []
    for eid, g in games.items():
        away, home, start = meta[eid]
        day = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(CENTRAL).date().isoformat()
        if day != slate or len(g) != 6 or any(v[2] != "OFFERED_PREGAME" for v in g.values()):
            continue
        out.append([day, f"{away} @ {home}", away, home, float(g["Spread", "Away"][0]), float(g["Spread", "Away"][1]),
                    float(g["Spread", "Home"][1]), float(g["Moneyline", "Away"][1]), float(g["Moneyline", "Home"][1]),
                    float(g["Total", "Over"][0]), float(g["Total", "Over"][1]), float(g["Total", "Under"][1])])
    return sorted(out, key=lambda q: q[1])


def _pelicans_clippers_as_la(r: dict) -> dict:
    if r["date"] == "2026-11-08" and r["away"] == "New Orleans Pelicans" and r["home"] == "Los Angeles Clippers":
        r = dict(r, home="LA Clippers")
        r["game_key"] = f"{r['date']}|{r['away']}|{r['home']}"
    return r


# Named, documented explanations found by reconciliation (2026-11-25). Each changes only a copy of the
# history for the replay; the frozen file is never edited.
HISTORY_VARIANTS = {
    # The Nov 7 late preview (05:59Z) ran before the Nov 6 finals were entered.
    "BEFORE_PREVIOUS_DAY_FINALS": dict(cutoff_days=1, edit=None),
    # Runs on Nov 9-11 had the Nov 8 Pelicans @ Clippers final as "LA Clippers"; the frozen history file
    # (Nov 11 manual-finals script) records "Los Angeles Clippers".
    "NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS": dict(cutoff_days=0, edit=_pelicans_clippers_as_la),
}


def history_before(slate: str, dest: Path, variant: str | None = None) -> Path:
    spec = HISTORY_VARIANTS[variant] if variant else dict(cutoff_days=0, edit=None)
    cutoff = (datetime.fromisoformat(slate) - timedelta(days=spec["cutoff_days"])).date().isoformat()
    with open(HISTORY, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [(spec["edit"] or (lambda r: r))(r) for r in reader if r["date"] < cutoff]
        fields = reader.fieldnames
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return dest


def reconcile_batch(con: sqlite3.Connection, batch_id: str, variant: str | None = None,
                    intermediates: bool = True) -> list[dict]:
    """Compare recorded R4 rows with a replay. ``variant`` names a documented history explanation;
    ``intermediates=False`` compares only the decision fields (Tier, Selection, Odds, Model_P, EV)."""
    recorded = [json.loads(r[0]) | {"_score_id": r[1], "_label": r[2]} for r in con.execute(
        "SELECT source_row_json, score_id, model_version FROM model_scores WHERE batch_id = ? AND sport = 'NBA' "
        f"AND model_version IN ({','.join('?' * len(R4_LABELS))})", (batch_id, *R4_LABELS))]
    reports = []
    for slate in sorted({r["Date"] for r in recorded}):
        rec = [r for r in recorded if r["Date"] == slate]
        q = quotes_for(con, batch_id, slate)
        report = {"batch_id": batch_id, "slate": slate, "recorded_rows": len(rec), "games_rebuilt": len(q),
                  "history_variant": variant or "FROZEN", "compared": "all" if intermediates else "decisions"}
        with tempfile.TemporaryDirectory() as d:
            qp = Path(d) / "quotes.json"
            qp.write_text(json.dumps(q, indent=2))
            try:
                fresh = run_frozen_scorer(qp, history_before(slate, Path(d) / "history.csv", variant), Path(d) / "work")
            except RuntimeError as exc:
                reports.append(report | {"status": "SCORER_REFUSED", "error": str(exc).strip().splitlines()[-1]})
                continue
        by_key = {(f["Game"], f["Market"]): f for f in fresh}
        outcome, diffs = Counter(), []
        for r in rec:
            f = by_key.get((r["Game"], r["Market"]))
            if f is None:
                outcome["NOT_REPLAYED"] += 1
                diffs.append({"game": r["Game"], "market": r["Market"], "status": "NOT_REPLAYED"})
                continue
            bad = [k for k in TEXT if str(r.get(k)) != str(f.get(k))]
            for k in (NUMERIC if intermediates else NUMERIC[:3]):
                a, b = _num(r.get(k)), _num(f.get(k))
                if (a is None) != (b is None) or (a is not None and abs(a - b) > TOL):
                    bad.append(k)
            outcome["MATCH" if not bad else "DIFFERS"] += 1
            if bad:
                diffs.append({"game": r["Game"], "market": r["Market"], "fields": bad,
                              "recorded": {k: r.get(k) for k in bad}, "replay": {k: f.get(k) for k in bad}})
        reports.append(report | {"status": "COMPARED", "outcomes": dict(outcome), "differences": diffs})
    return reports


def reconcile_all(con: sqlite3.Connection) -> list[dict]:
    """Every R4 batch: as frozen first; where that differs, each documented variant; then decisions only."""
    batches = [r[0] for r in con.execute(
        f"SELECT DISTINCT batch_id FROM model_scores WHERE sport = 'NBA' AND model_version IN "
        f"({','.join('?' * len(R4_LABELS))}) ORDER BY batch_id", R4_LABELS)]
    out = []
    for b in batches:
        for rep in reconcile_batch(con, b):
            best = rep
            if rep.get("outcomes", {}).get("DIFFERS") or rep.get("status") != "COMPARED":
                for v in HISTORY_VARIANTS:
                    alt = [r for r in reconcile_batch(con, b, v) if r["slate"] == rep["slate"]][0]
                    if alt.get("status") == "COMPARED" and not alt["outcomes"].get("DIFFERS"):
                        best = alt
                        break
                else:
                    alt = [r for r in reconcile_batch(con, b, "NOV8_PELICANS_CLIPPERS_AS_LA_CLIPPERS", False)
                           if r["slate"] == rep["slate"]][0]
                    best = rep | {"decisions_only": alt}
            out.append(best)
    return out


__all__ = ["reconcile_all", "reconcile_batch"]
