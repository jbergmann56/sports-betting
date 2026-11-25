"""Chronological, all-rows bet-sheet exports (CSV and Excel).

The CSV and the Excel "All rows" sheet contain **every** assembled row: positive,
zero and negative EV, Pass, Lean, research, NOT_EVALUATED_BY_MODEL, UNSCORED,
BLOCKED and QUOTE_NOT_OFFERED. Other workbook sheets are views over the same rows
and never remove or edit records. Excel output needs ``openpyxl`` (``[models]``
extra); CSV output is standard library only.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping, Optional, Sequence

from gambling.scoring.sheet import COLUMNS

POSITIVE_EV_VIEW_NOTE = ("VIEW ONLY: rows with model EV > 0 from SCORED / CONDITIONAL_SCORED model output. "
                         "Not a recommendation list; authorization is in release_wager_authorized and status. "
                         "Derived complements never appear here.")


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return v


def write_csv(rows: Sequence[Mapping], path: str | Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r.get(k)) for k in COLUMNS})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def champion_challenger_view(rows: Sequence[Mapping]) -> tuple[list[str], list[list]]:
    """One line per quote side: champion fields next to each challenger/shadow release."""
    key_cols = ["start_time_ct", "sport", "event_id", "away", "home", "market", "side", "selection", "line",
                "american_odds", "quote_status"]
    per = ["model_release_id", "model_status", "original_tier", "action_class", "p_win", "p_win_given_decisive",
           "derived_p_win", "ev", "ev_basis", "full_kelly", "adjusted_kelly", "adjusted_kelly_null_reason", "status"]
    groups: dict[tuple, dict[str, list[Mapping]]] = {}
    for r in rows:
        k = tuple(r.get(c) for c in key_cols)
        role = "CHAMPION" if (r.get("release_role") or r.get("recorded_role")) == "CHAMPION" else "OTHER"
        groups.setdefault(k, {"CHAMPION": [], "OTHER": []})[role].append(r)
    n_other = max((len(g["OTHER"]) for g in groups.values()), default=0)
    header = key_cols + [f"champion_{c}" for c in per]
    for i in range(n_other):
        header += [f"challenger{i + 1}_{c}" for c in per]
    body = []
    for k, g in groups.items():
        line = list(k)
        champs = g["CHAMPION"] or [{}]
        for champ in champs:
            out = line + [champ.get(c) for c in per]
            others = g["OTHER"] + [{}] * (n_other - len(g["OTHER"]))
            for o in others:
                out += [o.get(c) for c in per]
            body.append(out)
    return header, body


def write_excel(rows: Sequence[Mapping], path: str | Path, provenance: Optional[Mapping] = None) -> str:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Excel export needs openpyxl: pip install -e .[models]") from exc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    def sheet(ws, header, body, note=None):
        start = 1
        if note:
            ws.cell(row=1, column=1, value=note).font = Font(italic=True)
            start = 2
        for j, h in enumerate(header, 1):
            ws.cell(row=start, column=j, value=h).font = Font(bold=True)
        for i, values in enumerate(body, start + 1):
            for j, v in enumerate(values, 1):
                ws.cell(row=i, column=j, value=_cell(v))
        ws.freeze_panes = ws.cell(row=start + 1, column=1)
        if body:
            ws.auto_filter.ref = f"A{start}:{get_column_letter(len(header))}{start + len(body)}"

    ws = wb.active
    ws.title = "All rows"
    sheet(ws, COLUMNS, [[r.get(c) for c in COLUMNS] for r in rows])
    header, body = champion_challenger_view(rows)
    sheet(wb.create_sheet("Champion vs Challenger"), header, body)
    positive = [r for r in rows if r.get("ev") not in (None, "") and float(r["ev"]) > 0
                and r.get("model_status") in ("SCORED", "CONDITIONAL_SCORED")]
    sheet(wb.create_sheet("Positive EV view"), COLUMNS, [[r.get(c) for c in COLUMNS] for r in positive],
          note=POSITIVE_EV_VIEW_NOTE)
    prov = dict(provenance or {})
    prov.setdefault("rows_total", len(rows))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("status") or ""] = counts.get(r.get("status") or "", 0) + 1
    prov["rows_by_status"] = counts
    legend = [
        ("model_status", "SCORED | CONDITIONAL_SCORED | EVALUATED | NOT_EVALUATED_BY_MODEL | UNSCORED | BLOCKED"),
        ("original_tier", "Tier recorded by the frozen scorer; NONE for sides the model did not evaluate"),
        ("probability_basis", "UNCONDITIONAL or CONDITIONAL_DECISIVE (P given a non-push result)"),
        ("derived_*", "Labelled mathematical complement of the opposite side's model probability; no tier/EV/Kelly"),
        ("ev / ev_basis", "b*p_win - p_loss (unconditional) or b*p - (1-p) (conditional on decisive)"),
        ("full_kelly", "Single-bet push-refund Kelly; conditional basis is a diagnostic, not a portfolio size"),
        ("adjusted_kelly", "Only as computed by the release, with method/certification; otherwise null + reason"),
        ("status", "Presentation label from the model's recorded action and registry authorization at quote time"),
    ]
    ws = wb.create_sheet("Provenance & Legend")
    r = 1
    for k, v in prov.items():
        ws.cell(row=r, column=1, value=str(k)).font = Font(bold=True)
        ws.cell(row=r, column=2, value=json.dumps(v) if isinstance(v, (dict, list)) else _cell(v))
        r += 1
    r += 1
    for k, v in legend:
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
        r += 1
    wb.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()
