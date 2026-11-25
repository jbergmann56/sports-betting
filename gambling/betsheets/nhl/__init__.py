"""NHL bet sheets.

``build_capture_sheet`` assembles the complete chronological sheet for one capture
``quotes.csv`` with the frozen Day-0 scorer: every quoted NHL side x the champion and
challenger registered for that market (docs/betsheets/shared-contract.md,
docs/sports/nhl.md). Every NHL release is research-only (wagering not authorized),
so no row is wager-eligible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from gambling.core.quotes import complete_board
from gambling.models.nhl.day0_legacy import MARKET_RELEASES, RELEASES, Day0Inputs, score_capture
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous


def build_capture_sheet(quotes_csv: Path, authority: Optional[Authority], inputs: Optional[Day0Inputs] = None,
                        previous=None) -> list[dict]:
    quotes, scores = score_capture(quotes_csv, inputs)
    board = complete_board(quotes)
    return mark_new_vs_previous(assemble(board, scores, authority, releases=list(RELEASES),
                                         market_releases=MARKET_RELEASES), previous)


__all__ = ["build_capture_sheet"]
