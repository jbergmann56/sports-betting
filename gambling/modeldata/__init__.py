"""Versioned, append-only model-input store inside the rolling history SQLite database.

Shared by ChatGPT research and Claude development as the store of historical games,
odds snapshots, ratings, pregame feature snapshots, predictions and evaluation
results. The md_* tables (migration 0006) build on the existing data model: releases
come from model_releases, runs link to capture batches, quote cohorts and
model_scores, and rows can carry the existing game_key. See docs/model-data/README.md.
"""
from .store import ModelDataError, Store, guard_columns, open_store

__all__ = ["ModelDataError", "Store", "guard_columns", "open_store"]
