"""NCAABB V4 (production candidate through 2025): frozen-scorer adapter and master append.

Runs the UNCHANGED archived pipeline: the original ``prepare_and_score.py`` wrapper via
``rebuild_nov01_offline.py``, then ``score_ncaabb_v4.py`` with
``NCAABB_V4_PRODUCTION_CANDIDATE.joblib`` (scikit-learn 1.8.0 is mandatory). It maps
``V4_scored_markets.csv`` to adapter contract v2.

Releases (registry migration 0005):

* ``NCAABB_V4_PROD_THROUGH2025``: CHAMPION, wager-authorized. Effective date inferred from the
  binary's timestamp (PR #4 decision 6).
* ``NCAABB_V5_PROSPECTIVE_SHADOW`` (SHADOW, ``PARTIAL``) and ``NCAABB_V4_VALIDATION_FROZEN2024``
  (RESEARCH, retrospective only) have no scorer for this board. They are not put on the sheet.
  V5's first recorded score is 2026-11-06, after this board.

Mapping (verified against golden fixture ``NCAABB_V4_20261101``, 35/35 rows):

* **Sides.** One evaluated side per market (``selected_side``). The other side is
  ``NOT_EVALUATED_BY_MODEL``, and a complement is shown only where the shared sheet can label it
  ``DERIVED_COMPLEMENT`` (PR #4 decision 3).
* **Probabilities.** ``selected_probability`` is V4's conditional non-push probability. V4 attaches
  its own push estimate (``estimated_push_probability``: the segment's integer-line push rate on
  integer lines, 0 otherwise). The row is therefore unconditional:
  - P(win) = (1 − push)·p, P(loss) = (1 − push)·(1 − p), P(push) = push;
  - EV = (1 − push)·(b·p − (1 − p)), which is ``expected_unit_net_at_quote``;
  - ``push_probability_status`` is MODEL on integer lines and ZERO_BY_LINE otherwise.
* **Action classes** follow V4's recorded pre-bet eligibility, ``stake_eligible``, not the tier label:
  - eligible → QUALIFIED;
  - not eligible, tier Lean → LEAN;
  - otherwise → PASS.
  The original tier (B / Lean / Pass) stays in ``original_tier``. V4 marks 7 "Lean" rows as
  stake-eligible on Nov 1. They are therefore QUALIFIED, and PRODUCTION_QUALIFIED for the
  authorized champion.
* **Adjusted Kelly.** ``final_recommended_kelly`` passes through: Full Kelly × evidence factor ×
  health multiplier × portfolio factor (portfolio factor 1.0; "no correlation optimizer").
  Method ``V4_EVIDENCE_FACTOR_HEURISTIC``; certification ``LEGACY_NOT_PORTFOLIO_CERTIFIED`` (PR #4
  decision 2).
* **Blocked events.** Events in the Bovada response that the preparer blocked (Nov 1: Villanova @
  Notre Dame, "Captured after scheduled tip / not a pregame quote") get ``BLOCKED`` rows with
  the preparer's reason.

Master. ``master_records_from_inputs`` turns a run's pregame scoring inputs into rows of the
NCAABB master (``ncaabb/master`` in the model-input store, keyed by ESPN ``game_id``). The 58
columns the inputs share with the master are copied verbatim. The 76 master-only columns
(results, unit nets, source audit) are left empty, because the archive has no builder that
derives them. ``record_origin`` and ``notes`` say so. ``append_run_to_master`` appends them; a later
results run with the same ``game_id`` supersedes them.
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
from typing import Iterable, Mapping, Optional, Sequence

from gambling.config import PACKAGE_ROOT
from gambling.core.bovada import quotes_from_bovada
from gambling.core.quotes import OPPOSITE, QuoteSide
from gambling.models.base import (
    AK_LEGACY_NOT_CERTIFIED, BLOCKED, LEAN, NOT_EVALUATED_BY_MODEL, PASS, PUSH_MODEL, PUSH_ZERO_BY_LINE,
    QUALIFIED, SCORED, UNCONDITIONAL, ScoreRow, push_possible,
)

CHAMPION = "NCAABB_V4_PROD_THROUGH2025"
RELEASES = (CHAMPION,)
FIXTURE = PACKAGE_ROOT / "tests" / "golden" / "fixtures" / "NCAABB_V4_20261101"
LEGACY = PACKAGE_ROOT / "legacy_models" / "ncaabb_v4"
MASTER_DATASET = "ncaabb/master"
AK_METHOD = ("V4_EVIDENCE_FACTOR_HEURISTIC: full_kelly x evidence_factor x health_stake_multiplier x "
             "portfolio_factor (no correlation optimizer)")
FROZEN_BLOCK_REASON = ("PREPARER_BLOCKED: event absent from the archived V4_scoring_inputs.csv "
                       "(blocked_events.csv was not archived; rerun to read the preparer's reason)")


def _f(v) -> Optional[float]:
    if v is None or str(v).strip() in ("", "nan", "NaN", "None"):
        return None
    x = float(v)
    return None if math.isnan(x) else x


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------- scorer
def run_frozen_pipeline(external_dir: Path, workdir: Optional[Path] = None) -> dict:
    """Run the unchanged Nov 1 pipeline; return scored markets, scoring inputs and blocked events.

    Needs the pinned model environment (scikit-learn 1.8.0) and the two external inputs (the
    master and the 2026 schedule) from the reproducibility package, both hash-checked.
    """
    sys.path.insert(0, str(PACKAGE_ROOT))
    from tests.golden.replay import Ctx, run_ncaabb  # the golden runner is the reference harness

    manifest = json.loads((FIXTURE / "MANIFEST.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(workdir or tmp)
        report = run_ncaabb(manifest, work, Path(external_dir), Ctx())
        root = work / "nov01_v4_inputs"
        return dict(report=report, scored=_read(root / "V4_scored_markets.csv"),
                    inputs=_read(root / "V4_scoring_inputs.csv"), blocked=_read(root / "blocked_events.csv"))


def load_frozen_board(fixture: Path = FIXTURE) -> dict:
    meta = json.loads((fixture / "inputs" / "manifest.json").read_text())
    raw = json.loads((fixture / "inputs" / "bovada_raw.json").read_text())
    quotes = quotes_from_bovada(raw, meta["captured_utc"], "NCAABB", "NCAABB_V4_20261101/inputs/bovada_raw.json")
    return dict(quotes=quotes, captured_utc=meta["captured_utc"],
                scored=_read(fixture / "expected" / "V4_scored_markets.csv"),
                inputs=_read(fixture / "expected" / "V4_scoring_inputs.csv"), blocked=None)


# ---------------------------------------------------------------------- mapping
def _action(r: Mapping) -> str:
    if r["stake_eligible"] == "True":
        return QUALIFIED
    return LEAN if r["tier"] == "Lean" else PASS


def _quoted_line(r: Mapping, side: str) -> Optional[float]:
    if r["market"] == "Spread":
        away = float(r["away_spread"])
        return away if side == "Away" else -away
    return float(r["total_line"]) if r["market"] == "Total" else None


def adapt(scored: Iterable[Mapping], quotes: Iterable[QuoteSide],
          blocked: Optional[Iterable[Mapping]] = None) -> list[ScoreRow]:
    quotes = [q for q in quotes if q.sport == "NCAABB"]
    by_key = {(q.event_id, q.market, q.side): q for q in quotes}
    out: list[ScoreRow] = []
    for r in scored:
        event = r["game_id"].removeprefix("BOVADA_")
        side = r["selected_side"]
        q = by_key[(event, r["market"], side)]
        line = _quoted_line(r, side)
        if (line is None) != (q.line is None) or (line is not None and abs(q.line - line) > 1e-9) \
                or abs(q.american_odds - float(r["quoted_odds"])) > 1e-9:
            raise ValueError(f"{r['game_id']} {r['market']} {side}: scored {line}/{r['quoted_odds']} "
                             f"but quoted {q.line}/{q.american_odds}")
        p, push = float(r["selected_probability"]), float(r["estimated_push_probability"])
        if push > 0 and not push_possible(q.market, q.line):
            raise ValueError(f"{r['game_id']}: push estimate {push} on a line that cannot push")
        diag = {k: r[k] for k in ("selected_model", "full_segment", "evidence_segment", "fallback_level",
                                  "structural_role", "selected_market_no_vig_p", "probability_edge_no_vig",
                                  "raw_n", "effective_n", "evidence_factor", "probability_positive_edge_approx",
                                  "adjusted_kelly_before_portfolio", "portfolio_factor", "health_stake_multiplier",
                                  "calibration_health", "market_financial_health", "pricing_status",
                                  "cash_bet_status", "scoring_role", "model_week_source") if r.get(k) not in (None, "")}
        out.append(ScoreRow(
            CHAMPION, q.quote_id, SCORED, (1 - push) * p, (1 - push) * (1 - p), push,
            probability_basis=UNCONDITIONAL,
            push_probability_status=PUSH_MODEL if push_possible(q.market, q.line) else PUSH_ZERO_BY_LINE,
            action_class=_action(r), recorded_role="CHAMPION", original_tier=r["tier"],
            model_signal=r["health"], model_action=f"stake_eligible={r['stake_eligible']}",
            legacy_ev=float(r["expected_unit_net_at_quote"]), legacy_full_kelly=float(r["full_kelly"]),
            adjusted_kelly=float(r["final_recommended_kelly"]), adjusted_kelly_method=AK_METHOD,
            adjusted_kelly_certification=AK_LEGACY_NOT_CERTIFIED, score_as_of_utc=None, diagnostics=diag))
        opp = by_key[(event, r["market"], OPPOSITE[side])]
        out.append(ScoreRow(CHAMPION, opp.quote_id, NOT_EVALUATED_BY_MODEL, recorded_role="CHAMPION",
                            reason="MODEL_EVALUATES_SELECTED_SIDE_ONLY"))
    scored_events = {r["game_id"].removeprefix("BOVADA_") for r in scored}
    reasons = ({str(b["game_id"]).removeprefix("BOVADA_"): f"PREPARER_{b['input_status']}" for b in blocked}
               if blocked is not None else {})
    for q in quotes:
        if q.event_id not in scored_events:
            out.append(ScoreRow(CHAMPION, q.quote_id, BLOCKED, reason=reasons.get(q.event_id, FROZEN_BLOCK_REASON)))
    covered = {s.quote_id for s in out}
    missing = [q for q in quotes if q.quote_id not in covered]
    if missing:
        raise ValueError(f"V4 produced no row for quoted markets {[(q.event_id, q.market) for q in missing][:4]}")
    return out


def score_frozen_board(rerun_external: Optional[Path] = None) -> tuple[list[QuoteSide], list[ScoreRow], dict]:
    """Quotes, ScoreRows and the board for Nov 1; ``rerun_external`` re-executes the full pipeline."""
    board = load_frozen_board()
    if rerun_external is not None:
        run = run_frozen_pipeline(rerun_external)
        board = dict(board, scored=run["scored"], inputs=run["inputs"], blocked=run["blocked"], report=run["report"])
    return board["quotes"], adapt(board["scored"], board["quotes"], board["blocked"]), board


# ---------------------------------------------------------------------- master append
def master_records_from_inputs(inputs: Iterable[Mapping], master_columns: Sequence[str], run_id: str) -> list[dict]:
    """Master-shaped rows for a run's pregame scoring inputs; nothing outside the inputs is derived.

    ``run_id`` is accepted for the call signature only; it is not written into the records.
    """
    shared = [c for c in master_columns if c != "game_id"]
    out = []
    for r in inputs:
        espn = str(r.get("espn_game_id") or "").removesuffix(".0")
        if not espn:
            raise ValueError(f"{r['game_id']}: no ESPN game id; the master is keyed by ESPN game_id")
        rec = {c: ("" if r.get(c) is None else str(r[c])) for c in shared if c in r}
        rec.update({c: "" for c in master_columns if c not in rec})
        rec["game_id"] = espn
        rec["record_origin"] = "V4 daily pregame scoring input"
        # Deterministic content (no run id): a rerun of the same inputs appends nothing. The run that
        # appended a record is the APPEND version's produced_by_run.
        rec["notes"] = (f"From Bovada event {r.get('bovada_event_id', '')} captured {r.get('quote_captured_utc', '')}; "
                        "master-only fields (results, unit nets, source audit) not derived: no archived builder")
        out.append(rec)
    return out


def append_run_to_master(store, inputs: Iterable[Mapping], run_id: str, actor: str = "ncaabb-v4-adapter",
                         available_from_utc: Optional[str] = None) -> Optional[int]:
    """Append a run's games to ``ncaabb/master`` (new or changed records only). Returns the version id."""
    chain = store.chain(MASTER_DATASET)
    if not chain:
        raise ValueError(f"{MASTER_DATASET} has no base version; import the master first")
    records = master_records_from_inputs(inputs, store.columns(chain[0]), run_id)
    return store.append_records(MASTER_DATASET, records, actor,
                                f"NCAABB V4 run {run_id}: pregame scoring inputs", run_id=run_id,
                                available_from_utc=available_from_utc)


__all__ = ["CHAMPION", "RELEASES", "adapt", "append_run_to_master", "load_frozen_board",
           "master_records_from_inputs", "run_frozen_pipeline", "score_frozen_board"]
