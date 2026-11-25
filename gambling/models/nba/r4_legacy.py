"""NBA R4 (V27 structural, restored previous production): frozen-scorer adapter.

Runs the UNCHANGED archived scorer ``legacy_models/nba_r4/nba.py score`` (which hash-checks its
own release files via ``RELEASE_HASHES.json``) and maps ``forecasts.csv`` to adapter contract v2.

Releases (registry migration 0005):

* ``NBA_R4_V27_20261030``: CHAMPION, wager-authorized in all three markets
  (``ACTIVE_RELEASE.json``: ``normal_wager: true``). Scorer label ``NBA_PREVIOUS_PRODUCTION_R4_20261030``.
* ``NBA_R3_20261029``: CHALLENGER, ``ARTIFACTS_MISSING``. Every quote gets an explicit ``BLOCKED``
  row, so the champion/challenger view shows the gap instead of hiding it.

Mapping (verified against golden fixture ``NBA_R4_20261112``, 12/12 rows):

* **Sides.** The scorer evaluates one side per market. The other side is ``NOT_EVALUATED_BY_MODEL``.
  - Spread: the side favored by the model-vs-market home-margin gap.
  - Moneyline: the side with the larger structural-minus-no-vig residual.
  - Total: the Under only.
* **Probabilities.** ``Model_P`` exists only for qualifying tiers.
  - Spread B and OU B: Jeffreys Beta posterior means on wins/losses, i.e. P(win | decisive). Half-point
    lines are therefore unconditional with P(push)=0; integer lines are ``CONDITIONAL_SCORED``
    with push UNKNOWN (PR #4 decision 4). The scorer's own sizing treats integer spreads with
    a separate push rate.
  - ML B+: logistic(logit(no-vig) + 0.359). Two-way NBA moneyline, so no push.
  - Rows without a probability are ``EVALUATED`` with the recorded tier and reason.
* **Action classes**, from the recorded tier and sizing status:
  - B or B+ with ``QUALIFIED_POSITIVE_EV`` → QUALIFIED;
  - B or B+ with ``NO_POSITIVE_EV`` → PASS;
  - Lean → LEAN (``normal_wager: false``);
  - Pass → PASS.
* **Adjusted Kelly.** The scorer's joint posterior-predictive expected-log portfolio stake
  (``portfolio_kelly.py``) passes through unchanged. Method:
  ``JOINT_POSTERIOR_PREDICTIVE_EXPECTED_LOG`` with the conditional dependence model. Certification:
  ``LEGACY_NOT_PORTFOLIO_CERTIFIED``, because ``DEPENDENCE_MODEL.json`` is "SHADOW_ADJUSTED_KELLY;
  conditional scenario model, not validated joint calibration". When the scorer reports the portfolio
  as unavailable, the value is null with its reason.

Quotes. ``quotes_json_from_capture`` rebuilds the scorer's 12-field quote JSON from a capture
``quotes.csv`` with the same rules as the archived ``build_nba_daily_features.py``. On Nov 12 it
reproduces the archived JSON byte-for-byte, so each ``quote_id`` (Bovada price id) is tied to the
exact price that was scored. The scorer still labels quotes ``USER_BOVADA_UNTIMESTAMPED``, but the
capture carries timestamps; the sheet uses the capture's.

History. The scorer refuses history that is more than 7 days stale. The Nov 6–11 finals were
transcribed manually and are accepted as frozen replay input only (PR #4 decision 5). Live use
needs an automated results source (``docs/sports/nba.md``).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from gambling.config import PACKAGE_ROOT
from gambling.core.quotes import OPPOSITE, QuoteSide, from_capture_csv
from gambling.models.base import (
    AK_LEGACY_NOT_CERTIFIED, BLOCKED, EVALUATED, LEAN, NOT_EVALUATED_BY_MODEL, PASS, QUALIFIED, ScoreRow,
    binary_probability_row, push_possible,
)

CHAMPION = "NBA_R4_V27_20261030"
CHALLENGER = "NBA_R3_20261029"
RELEASES = (CHAMPION, CHALLENGER)
SCORER_LABEL = "NBA_PREVIOUS_PRODUCTION_R4_20261030"
LEGACY = PACKAGE_ROOT / "legacy_models" / "nba_r4"
FIXTURE = PACKAGE_ROOT / "tests" / "golden" / "fixtures" / "NBA_R4_20261112"
# The Nov 12 capture (batch 20261112T134056Z_68f7ec) is stored once, in the NHL fixture.
CAPTURE_20261112 = PACKAGE_ROOT / "tests" / "golden" / "fixtures" / "NHL_DAY0_20261112" / "inputs" / "20261112_quotes.csv"
CAPTURE_20261112_SHA = "e26bb3286884d680b8b66880313e7c48fe02b5dd05cca77744ebc687a578381d"
QUOTES_JSON_SHA = "9dc344953e4f066e9767ca26a924b2e1160b02f8d2f7cdda55a38e955eb596ee"
HISTORY_SHA = "29fb33308a2c51b8f4c951cae8a504bcc9c57c3aae895c20955463ea9e0561f3"
R3_BLOCK_REASON = ("ARTIFACTS_MISSING: NBA_R3_20261029 model not bundled (registry artifact_status); "
                   "superseded operationally by R4 on 2026-10-30")
AK_METHOD = "JOINT_POSTERIOR_PREDICTIVE_EXPECTED_LOG (portfolio_kelly.py; DEPENDENCE_MODEL.json conditional scenarios)"


def _f(v) -> Optional[float]:
    if v is None or str(v).strip() in ("", "nan", "NaN", "None"):
        return None
    x = float(v)
    return None if math.isnan(x) else x


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------- quotes
def quotes_json_from_capture(quotes_csv: Path, date: str) -> str:
    """The scorer's quote JSON, built with the rules of the archived ``build_nba_daily_features.py``.

    Only complete six-side OFFERED_PREGAME boards whose Central-time start date is ``date``;
    a quote captured at or after the start is an error.
    """
    with open(quotes_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    grp: dict[str, dict] = {}
    for r in rows:
        if r["sport"] == "NBA":
            grp.setdefault(r["event_id"], {})[r["market"], r["side"]] = r
    out = []
    for gg in grp.values():
        if len(gg) != 6 or any(x["quote_status"] != "OFFERED_PREGAME" for x in gg.values()):
            continue
        away, home = gg["Moneyline", "Away"]["description"].split(" @ ")
        day = datetime.fromisoformat(gg["Moneyline", "Away"]["start_utc"].replace("Z", "+00:00")) \
            .astimezone(ZoneInfo("America/Chicago")).date().isoformat()
        if day != date:
            continue
        if any(x["snapshot_as_of_utc"] >= x["start_utc"] for x in gg.values()):
            raise RuntimeError("Quote not pregame")
        get = lambda m, s, k: float(gg[m, s][k])  # noqa: E731
        out.append([day, away + " @ " + home, away, home, get("Spread", "Away", "line"),
                    get("Spread", "Away", "odds_american"), get("Spread", "Home", "odds_american"),
                    get("Moneyline", "Away", "odds_american"), get("Moneyline", "Home", "odds_american"),
                    get("Total", "Over", "line"), get("Total", "Over", "odds_american"),
                    get("Total", "Under", "odds_american")])
    return json.dumps(out, indent=2)


# ---------------------------------------------------------------------- scorer
def run_frozen_scorer(quotes_json: Path, history: Path, workdir: Optional[Path] = None) -> list[dict]:
    """Execute ``nba.py score`` unchanged (it verifies its own release hashes); return forecasts rows.

    Needs the model environment (pandas/numpy/scipy; ``requirements-models.txt``).
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(workdir or tmp)
        shutil.copytree(LEGACY, work / "nba_r4", dirs_exist_ok=True)
        out = work / "out"
        done = subprocess.run([sys.executable, "-B", str(work / "nba_r4" / "nba.py"), "score", "--quotes",
                               str(Path(quotes_json).resolve()), "--history", str(Path(history).resolve()),
                               "--out", str(out)], cwd=work, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(done.stderr[-2000:])
        with open(out / "forecasts.csv", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def load_frozen_board(capture: Path = CAPTURE_20261112, fixture: Path = FIXTURE, date: str = "2026-11-12") -> dict:
    """Archived Nov 12 board: capture quotes (IDs), the scorer's JSON (rebuilt and checked), archived output."""
    if _sha(capture) != CAPTURE_20261112_SHA:
        raise ValueError("Nov 12 capture hash mismatch")
    rebuilt = quotes_json_from_capture(capture, date)
    archived_json = fixture / "inputs" / f"{date}_nba_quotes.json"
    if rebuilt.encode() != archived_json.read_bytes():
        raise ValueError("quote JSON rebuilt from the capture differs from the archived scorer input")
    with open(fixture / "expected" / "forecasts.csv", newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    return dict(quotes=from_capture_csv(capture, sport="NBA"), quotes_json=archived_json,
                history=fixture / "inputs" / "nba_history_through_2026-11-11.csv", sheet=sheet)


# ---------------------------------------------------------------------- mapping
def _side(r: Mapping) -> tuple[str, Optional[float]]:
    sel, market = r["Selection"], r["Market"]
    if market == "Total":
        if not sel.startswith("Under "):
            raise ValueError(f"R4 totals are Under-only, got {sel!r}")
        return "Under", float(sel.split()[-1])
    if market == "Moneyline":
        team = sel[:-3] if sel.endswith(" ML") else sel
        return ("Away" if team == r["Away"] else "Home" if team == r["Home"] else _bad(sel)), None
    team, line = sel.rsplit(" ", 1)
    return ("Away" if team == r["Away"] else "Home" if team == r["Home"] else _bad(sel)), float(line)


def _bad(sel: str):
    raise ValueError(f"selection {sel!r} matches neither team")


def _action(r: Mapping) -> str:
    tier, sizing = r["Tier"], r["Sizing_Status"]
    if tier in ("B", "B+"):
        return QUALIFIED if sizing == "QUALIFIED_POSITIVE_EV" else PASS
    return LEAN if tier == "Lean" else PASS


def adapt(forecasts: Iterable[Mapping], quotes: Iterable[QuoteSide]) -> list[ScoreRow]:
    """Map ``forecasts.csv`` rows to ScoreRows (R4) plus BLOCKED rows for the missing R3 challenger."""
    quotes = [q for q in quotes if q.sport == "NBA"]
    by_game = {(q.away, q.home, q.market, q.side): q for q in quotes}
    out: list[ScoreRow] = []
    for r in forecasts:
        if r["Release"] != SCORER_LABEL:
            raise ValueError(f"unexpected release label {r['Release']!r}")
        side, line = _side(r)
        q = by_game[(r["Away"], r["Home"], r["Market"], side)]
        if (line is None) != (q.line is None) or (line is not None and abs(q.line - line) > 1e-9) \
                or abs(q.american_odds - float(r["Odds"])) > 1e-9:
            raise ValueError(f"{r['Game']} {r['Market']}: scored {line}/{r['Odds']} but quoted {q.line}/{q.american_odds}")
        diag = {k: r[k] for k in ("Edge_Metric", "Edge_Type", "Model_Home_Margin", "Predicted_Total",
                                  "Structural_Home_Win_P", "Selected_NoVig_ML_P", "Away_B2B", "Home_B2B",
                                  "Posterior_95_Low", "Posterior_95_High", "Posterior_P_Positive_EV", "Validation",
                                  "Quote_Source", "Sizing_Status", "Adjusted_Kelly_Status") if r.get(k) not in (None, "")}
        common = dict(recorded_role="CHAMPION", original_tier=r["Tier"], model_signal=r["Model_Health"],
                      model_action=r["Sizing_Status"], score_as_of_utc=r["Frozen_UTC"] or None, diagnostics=diag)
        p = _f(r["Model_P"])
        if p is None:
            out.append(ScoreRow(CHAMPION, q.quote_id, EVALUATED, action_class=_action(r), reason=r["Reason"], **common))
        else:
            ak = _f(r["Adjusted_Kelly"])
            status = r["Adjusted_Kelly_Status"]
            if status.startswith("UNAVAILABLE") or ak is None:
                kelly = dict(adjusted_kelly_null_reason=f"RELEASE_REPORTS_UNAVAILABLE: {status}")
            else:
                kelly = dict(adjusted_kelly=ak, adjusted_kelly_method=f"{AK_METHOD}; status {status}",
                             adjusted_kelly_certification=AK_LEGACY_NOT_CERTIFIED)
            out.append(binary_probability_row(
                release_id=CHAMPION, quote_id=q.quote_id, p_win=p, push_possible=push_possible(q.market, q.line),
                action_class=_action(r), legacy_ev=_f(r["EV"]), legacy_full_kelly=_f(r["Full_Kelly"]),
                reason=r["Reason"], **kelly, **common))
        opp = by_game[(r["Away"], r["Home"], r["Market"], OPPOSITE[side])]
        out.append(ScoreRow(CHAMPION, opp.quote_id, NOT_EVALUATED_BY_MODEL, recorded_role="CHAMPION",
                            score_as_of_utc=r["Frozen_UTC"] or None,
                            reason={"Total": "RULE_EVALUATES_UNDER_ONLY", "Spread": "RULE_EVALUATES_MARGIN_GAP_SIDE_ONLY",
                                    "Moneyline": "RULE_EVALUATES_RESIDUAL_SIDE_ONLY"}[r["Market"]]))
    scored_games = {(r["Away"], r["Home"]) for r in forecasts}
    for q in quotes:
        out.append(ScoreRow(CHALLENGER, q.quote_id, BLOCKED, reason=R3_BLOCK_REASON, recorded_role="CHALLENGER"))
    covered = {s.quote_id for s in out if s.release_id == CHAMPION}
    for q in quotes:
        if q.quote_id not in covered:
            reason = ("NOT_IN_SCORER_SLATE: board incomplete, not pregame or not on the slate date"
                      if (q.away, q.home) not in scored_games else "NO_SCORER_ROW")
            out.append(ScoreRow(CHAMPION, q.quote_id, "UNSCORED", reason=reason))
    return out


def score_frozen_board(rerun: bool = False, workdir: Optional[Path] = None) -> tuple[list[QuoteSide], list[ScoreRow]]:
    """Quotes + ScoreRows for the archived Nov 12 board (optionally re-executing the frozen scorer)."""
    board = load_frozen_board()
    if rerun:
        if _sha(board["history"]) != HISTORY_SHA or _sha(board["quotes_json"]) != QUOTES_JSON_SHA:
            raise ValueError("frozen NBA replay input hash mismatch")
        sheet = run_frozen_scorer(board["quotes_json"], board["history"], workdir)
    else:
        sheet = board["sheet"]
    return board["quotes"], adapt(sheet, board["quotes"])


__all__ = ["CHALLENGER", "CHAMPION", "RELEASES", "adapt", "load_frozen_board", "quotes_json_from_capture",
           "run_frozen_scorer", "score_frozen_board"]
