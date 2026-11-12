"""Reliable, provenance-preserving capture of Bovada public odds feeds.

Read-only: this package fetches publicly listed prices for analysis. It never
logs in, places wagers, or touches an account.
"""

from .parse import Event, Quote, parse_feed
from .run import FetchConfig, RunResult, fetch_board, replay_run
from .transport import Outcome, RetryPolicy, classify

__all__ = ["Event", "Quote", "parse_feed", "FetchConfig", "RunResult", "fetch_board", "replay_run",
           "Outcome", "RetryPolicy", "classify"]
