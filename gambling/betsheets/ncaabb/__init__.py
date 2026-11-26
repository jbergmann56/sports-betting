"""NCAABB bet sheets.

``build_frozen_sheet`` assembles the complete chronological sheet for the archived Nov 1
board: every quoted side x the V4 champion, with events the preparer blocked shown as
BLOCKED. See docs/betsheets/shared-contract.md and docs/sports/ncaabb.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from gambling.models.ncaabb.v4_legacy import RELEASES, score_frozen_board
from gambling.scoring.sheet import Authority, assemble, mark_new_vs_previous


def build_frozen_sheet(authority: Optional[Authority], rerun_external: Optional[Path] = None,
                       previous=None) -> list[dict]:
    quotes, scores, _ = score_frozen_board(rerun_external)
    return mark_new_vs_previous(assemble(quotes, scores, authority, releases=list(RELEASES)), previous)


__all__ = ["build_frozen_sheet"]
