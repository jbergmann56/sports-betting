"""Versioned, append-only model-input database (MySQL; SQLite for CI/offline).

Shared by ChatGPT research and Claude development as the authoritative store of
historical games, odds snapshots, ratings, pregame feature snapshots, model
releases, predictions and evaluation results. See docs/model-data/README.md.
The existing SQLite scoring history (gambling/db) is unchanged and remains the
operational record until migration is independently validated.
"""
from .store import ModelDataError, Store, connect, guard_columns

__all__ = ["ModelDataError", "Store", "connect", "guard_columns"]
