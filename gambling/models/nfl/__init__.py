"""NFL model adapters.

``rev2_legacy`` -- frozen-replay adapter for NFL_REV2_CAL_20261024 (champion) and
NFL_W8_FULL_SLOPE_20261026 (challenger). It wraps the unchanged archived scorer
and is verified against the golden fixture and the archived score records. It is
not a live pipeline (no current schedule/results feed yet). See docs/sports/nfl.md.
"""
