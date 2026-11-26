"""NCAAFB Week 8+ configuration (Nov 2 board): frozen-scorer adapter.

Runs the UNCHANGED archived scorers (``legacy_models/ncaafb/build_features.py`` and
``score_both.py``, authority ``authority.json``) and maps the one-row-per-game-market output
``ALL_62_GAMES_BOTH_MODEL_TIERS.csv`` to adapter contract v2.

Releases (registry migration 0005):

==========  ======================================  ==================================  =============
Market      Release                                 Scorer columns                      Wagering
==========  ======================================  ==================================  =============
Spread      NCAAFB_SPREAD_PP_V2_20261028 (champion)  Champion*                           authorized
Spread      NCAAFB_SPREAD_CONTINUOUS_V1_20261023     Challenger*                         not authorized
Moneyline   NCAAFB_ML_W8PLUS_RULE (shared)           Champion* = Challenger* (asserted)  authorized
Total       NCAAFB_OU_RESEARCH (shared, research)    Champion* = Challenger* (asserted)  not authorized
==========  ======================================  ==================================  =============

Mapping (verified against golden fixture ``NCAAFB_20261102``):

* **Spread.** The rule evaluates only the higher-slope team's side.
  - That side carries the recorded probability when it is eligible (underdog and |Z| ≥ 1.243).
  - Otherwise that side is ``EVALUATED``/Pass with the recorded reason.
  - The other side is ``NOT_EVALUATED_BY_MODEL``.
  - The probability is P(win | decisive) (authority: "Conditional decisive settlements"). On
    half-point lines it is therefore unconditional with P(push)=0; on integer lines it is
    ``CONDITIONAL_SCORED`` with the push UNKNOWN (PR #4 decision 4).
* **Moneyline.** The rule evaluates only the underdog.
  - Outside the dog +250..400 / total 45..55 regime → ``EVALUATED``/Pass.
  - Favorite's published SRS not recovered → ``UNSCORED``; the scorer's hypothetical
    probability stays in diagnostics only.
  - Otherwise ``SCORED``: "A existing" when the published SRS is < 10, or "B descriptive"
    (descriptive only, Kelly 0) when it is ≥ 10.
* **Total.** The PFPA rule looks only at the Under.
  - The Under carries the research probability 54/99 when PFPA − total ≤ −5 (``Lean``), and is
    ``EVALUATED``/Pass otherwise.
  - The Over is ``NOT_EVALUATED_BY_MODEL``.
  - The release's Adjusted Kelly of 0 ("zero normal allocation") passes through as recorded.
* **Action classes** come from the recorded tier, never recomputed:
  - B+/B provisional and A existing → ``QUALIFIED``;
  - Lean → ``LEAN``;
  - Pass, B descriptive → ``PASS``.
  Wager eligibility then comes from the registry at quote time (only the champion spread and
  the ML rule are authorized). A challenger row stays ``QUALIFIED_NOT_WAGER_AUTHORIZED``.
* **Adjusted Kelly** (spread/ML): not in the per-row output. The authority's joint
  expected-log optimizer was not run for this board ("Joint sizing not run; current exposure
  not reconciled"), so it is null with that reason.

This is a frozen-replay adapter for the archived Nov 2 inputs. A new week needs new
pregame features, a posterior/quadrature refresh decision, published SRS gate values and
results ingestion (``docs/sports/ncaafb.md``).
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
from pathlib import Path
from typing import Iterable, Mapping, Optional

from gambling.config import PACKAGE_ROOT
from gambling.core.bovada import quotes_from_bovada as _bovada
from gambling.core.quotes import OPPOSITE, QuoteSide
from gambling.models.base import (
    AK_RELEASE_METHOD, EVALUATED, LEAN, NOT_EVALUATED_BY_MODEL, PASS, QUALIFIED, UNSCORED, ScoreRow,
    binary_probability_row, push_possible,
)

SPREAD_CHAMPION = "NCAAFB_SPREAD_PP_V2_20261028"
SPREAD_CHALLENGER = "NCAAFB_SPREAD_CONTINUOUS_V1_20261023"
ML_RULE = "NCAAFB_ML_W8PLUS_RULE"
OU_RESEARCH = "NCAAFB_OU_RESEARCH"
MARKET_RELEASES = {
    "Spread": (SPREAD_CHAMPION, SPREAD_CHALLENGER),
    "Moneyline": (ML_RULE,),
    "Total": (OU_RESEARCH,),
}
RELEASES = (SPREAD_CHAMPION, SPREAD_CHALLENGER, ML_RULE, OU_RESEARCH)

FIXTURE = PACKAGE_ROOT / "tests" / "golden" / "fixtures" / "NCAAFB_20261102"
LEGACY = PACKAGE_ROOT / "legacy_models" / "ncaafb"
SCORER_SHA = {
    "build_features.py": "d729d72f3778c76381414153c3c6540ca08e19681ca41178ea1d8905994228a0",
    "score_both.py": "e9fde3457c18085d830ab637c81f8f0458d4ffaf248d8775fa7884736fa81400",
    "authority.json": "9e5e0678171b31fc595a72d8396aa5437259545b1ba044fb0446dddf36fb96bb",
}
OUTPUT = "ALL_62_GAMES_BOTH_MODEL_TIERS.csv"

TIER_ACTION = {"B+ provisional": QUALIFIED, "B provisional": QUALIFIED, "A existing": QUALIFIED,
               "Lean": LEAN, "Pass": PASS, "B descriptive": PASS}
SIZING_REASON = "RELEASE_REPORTS_UNAVAILABLE: Joint sizing not run; current exposure not reconciled"
OU_AK_METHOD = "ZERO_NORMAL_ALLOCATION (authority.json OU: 'Research Lean remains visible; zero allocation')"


def _f(v) -> Optional[float]:
    if v is None or str(v).strip() in ("", "nan", "NaN", "None"):
        return None
    x = float(v)
    return None if math.isnan(x) else x


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _american(v: str) -> float:
    return 100.0 if str(v).upper() == "EVEN" else float(v)


# ---------------------------------------------------------------------- quotes
def quotes_from_bovada(raw: list, captured_utc: str, source: str = "") -> list[QuoteSide]:
    """Six QuoteSides per event from the archived Bovada coupon response (main game-line markets)."""
    return _bovada(raw, captured_utc, "NCAAFB", source)


def check_against_quoted_lines(quotes: Iterable[QuoteSide], quoted_lines: Iterable[Mapping]) -> None:
    """Every price the scorer read (quoted_lines.csv) must equal the raw Bovada outcome."""
    q = {(x.event_id, x.market, x.side): x for x in quotes}
    cols = {("Spread", "Away"): ("AwaySpread", "AwaySpreadOdds"), ("Spread", "Home"): ("HomeSpread", "HomeSpreadOdds"),
            ("Moneyline", "Away"): (None, "AwayML"), ("Moneyline", "Home"): (None, "HomeML"),
            ("Total", "Over"): ("Total", "OverOdds"), ("Total", "Under"): ("Total", "UnderOdds")}
    for r in quoted_lines:
        for (market, side), (lc, oc) in cols.items():
            x = q[(str(r["EventID"]), market, side)]
            line = _f(r[lc]) if lc else None
            if (x.line is None) != (line is None) or (line is not None and abs(x.line - line) > 1e-9) \
                    or abs(x.american_odds - _american(r[oc])) > 1e-9:
                raise ValueError(f"quoted_lines {r['EventID']} {market} {side} != raw Bovada outcome")


# ---------------------------------------------------------------------- scorer
def run_frozen_scorer(workdir: Optional[Path] = None, fixture: Path = FIXTURE) -> list[dict]:
    """Execute the unchanged scorers on the archived Nov 2 inputs; return the fresh output rows.

    Needs the model environment (pandas/numpy/scipy; ``requirements-models.txt``).
    """
    for name, digest in SCORER_SHA.items():
        if _sha(LEGACY / name) != digest:
            raise ValueError(f"frozen NCAAFB scorer hash mismatch: {name}")
    manifest = json.loads((fixture / "MANIFEST.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(workdir or tmp)
        shutil.copytree(fixture / "inputs", work / "inputs", dirs_exist_ok=True)
        for entry in manifest["inputs"]:
            if _sha(work / entry["path"]) != entry["sha256"]:
                raise ValueError(f"frozen NCAAFB input hash mismatch: {entry['path']}")
        (work / "results").mkdir(exist_ok=True)
        shutil.move(str(work / "inputs" / "oct27_scoreboard.json"), work / "results" / "oct27_scoreboard.json")
        for name in ("build_features.py", "score_both.py"):
            shutil.copy2(LEGACY / name, work / name)
        for name in ("build_features.py", "score_both.py"):
            done = subprocess.run([sys.executable, "-B", name], cwd=work, capture_output=True, text=True)
            if done.returncode != 0:
                raise RuntimeError(f"{name}: {done.stderr[-2000:]}")
        with open(work / "results" / OUTPUT, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


def load_frozen_board(fixture: Path = FIXTURE) -> dict:
    """Archived inputs and the archived scorer output (no execution)."""
    raw = json.loads((fixture / "inputs" / "raw_bovada_response.json").read_text())
    with open(fixture / "inputs" / "quoted_lines.csv", newline="", encoding="utf-8") as f:
        lines = list(csv.DictReader(f))
    captured = {r["CapturedUTC"] for r in lines}
    if len(captured) != 1:
        raise ValueError(f"quoted_lines carries several capture times {sorted(captured)}")
    quotes = quotes_from_bovada(raw, captured.pop(), "NCAAFB_20261102/inputs/raw_bovada_response.json")
    check_against_quoted_lines(quotes, lines)
    with open(fixture / "expected" / OUTPUT, newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    return dict(quotes=quotes, quoted_lines=lines, sheet=sheet)


# ---------------------------------------------------------------------- mapping
def _side_of(r: Mapping, market: str) -> str:
    if market == "Total":
        return "Under"
    if r["Selection"] == r["Away"]:
        return "Away"
    if r["Selection"] == r["Home"]:
        return "Home"
    raise ValueError(f"selection {r['Selection']!r} is neither {r['Away']!r} nor {r['Home']!r}")


def _check_price(q: QuoteSide, r: Mapping) -> None:
    line, odds = _f(r["Line"]), _f(r["Odds"])
    if q.market != "Moneyline" and (q.line is None or line is None or abs(q.line - line) > 1e-9):
        raise ValueError(f"{q.event_id} {q.market} {q.side}: scored line {line} != quoted {q.line}")
    if odds is not None and abs(q.american_odds - odds) > 1e-9:
        raise ValueError(f"{q.event_id} {q.market} {q.side}: scored odds {odds} != quoted {q.american_odds}")


def adapt(sheet: Iterable[Mapping], quotes: Iterable[QuoteSide]) -> list[ScoreRow]:
    """Map the archived/fresh ``ALL_62_GAMES_BOTH_MODEL_TIERS.csv`` rows to ScoreRows."""
    by_key = {(q.event_id, q.market, q.side): q for q in quotes}
    out: list[ScoreRow] = []
    for r in sheet:
        market = {"ML": "Moneyline"}.get(r["Market"], r["Market"])
        configs = (((SPREAD_CHAMPION, "Champion", "CHAMPION"), (SPREAD_CHALLENGER, "Challenger", "CHALLENGER"))
                   if market == "Spread" else
                   (((ML_RULE if market == "Moneyline" else OU_RESEARCH), "Champion", "SHARED_COMPONENT"),))
        if market != "Spread":
            for col in ("Tier", "P", "EV", "FullKelly", "AdjustedKelly"):
                if r["Champion" + col] != r["Challenger" + col]:
                    raise ValueError(f"shared {market} component differs between configurations: {col}")
        side = _side_of(r, market) if r["Selection"] else "Under"
        q = by_key[(str(r["EventID"]), market, side)]
        opp = by_key[(str(r["EventID"]), market, OPPOSITE[side])]
        for release, prefix, role in configs:
            tier = r[prefix + "Tier"]
            p = _f(r[prefix + "P"])
            diag = {k: r[k] for k in ("Z", "SignalGroup", "NoVigP", "FavoritePublishedSRS", "SRSSourceURL", "PFPA",
                                      "PFPA_Gap", "ConditionalIfFavoriteSRSBelow10P",
                                      "ConditionalIfFavoriteSRSBelow10EV", "FeatureCutoff", "ProbabilityBasis",
                                      "SizingStatus") if r.get(k) not in (None, "")}
            common = dict(recorded_role=role, original_tier=tier, model_signal=r.get("SignalGroup") or None,
                          model_action=tier, score_as_of_utc=None, diagnostics=diag)
            if tier.startswith("Unscored"):
                out.append(ScoreRow(release, q.quote_id, UNSCORED, reason=f"{tier}: {r['Reason']}", **common))
            elif p is None:
                out.append(ScoreRow(release, q.quote_id, EVALUATED, action_class=TIER_ACTION[tier], reason=r["Reason"],
                                    **common))
            else:
                _check_price(q, r)
                ak = _f(r[prefix + "AdjustedKelly"])
                kelly = (dict(adjusted_kelly=ak, adjusted_kelly_method=OU_AK_METHOD,
                              adjusted_kelly_certification=AK_RELEASE_METHOD) if ak is not None
                         else dict(adjusted_kelly_null_reason=SIZING_REASON))
                out.append(binary_probability_row(
                    release_id=release, quote_id=q.quote_id, p_win=p, push_possible=push_possible(market, q.line),
                    action_class=TIER_ACTION[tier], legacy_ev=_f(r[prefix + "EV"]),
                    legacy_full_kelly=_f(r[prefix + "FullKelly"]), reason=r["Reason"], **kelly, **common))
            out.append(ScoreRow(release, opp.quote_id, NOT_EVALUATED_BY_MODEL, recorded_role=role,
                                reason=("RULE_EVALUATES_UNDER_ONLY" if market == "Total" else
                                        "RULE_EVALUATES_HIGHER_SLOPE_SIDE_ONLY" if market == "Spread" else
                                        "RULE_EVALUATES_UNDERDOG_ONLY")))
    expected = {(rel, q.quote_id) for q in by_key.values() for rel in MARKET_RELEASES[q.market]}
    produced = {(s.release_id, s.quote_id) for s in out}
    if expected != produced:
        raise ValueError(f"NCAAFB adapter coverage mismatch: missing {sorted(expected - produced)[:3]}, "
                         f"extra {sorted(produced - expected)[:3]}")
    return out


def score_frozen_board(rerun: bool = False, workdir: Optional[Path] = None) -> tuple[list[QuoteSide], list[ScoreRow]]:
    """Quotes + ScoreRows for the archived Nov 2 board (optionally re-executing the frozen scorers)."""
    board = load_frozen_board()
    sheet = run_frozen_scorer(workdir) if rerun else board["sheet"]
    return board["quotes"], adapt(sheet, board["quotes"])


__all__ = ["MARKET_RELEASES", "RELEASES", "adapt", "load_frozen_board", "quotes_from_bovada", "run_frozen_scorer",
           "score_frozen_board"]
