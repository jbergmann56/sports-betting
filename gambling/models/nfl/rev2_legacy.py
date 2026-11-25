"""NFL REV2-CAL champion + W8 full-slope challenger: frozen-scorer adapter.

Wraps the UNCHANGED archived scorer (`NFL_20261110_072712CST/scoring/score.py`
in the frozen ZIP, whose `model/src` files are byte-identical to
`legacy_models/nfl/`) and maps its per-market output to adapter contract v2:
one ``ScoreRow`` per quoted side per release.

Mapping (verified against the archived ``model_scores`` for the Nov 10 batch):

* Champion row: the side named by ``champion_selection`` carries the model's
  recorded tier/signal/action. A calibrated probability exists only for tiers
  A/B+ (``champion_p``); it is a binary win probability, so the row is
  ``SCORED`` (P(push)=0) on half-point lines and ``CONDITIONAL_SCORED`` on
  integer lines (research decision 4). Tiers without a probability are
  ``EVALUATED``. The opposite side is ``NOT_EVALUATED_BY_MODEL``.
* Challenger row: if a segment was selected, the selected side carries
  ``challenger_p`` the same way and the opposite side is not evaluated. If no
  segment was selected the challenger evaluated the market and passed: both
  sides are ``EVALUATED`` with the recorded action.
* Action classes come from the recorded action text, never recomputed:
  ``POSITIVE EV`` -> QUALIFIED; ``SHADOW POSITIVE EV`` -> RESEARCH_POSITIVE_EV;
  every ``PASS...`` -> PASS.
* Adjusted Kelly: not computed by either release; null with the release's own
  recorded reason.

This is a **frozen replay adapter** for archived boards. It is not a live
pipeline: live use additionally needs a current schedule/results snapshot and a
capture-to-``board.json`` converter (backlog B8/B10).
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Mapping, Optional

from gambling.config import PACKAGE_ROOT
from gambling.core.quotes import OPPOSITE, QuoteSide
from gambling.models.base import (
    EVALUATED, NOT_EVALUATED_BY_MODEL, PASS, QUALIFIED, RESEARCH_POSITIVE_EV, ScoreRow,
    binary_probability_row, push_possible,
)

CHAMPION = "NFL_REV2_CAL_20261024"
CHALLENGER = "NFL_W8_FULL_SLOPE_20261026"
RELEASES = (CHAMPION, CHALLENGER)
FROZEN_ZIP = PACKAGE_ROOT / "data" / "GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip"
NOV10_PREFIX = "NFL_20261110_072712CST/"

# Registry-pinned frozen members (gambling/db/migrations/0005_seed_model_registry.sql).
PINNED_MEMBERS = {
    "scoring/score.py": "6fe3e0e4ec92567c72c263a95bbccf30fbac42bfd6d78d33b7e662d4c054d74b",
    "scoring/model/data/champion_config_preserved.json":
        "eba7e74904c17f0695f31afdc8965bf4d7de90b81f74e68def87332a46c05506",
    "scoring/metadata.json": "88e2f6adc9237304c7f29bd88e7d693e4a2b2d7c8b901464ff14a915bd0bd69e",
}

ACTION_CLASS = {"POSITIVE EV": QUALIFIED, "SHADOW POSITIVE EV": RESEARCH_POSITIVE_EV}
MARKETS = {"Spread": ("Away", "Home"), "Moneyline": ("Away", "Home"), "Total": ("Over", "Under")}


def _f(v) -> Optional[float]:
    if v is None or str(v).strip() in ("", "nan", "NaN", "None"):
        return None
    x = float(v)
    return None if math.isnan(x) else x


def _action_class(text: str) -> str:
    if text in ACTION_CLASS:
        return ACTION_CLASS[text]
    if text.startswith("PASS"):
        return PASS
    raise ValueError(f"unmapped NFL action text {text!r}")


def snapshot_quote_sides(quotes_csv_text: str, as_of_utc: str) -> list[QuoteSide]:
    """Convert the wide NFL snapshot ``quotes.csv`` (one row per game) to six QuoteSides per game."""
    out = []
    for r in csv.DictReader(io.StringIO(quotes_csv_text)):
        def side(market, s, sel, line, odds, code, letter):
            price = r.get(f"2W-{code}_{letter}_price_id")
            return QuoteSide("NFL", r["event_id"], r["start_utc"], r["away"], r["home"], market, s, sel,
                             line, _f(odds), f"BOVADA:{price}" if price else f"BOVADA:{r['event_id']}:{market}:{s}",
                             as_of_utc, "OFFERED_PREGAME", "Bovada", r.get("source_url", ""))
        out += [side("Moneyline", "Away", r["away"], None, r["away_moneyline"], "12", "A"),
                side("Moneyline", "Home", r["home"], None, r["home_moneyline"], "12", "H"),
                side("Spread", "Away", r["away"], _f(r["away_spread"]), r["away_spread_odds"], "HCAP", "A"),
                side("Spread", "Home", r["home"], _f(r["home_spread"]), r["home_spread_odds"], "HCAP", "H"),
                side("Total", "Over", "Over", _f(r["total"]), r["over_odds"], "OU", "O"),
                side("Total", "Under", "Under", _f(r["total"]), r["under_odds"], "OU", "U")]
    return out


def _side_for(selection: str, q_by_side: Mapping[str, QuoteSide]) -> str:
    for s, q in q_by_side.items():
        if q.selection == selection:
            return s
    raise ValueError(f"selection {selection!r} not on board {sorted(q.selection for q in q_by_side.values())}")


def _check_price(q: QuoteSide, line: Optional[float], odds: Optional[float], who: str) -> None:
    if (q.line is None) != (line is None) or (line is not None and abs(q.line - line) > 1e-9):
        raise ValueError(f"{who}: line {line} != quoted {q.line} for {q.event_id} {q.market} {q.side}")
    if odds is None or q.american_odds is None or abs(q.american_odds - odds) > 1e-9:
        raise ValueError(f"{who}: odds {odds} != quoted {q.american_odds} for {q.event_id} {q.market} {q.side}")


def adapt_dual_sheet(rows: Iterable[Mapping], quotes: Iterable[QuoteSide], score_as_of_utc: Optional[str],
                     adjusted_reason: str) -> list[ScoreRow]:
    """Map the frozen ``dual_model_bet_sheet.csv`` rows to ScoreRows for every quoted side."""
    by_game: dict[tuple[str, str], dict[str, dict[str, QuoteSide]]] = {}
    for q in quotes:
        by_game.setdefault((q.away, q.home), {}).setdefault(q.market, {})[q.side] = q
    ak_reason = f"RELEASE_REPORTS_UNAVAILABLE: {adjusted_reason}"
    out: list[ScoreRow] = []
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        market = r["market"]
        sides = by_game[(r["away"], r["home"])][market]
        for release, prefix, role in ((CHAMPION, "champion", "CHAMPION"), (CHALLENGER, "challenger", "CHALLENGER")):
            seen.add((release, r["away"] + "@" + r["home"], market))
            action = r[f"{prefix}_action"]
            selection = r.get(f"{prefix}_selection") or ""
            tier = r["champion_tier"] if prefix == "champion" else (r.get("challenger_rule") or None)
            signal = r["champion_signal"] if prefix == "champion" else (r.get("challenger_rule") or None)
            common = dict(recorded_role=role, model_action=action, score_as_of_utc=score_as_of_utc,
                          adjusted_kelly_null_reason=ak_reason)
            if not selection:
                for s in MARKETS[market]:
                    out.append(ScoreRow(release, sides[s].quote_id, EVALUATED, original_tier=tier,
                                        model_signal=signal, action_class=_action_class(action),
                                        reason="MODEL_EVALUATED_MARKET_NO_SELECTION", **common))
                continue
            s_sel = _side_for(selection, sides)
            q = sides[s_sel]
            _check_price(q, _f(r[f"{prefix}_line"]), _f(r[f"{prefix}_odds"]), f"{release}")
            p = _f(r[f"{prefix}_p"])
            legacy = dict(legacy_ev=_f(r[f"{prefix}_ev"]), legacy_full_kelly=_f(r[f"{prefix}_full_kelly"]))
            if p is not None:
                out.append(binary_probability_row(release_id=release, quote_id=q.quote_id, p_win=p,
                                                  push_possible=push_possible(market, q.line), original_tier=tier,
                                                  model_signal=signal, action_class=_action_class(action),
                                                  **legacy, **common))
            else:
                out.append(ScoreRow(release, q.quote_id, EVALUATED, original_tier=tier, model_signal=signal,
                                    action_class=_action_class(action), reason="NO_CALIBRATED_PROBABILITY_FOR_TIER",
                                    **legacy, **common))
            opp = sides[OPPOSITE[s_sel]]
            out.append(ScoreRow(release, opp.quote_id, NOT_EVALUATED_BY_MODEL,
                                reason="MODEL_SELECTED_OPPOSITE_SIDE", recorded_role=role,
                                score_as_of_utc=score_as_of_utc))
    expected = {(rel, f"{q.away}@{q.home}", q.market) for q in quotes for rel in RELEASES}
    missing = expected - seen
    if missing:
        raise ValueError(f"frozen output lacks markets {sorted(missing)[:3]}")
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_frozen_board(zip_path: Path = FROZEN_ZIP, prefix: str = NOV10_PREFIX) -> dict:
    """Read the archived board: quotes, as-of time, scorer output and metadata (no execution)."""
    import json
    with zipfile.ZipFile(zip_path) as z:
        for member, digest in PINNED_MEMBERS.items():
            if _sha(z.read(prefix + member)) != digest:
                raise ValueError(f"frozen member hash mismatch: {member}")
        quotes_text = z.read(prefix + "snapshot/quotes.csv").decode("utf-8")
        feed = json.loads(z.read(prefix + "snapshot/feed_metadata.json"))
        meta = json.loads(z.read(prefix + "scoring/metadata.json"))
        sheet = list(csv.DictReader(io.StringIO(z.read(prefix + "scoring/dual_model_bet_sheet.csv").decode("utf-8"))))
    return dict(quotes=snapshot_quote_sides(quotes_text, feed["retrieved_at_utc"]), feed=feed, metadata=meta,
                sheet=sheet)


def run_frozen_scorer(workdir: Path, zip_path: Path = FROZEN_ZIP, prefix: str = NOV10_PREFIX) -> list[dict]:
    """Execute the unchanged archived scorer in ``workdir`` and return its fresh output rows.

    Requires the model environment (pandas/numpy/scipy; ``requirements-models.txt``).
    """
    workdir = Path(workdir)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.startswith(prefix):
                z.extract(name, workdir)
    scoring = workdir / prefix / "scoring"
    for member, digest in PINNED_MEMBERS.items():
        if _sha((workdir / prefix / member).read_bytes()) != digest:
            raise ValueError(f"frozen member hash mismatch after extraction: {member}")
    (scoring / "dual_model_bet_sheet.csv").unlink()  # prove the output is regenerated, not reused
    done = subprocess.run([sys.executable, "-B", "score.py"], cwd=scoring, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-2000:])
    with open(scoring / "dual_model_bet_sheet.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score_frozen_board(zip_path: Path = FROZEN_ZIP, prefix: str = NOV10_PREFIX,
                       rerun: bool = False, workdir: Optional[Path] = None) -> tuple[list[QuoteSide], list[ScoreRow]]:
    """Quotes + ScoreRows for an archived NFL board (optionally re-executing the frozen scorer)."""
    board = load_frozen_board(zip_path, prefix)
    sheet = board["sheet"]
    if rerun:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sheet = run_frozen_scorer(Path(workdir or tmp), zip_path, prefix)
    rows = adapt_dual_sheet(sheet, board["quotes"], None, board["metadata"].get("adjusted_reason") or "not recorded")
    return board["quotes"], rows


__all__ = ["CHAMPION", "CHALLENGER", "RELEASES", "adapt_dual_sheet", "load_frozen_board", "run_frozen_scorer",
           "score_frozen_board", "snapshot_quote_sides"]
