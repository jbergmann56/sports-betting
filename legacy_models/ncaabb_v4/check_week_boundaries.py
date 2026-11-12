"""Verify the user-defined week boundary and control cash treatment."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from ncaabb_models import feature_table, rating_input
from ncaabb_matchup import prepare

ROOT = Path(__file__).resolve().parents[1]
data = pd.read_csv(ROOT/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv', low_memory=False)
base = data.loc[(data.season == 2025) & data.d1_vs_d1 & data.away_prior_srs.notna()].iloc[[120]].copy()
checks = {}
for week in [0, 7, 8, 90, 91]:
    q = base.copy()
    q['season_week'] = q['model_week'] = week
    q['model_early_season'] = week < 8
    q['model_postseason'] = week > 90
    q['away_games_before'] = q['home_games_before'] = 12
    expected = q.away_prior_srs if week < 8 else q.away_srs_pregame
    assert np.allclose(rating_input(q, 'away', 'srs'), expected)
    assert prepare(q, 'Spread', 3).regime.iloc[0] == ('Postseason' if week > 90 else 'Early' if week < 8 else 'Established')
    checks[f'week_{week}_uses_expected_rating_and_regime'] = True
    changed = q.copy()
    if week < 8:
        for c in ['away_srs_pregame', 'home_srs_pregame', 'away_osrs_pregame', 'home_osrs_pregame', 'away_def_allowance_pregame', 'home_def_allowance_pregame', 'away_srs_slope_28d', 'home_srs_slope_28d']:
            changed[c] = 1000
        for market in ['Spread', 'Moneyline', 'Total']:
            pd.testing.assert_frame_equal(feature_table(q, market), feature_table(changed, market))
            a, b = prepare(q, market, 3), prepare(changed, market, 3)
            for c in ['core_segment', 'full_segment', 'structure_cover_edge', 'structure_total_edge']:
                pd.testing.assert_series_equal(a[c], b[c])
        checks[f'week_{week}_current_ratings_have_zero_feature_and_segment_effect'] = True
    elif week == 8:
        changed['away_srs_pregame'] = q.away_srs_pregame + 10
        assert not np.allclose(feature_table(q, 'Spread').rating_gap, feature_table(changed, 'Spread').rating_gap)
        checks['week_8_current_rating_changes_features'] = True
w = pd.read_csv(ROOT/'NCAABB_WAGER_OBSERVATIONS_WEEK_CONTROLS.csv')
c = w.loc[w.is_control]
assert len(c) == 183 and c.game_id.nunique() == 61
assert c.cash_stake_for_controls.eq(0).all() and c.control_cash_net.eq(0).all()
checks['all_183_controls_retained_with_zero_cash_stake_and_net'] = True
(ROOT/'NCAABB_V4_WEEK_BOUNDARY_TESTS.json').write_text(json.dumps(checks, indent=2))
print(json.dumps(checks))
