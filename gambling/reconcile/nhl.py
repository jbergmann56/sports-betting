"""NHL: replay every recorded capture batch through the frozen Day-0 adapter and compare.

For a batch, ``capture_rows`` rebuilds the capture ``quotes.csv`` the original NHL adapter reads
(sport, event, description, start, market, side, line, price, status, snapshot time) from
``market_quotes`` + ``events``. ``reconcile_batch`` runs ``score_capture`` (unchanged scorer,
frozen controls) and matches each recorded ``model_scores`` row on (event, market, side, model
label).

Outcomes per recorded row:

* ``MATCH``: same probability (|Δ| ≤ 1e-9; both null for unscored challengers), EV within 1e-9.
* ``PROBABILITY_DIFFERS`` / ``EV_DIFFERS``: replay disagrees with what was recorded.
* Spread rows ingested without ``selection_side`` take their side from ``selection_display``
  ("Florida Panthers +1.5" → the away/home team of the event); counted as
  ``basis:SIDE_FROM_SELECTION_DISPLAY``. ``SIDE_UNRESOLVED`` if the team does not match.
* ``NOT_REPLAYED``: the adapter emitted no row (incomplete board in the rebuilt capture).
* ``NOT_REPLAYABLE_LABEL``: the recorded model is not a Day-0 release (e.g. the Nov 6
  ``NHL_V15_FROZEN_MORNING`` and ``NHL_DAY0_APPROX_FROM_ROUNDED_EV`` rows).
"""
from __future__ import annotations

import csv
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gambling.models.nhl.day0_legacy import RELEASE_BY_LABEL, run_frozen_scorer

CAPTURE_COLUMNS = ["sport", "event_id", "description", "start_utc", "market", "side", "line", "odds_american",
                   "quote_status", "snapshot_as_of_utc"]
TOL = 1e-9


def _iso(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return ts
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


def capture_rows(con: sqlite3.Connection, batch_id: str) -> list[dict]:
    rows = con.execute(
        "SELECT q.event_id, e.game, e.away, e.home, e.start_utc, q.market, q.side, q.line, q.odds_american, "
        "q.quote_status, q.quote_captured_utc FROM market_quotes q JOIN events e "
        "ON e.batch_id = q.batch_id AND e.sport = q.sport AND e.event_id = q.event_id "
        "WHERE q.batch_id = ? AND q.sport = 'NHL' ORDER BY q.event_id, q.market, q.side", (batch_id,)).fetchall()
    out = []
    for eid, game, away, home, start, market, side, line, odds, status, captured in rows:
        out.append({"sport": "NHL", "event_id": str(eid), "description": game or f"{away} @ {home}",
                    "start_utc": _iso(start), "market": market, "side": side,
                    "line": "" if line is None else repr(float(line)), "odds_american": repr(float(odds)),
                    "quote_status": status, "snapshot_as_of_utc": _iso(captured)})
    return out


def reconcile_batch(con: sqlite3.Connection, batch_id: str) -> dict:
    caps = capture_rows(con, batch_id)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "quotes.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAPTURE_COLUMNS)
            w.writeheader()
            w.writerows(caps)
        data = run_frozen_scorer(path)
    replay = {(str(o["event_id"]), o["market"], o["side"], o["model_version"]): (o, c)
              for o, c in zip(data["out"], data["contracts"])}
    recorded = con.execute(
        "SELECT s.score_id, s.event_id, s.market, s.selection_side, s.selection_display, s.model_version, "
        "s.model_probability, s.expected_value, s.tier, e.away, e.home FROM model_scores s LEFT JOIN events e "
        "ON e.batch_id = s.batch_id AND e.sport = s.sport AND e.event_id = s.event_id "
        "WHERE s.batch_id = ? AND s.sport = 'NHL'", (batch_id,)).fetchall()
    details, outcome = [], Counter()
    for sid, eid, market, side, display, label, p, ev, tier, away, home in recorded:
        basis = "RECORDED_SIDE"
        if side is None and display and market == "Spread":
            team = display.rsplit(" ", 1)[0]
            side = "Away" if team == away else "Home" if team == home else None
            basis = "SIDE_FROM_SELECTION_DISPLAY"
        key = (str(eid), market, side, label)
        if label not in RELEASE_BY_LABEL:
            status = "NOT_REPLAYABLE_LABEL"
        elif side is None:
            status = "SIDE_UNRESOLVED"
        elif key not in replay:
            status = "NOT_REPLAYED"
        else:
            o, _ = replay[key]
            rp, rev = o["model_p"], o["ev"]
            if (p is None) != (rp is None) or (p is not None and abs(p - rp) > TOL):
                status = "PROBABILITY_DIFFERS"
            elif (ev is None) != (rev is None) or (ev is not None and abs(ev - rev) > TOL):
                status = "EV_DIFFERS"
            else:
                status = "MATCH"
        outcome[status] += 1
        outcome[f"basis:{basis}"] += 1
        if status != "MATCH":
            details.append({"score_id": sid, "event_id": eid, "market": market, "side": side, "display": display,
                            "model": label, "recorded_p": p, "recorded_tier": tier, "status": status,
                            "replay_p": replay[key][0]["model_p"] if key in replay else None})
    return {"batch_id": batch_id, "quotes": len(caps), "recorded_rows": len(recorded),
            "incomplete_events": data["incomplete"], "outcomes": dict(outcome), "details": details}


def reconcile_all(con: sqlite3.Connection) -> list[dict]:
    batches = [r[0] for r in con.execute("SELECT DISTINCT batch_id FROM model_scores WHERE sport = 'NHL' "
                                         "ORDER BY batch_id")]
    return [reconcile_batch(con, b) for b in batches]


__all__ = ["capture_rows", "reconcile_all", "reconcile_batch"]
