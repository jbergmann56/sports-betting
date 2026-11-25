"""NFL bet sheets.

``build_frozen_sheet`` assembles the complete chronological sheet (every quoted
side x champion/challenger) for an archived NFL board using the shared contract
(docs/betsheets/shared-contract.md). Live boards follow once a live NFL feature
source exists (docs/sports/nfl.md).
"""
from __future__ import annotations

from typing import Optional

from gambling.models.nfl.rev2_legacy import RELEASES, score_frozen_board
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous


def build_frozen_sheet(authority: Optional[Authority], rerun: bool = False, previous=None) -> list[dict]:
    quotes, scores = score_frozen_board(rerun=rerun)
    return mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(RELEASES)), previous)


__all__ = ["build_frozen_sheet"]
