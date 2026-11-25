"""NBA bet sheets.

``build_frozen_sheet`` assembles the complete chronological sheet for the archived Nov 12
board: every quoted side x R4 champion (scored by the frozen scorer) and the R3 challenger
(BLOCKED: artifacts missing). See docs/betsheets/shared-contract.md and docs/sports/nba.md.
"""
from __future__ import annotations

from typing import Optional

from gambling.models.nba.r4_legacy import RELEASES, score_frozen_board
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous


def build_frozen_sheet(authority: Optional[Authority], rerun: bool = False, previous=None) -> list[dict]:
    quotes, scores = score_frozen_board(rerun=rerun)
    return mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(RELEASES)), previous)


__all__ = ["build_frozen_sheet"]
