"""Game schedules and finals (ESPN scoreboard/summary, SportsDataverse releases).

Plan Phase 2. Raw responses are saved like Bovada captures (URL, captured_utc,
sha256) before parsing; parsed finals load into ``official_game_results``.
Games on the schedule but absent from the book board are labelled
``NOT_LISTED_BY_BOOK``. Not implemented yet.
"""
