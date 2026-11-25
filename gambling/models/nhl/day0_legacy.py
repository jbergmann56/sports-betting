"""NHL Day-0 champions (ML/PL/OU) + V3/PL V1/V15 challengers: frozen-scorer adapter.

Runs the UNCHANGED archived Day-0 scorer (``legacy_models/nhl_day0/day0_production.py``)
through the UNCHANGED original capture adapter (``nhl_score_adapter_ORIGINAL.py``) in an
isolated subprocess, and maps every emitted contract to adapter contract v2: one
``ScoreRow`` per quoted side per release of that market.

Releases (registry migration 0005; authority JSON 2026-10-26):

==========  =============================  =========================  ==============
Market      Champion (scoring authority)   Challenger                 Wagering
==========  =============================  =========================  ==============
Moneyline   NHL_ML_DAY0_V1_20261025        NHL_ML_V3                  not authorized
Spread      NHL_PL_DAY0_V1_20261025        NHL_PL_V1                  not authorized
Total       NHL_OU_DAY0_V1_20261025        NHL_V15_CONDITIONAL_COUNT  not authorized
==========  =============================  =========================  ==============

Mapping, verified against the golden fixture ``NHL_DAY0_20261112`` (132/132 rows):

* The scorer emits a contract for both sides of every market for every release, so no
  side is "not evaluated" and no complement is derived here.
* Probabilities are the scorer's own ``model_p_win / model_p_loss / model_p_push``. These are
  captured from ``score_games``'s return value, because the archived CSV drops ``p_push``.
  - Totals on integer lines carry the Day-0 model's own push probability (``PUSH_MODEL``).
  - Moneyline and ±1.5 puck lines carry the model's P(push)=0 (``ZERO_BY_LINE``).
* ``model_p_win is None`` → ``UNSCORED``, with the scorer's ``research_status`` as the reason. The
  PL V1 and V15 challengers are unscored because their inputs are not bundled.
* Tier and status are the original adapter's: ``Lean``/``RESEARCH_POSITIVE_EV`` for positive-EV
  champion rows, otherwise ``Pass``/``PASS``. No row is QUALIFIED: the authority file sets
  ``wagering_authorized: false`` and ``authorized_stake_usd = 0`` for every release.
* ``NHL ML V3`` re-emits the no-vig market probability (``MARKET_ANCHOR_NO_INDEPENDENT_EDGE``).
  It is recorded as the scorer emitted it, not as an independent model.
* Adjusted Kelly: the scorer emits ``adjusted_kelly=None``. It is null here, with that reason.
* Events whose board is incomplete or not pregame (the original adapter skips them) get
  explicit ``UNSCORED`` rows instead of disappearing.

This is a frozen-replay adapter. Live use additionally needs a current control-file
refresh decision (the controls are frozen through 2025) and ChatGPT-side evaluation
(backlog in ``docs/sports/nhl.md``).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from gambling.config import PACKAGE_ROOT
from gambling.core.quotes import QuoteSide, from_capture_csv
from gambling.models.base import (
    PASS, PUSH_MODEL, PUSH_ZERO_BY_LINE, RESEARCH_POSITIVE_EV, SCORED, UNCONDITIONAL, UNSCORED, ScoreRow,
    push_possible,
)

ML_CHAMPION, ML_CHALLENGER = "NHL_ML_DAY0_V1_20261025", "NHL_ML_V3"
PL_CHAMPION, PL_CHALLENGER = "NHL_PL_DAY0_V1_20261025", "NHL_PL_V1"
OU_CHAMPION, OU_CHALLENGER = "NHL_OU_DAY0_V1_20261025", "NHL_V15_CONDITIONAL_COUNT"
MARKET_RELEASES = {
    "Moneyline": (ML_CHAMPION, ML_CHALLENGER),
    "Spread": (PL_CHAMPION, PL_CHALLENGER),
    "Total": (OU_CHAMPION, OU_CHALLENGER),
}
RELEASES = tuple(r for pair in MARKET_RELEASES.values() for r in pair)

# Scorer model labels -> registered releases (model_release_aliases, migration 0005).
RELEASE_BY_LABEL = {
    "NHL-ML-DAY0-V1-2026-10-25": ML_CHAMPION, "NHL ML V3": ML_CHALLENGER,
    "NHL-PL-DAY0-V1-2026-10-25": PL_CHAMPION, "NHL PL V1": PL_CHALLENGER,
    "NHL-OU-DAY0-V1-2026-10-25": OU_CHAMPION, "NHL V15 Conditional Count": OU_CHALLENGER,
}
STATUS_ACTION = {"RESEARCH_POSITIVE_EV": RESEARCH_POSITIVE_EV, "PASS": PASS}

SCORER = PACKAGE_ROOT / "legacy_models" / "nhl_day0" / "day0_production.py"
SCORER_SHA = "ae1f9c5bf3b26deb5b421a235c14bbb28a259429edfa198db422f05265107579"
CONTROLS_SHA = "4b6119a04f2b4129b4fda4e3511d5c5b3dc9b083ed5368cf2d52c42a28be8b15"
ADAPTER_SHA = "3a52e46266402d31e19ddf5273c478c009b4a2624133152f5b2340921eee1478"
FIXTURE_DIR = PACKAGE_ROOT / "tests" / "golden" / "fixtures" / "NHL_DAY0_20261112" / "inputs"
ADJUSTED_REASON = ("RELEASE_REPORTS_UNAVAILABLE: Day-0 scorer emits adjusted_kelly=None "
                   "(research only; authorized_stake_usd=0)")

_RUNNER = r'''
import csv, json, sys
sys.path.insert(0, sys.argv[1])
import nhl_adapter
captured = []
_orig = nhl_adapter.model.score_games
def _capture(games, params):
    result = _orig(games, params)
    captured.append(result[0])
    return result
nhl_adapter.model.score_games = _capture
out, incomplete, audits = nhl_adapter.score(sys.argv[2])
json.dump(dict(out=out, contracts=captured[0] if captured else [], incomplete=incomplete, audits=audits,
               control_sha=nhl_adapter.CONTROL_SHA), open(sys.argv[3], "w"))
'''


@dataclass(frozen=True)
class Day0Inputs:
    """The two frozen files the scorer needs besides itself, hash-checked."""
    controls: Path
    original_adapter: Path

    @classmethod
    def from_fixture(cls) -> "Day0Inputs":
        return cls(FIXTURE_DIR / "OBSERVED_PRICE_ALL_CONTROLS.csv", FIXTURE_DIR / "nhl_score_adapter_ORIGINAL.py")

    @classmethod
    def from_store(cls, store, dest: Path) -> "Day0Inputs":
        """Materialize both files from the model-input store (``md_source_files``) by SHA-256."""
        dest = Path(dest)
        return cls(store.materialize_source(CONTROLS_SHA, dest / "OBSERVED_PRICE_ALL_CONTROLS.csv"),
                   store.materialize_source(ADAPTER_SHA, dest / "nhl_score_adapter_ORIGINAL.py"))

    def verify(self) -> None:
        for path, digest in ((self.controls, CONTROLS_SHA), (self.original_adapter, ADAPTER_SHA),
                             (SCORER, SCORER_SHA)):
            if _sha(Path(path).read_bytes()) != digest:
                raise ValueError(f"frozen NHL input hash mismatch: {path}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_frozen_scorer(quotes_csv: Path, inputs: Optional[Day0Inputs] = None,
                      workdir: Optional[Path] = None) -> dict:
    """Execute the unchanged scorer + original adapter on a capture ``quotes.csv`` (stdlib only).

    Returns ``out`` (the original adapter rows), ``contracts`` (the scorer's full contracts, same
    order), ``incomplete`` (skipped event ids), ``audits`` and ``control_sha``.
    """
    inputs = inputs or Day0Inputs.from_fixture()
    inputs.verify()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(workdir or tmp)
        pkg = work / "models" / "nhl_day0"
        pkg.mkdir(parents=True, exist_ok=True)
        (work / "models" / "__init__.py").write_text("")
        (pkg / "__init__.py").write_text("")
        shutil.copy2(SCORER, pkg / "day0_production.py")
        shutil.copy2(inputs.controls, pkg / "OBSERVED_PRICE_ALL_CONTROLS.csv")
        shutil.copy2(inputs.original_adapter, work / "nhl_adapter.py")
        (work / "run_day0.py").write_text(_RUNNER)
        result = work / "day0_result.json"
        done = subprocess.run([sys.executable, "-B", "run_day0.py", str(work), str(Path(quotes_csv).resolve()),
                               str(result)], cwd=work, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(done.stderr[-2000:])
        data = json.loads(result.read_text())
    if len(data["out"]) != len(data["contracts"]):
        raise ValueError("scorer contracts and adapter rows are not aligned")
    return data


def adapt(out: list[dict], contracts: list[dict], quotes: Iterable[QuoteSide],
          incomplete: Iterable[str] = ()) -> list[ScoreRow]:
    """Map the original adapter rows (+ the scorer's contracts) to ScoreRows."""
    quotes = [q for q in quotes if q.sport == "NHL"]
    by_key = {(q.event_id, q.market, q.side): q for q in quotes}
    rows: list[ScoreRow] = []
    for o, c in zip(out, contracts):
        release = RELEASE_BY_LABEL[o["model_version"]]
        if c["model"] != o["model_version"] or str(c["game_id"]) != str(o["event_id"]):
            raise ValueError(f"misaligned contract for {o['event_id']} {o['model_version']}")
        q = by_key[(str(o["event_id"]), o["market"], o["side"])]
        line = None if o["line"] in (None, "") else float(o["line"])
        if (q.line is None) != (line is None) or (line is not None and abs(q.line - line) > 1e-9) \
                or q.american_odds is None or abs(q.american_odds - float(o["odds"])) > 1e-9:
            raise ValueError(f"{release}: priced {line}/{o['odds']} but quoted {q.line}/{q.american_odds}")
        common = dict(recorded_role=o["model_role"], original_tier=o["tier"], model_signal=c["research_status"],
                      model_action=o["status"], score_as_of_utc=None,
                      diagnostics={"feature_cutoff": o["feature_cutoff"], "feature_source": o["feature_source"],
                                   "no_vig_probability": c.get("no_vig_p"), "scorer_source_label": c.get("source_label")})
        if o["model_p"] is None:
            rows.append(ScoreRow(release, q.quote_id, UNSCORED, reason=c["research_status"], **common))
            continue
        p_win, p_loss, p_push = c["model_p_win"], c["model_p_loss"], c["model_p_push"]
        if abs(p_win - o["model_p"]) > 1e-15:
            raise ValueError(f"{release}: contract p {p_win} != adapter p {o['model_p']}")
        rows.append(ScoreRow(
            release, q.quote_id, SCORED, p_win, p_loss, p_push, probability_basis=UNCONDITIONAL,
            push_probability_status=PUSH_MODEL if push_possible(q.market, q.line) else PUSH_ZERO_BY_LINE,
            action_class=STATUS_ACTION[o["status"]], legacy_ev=o["ev"], legacy_full_kelly=o["full_kelly"],
            adjusted_kelly_null_reason=ADJUSTED_REASON, **common))
    skipped = {str(e) for e in incomplete}
    for q in quotes:
        if q.event_id in skipped:
            for release in MARKET_RELEASES.get(q.market, ()):
                rows.append(ScoreRow(release, q.quote_id, UNSCORED,
                                     reason="INCOMPLETE_OR_NOT_PREGAME_BOARD: original adapter requires six "
                                            "OFFERED_PREGAME sides"))
    covered = {(r.release_id, r.quote_id) for r in rows}
    missing = [(rel, q.quote_id) for q in quotes for rel in MARKET_RELEASES.get(q.market, ())
               if (rel, q.quote_id) not in covered]
    if missing:
        raise ValueError(f"NHL scorer produced no row for {missing[:3]}")
    return rows


def score_capture(quotes_csv: Path, inputs: Optional[Day0Inputs] = None) -> tuple[list[QuoteSide], list[ScoreRow]]:
    """Quotes + ScoreRows for one capture ``quotes.csv`` (archived or new) using the frozen Day-0 scorer."""
    quotes = from_capture_csv(quotes_csv, sport="NHL")
    data = run_frozen_scorer(quotes_csv, inputs)
    return quotes, adapt(data["out"], data["contracts"], quotes, data["incomplete"])


__all__ = ["MARKET_RELEASES", "RELEASES", "Day0Inputs", "adapt", "run_frozen_scorer", "score_capture"]
