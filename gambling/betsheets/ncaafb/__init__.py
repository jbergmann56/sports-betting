"""NCAAFB bet sheets.

``build_frozen_sheet`` assembles the complete chronological sheet for the archived Nov 2
(Week 10) board: every quoted side x the releases registered for its market (spread
champion PP-V2 + continuous-V1 challenger; shared ML rule; shared OU research rule).
See docs/betsheets/shared-contract.md and docs/sports/ncaafb.md.
"""
from __future__ import annotations

from typing import Optional

from gambling.models.ncaafb.w8plus_legacy import MARKET_RELEASES, RELEASES, score_frozen_board
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous


def build_frozen_sheet(authority: Optional[Authority], rerun: bool = False, previous=None) -> list[dict]:
    quotes, scores = score_frozen_board(rerun=rerun)
    return mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(RELEASES),
                                         market_releases=MARKET_RELEASES), previous)


__all__ = ["build_frozen_sheet"]
