"""Game results.

``espn``: ESPN scoreboard collector for all five sports. Raw responses are stored with URL,
request date, retrieval time and SHA-256 (``espn_result_captures``, migration 0007), every
event is observed, and completed games are recorded once in ``official_game_results``;
differing later observations go to ``espn_result_conflicts``. ``nba_history_rows`` turns
recorded NBA finals into rows for the frozen R4 scorer's history file.
"""
