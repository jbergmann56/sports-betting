"""Filesystem locations, overridable so the package can live inside a larger app.

Set ``GAMBLING_DATA_DIR`` (or pass a :class:`Paths` explicitly) to relocate the
working data. Nothing else in the package hardcodes a path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FROZEN_ARCHIVE_NAME = "GAMBLING_ROLLING_AUTHORITATIVE_QUOTES_AND_SCORES.zip"
FROZEN_ARCHIVE_MEMBER = "GAMBLING_ROLLING_SCORING_HISTORY.sqlite"


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def frozen_archive(self) -> Path:
        """Bundled original evidence. Never modified."""
        return self.data_dir / FROZEN_ARCHIVE_NAME

    @property
    def frozen_db(self) -> Path:
        """Disposable read-only extraction of the frozen archive."""
        return self.data_dir / "history.sqlite"

    @property
    def database(self) -> Path:
        """The persistent, append-only rolling history."""
        return self.data_dir / "gambling.sqlite"

    @property
    def captures(self) -> Path:
        return self.data_dir / "captures"

    @property
    def archives(self) -> Path:
        return self.data_dir / "archives"


def default_paths() -> Paths:
    override = os.environ.get("GAMBLING_DATA_DIR")
    return Paths(Path(override) if override else PACKAGE_ROOT / "data")
