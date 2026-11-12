"""Use frozen NHL Day0 three-market champion on Nov7 Bovada main lines.

Frozen 2021-25 residual coefficients and pairwise calibration are preserved.
Moneyline, puck line and total sides are retained, including Passes. V15
challenger remains explicitly UNSCORED without current-season feature parity.
"""
from pathlib import Path
import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import sys

ROOT=Path(__file__).resolve().parent
ap=argparse.ArgumentParser()
ap.add_argument('--date',default='2026-11-10')
ap.add_argument('--out',type=Path,default=ROOT/'outputs/bovada_20261110_raw')
args=ap.parse_args()
OUT=args.out
BASE=ROOT/'recovered_sources/nhl_day0/nhl_rebuild'
SCORER=BASE/'day0_production.py'
CONTROL=BASE/'day0_recovered/expanded/OBSERVED_PRICE_ALL_CONTROLS.csv'
spec=importlib.util.spec_from_file_location('frozen_nhl_day0_scorer',SCORER)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
params=mod.historical_segments(CONTROL)
board=[r for r in csv.DictReader((OUT/'NHL_main_board.csv').open(newline='')) if r['start_central'][:10]==args.date and r['pregame']=='True']
assert board and all(x['pregame']=='True' for x in board)

def num(x):
    n=float(x)
    assert math.isfinite(n)
    return n

games=[];quote_lookup={}
for row in board:
    a={'ml_price':num(row['away_ml_odds']), 'pl_price':num(row['away_spread_odds']),
       'pl_line':num(row['away_spread_line']), 'total_price':num(row['over_odds']),
       'total_line':num(row['total_line'])}
    h={'ml_price':num(row['home_ml_odds']), 'pl_price':num(row['home_spread_odds']),
       'pl_line':num(row['home_spread_line']), 'total_price':num(row['under_odds']),
       'total_line':num(row['total_line'])}
    assert abs(a['pl_line']+h['pl_line'])<1e-9
    game={'game_id':row['event_id'],'start_utc':row['start_utc'],
          'away':row['away'],'home':row['home'],'quote_away':a,'quote_home':h}
    games.append(game);quote_lookup[row['event_id']]=row

scores,audits=mod.score_games(games,params)
assert len(scores)==len(board)*12 and len(audits)==len(board)
for item in scores:
    raw=quote_lookup[item['game_id']]
    item['date']=args.date
    item['quote_captured_utc']=raw['captured_utc']
    item['quote_source']='BOVADA_PUBLIC_EVENT_API_MAIN_GAME_LINES'
    item['source_label']='Bovada public event API'
    item['scoring_status']='RESEARCH_ONLY' if item['model_p_win'] is not None else 'UNSCORED_MISSING_VALIDATED_FEATURES'
    item['production_authorized']=False
    item['adjusted_kelly_status']='UNAVAILABLE_POSTERIOR_AWARE_JOINT_VALIDATION'
    item['model_health']='Day0 odds-anchor transferred to Bovada, calibration not bookmaker-certified; V15 unavailable without exact pregame inputs'
    item['bookmaker']='Bovada'
    item['source_file']='NHL_main_board.csv'
    item['historical_controls_sha256']=hashlib.sha256(CONTROL.read_bytes()).hexdigest()

for a in audits:
    assert max(abs(a[k]) for k in ('ml_complement_residual','pl_complement_residual','total_probability_residual'))<1e-10
    assert a['favorite_margin_constraint']
(OUT/'NHL_DAY0_ALL_SCORES.json').write_text(json.dumps(scores,indent=2))
(OUT/'NHL_DAY0_COHERENCE_AUDIT.json').write_text(json.dumps(audits,indent=2))
with (OUT/'NHL_DAY0_ALL_SCORES.csv').open('w',newline='') as f:
    fields=[k for k in scores[0] if k!='raw_probability_audit']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(scores)
summary={'games':len(board),'all_model_rows':len(scores),
         'champion_positive_research':sum(s['model_role']=='CHAMPION' and s['model_ev'] is not None and s['model_ev']>0 for s in scores),
         'v15_unscored':sum('V15' in s['model'] and s['model_p_win'] is None for s in scores),
         'source_models':['NHL-ML-DAY0-V1-2026-10-25','NHL-PL-DAY0-V1-2026-10-25','NHL-OU-DAY0-V1-2026-10-25'],
         'status':'ALL RESEARCH ONLY, NO PRODUCTION STAKING AUTHORIZATION'}
(OUT/'NHL_DAY0_MODEL_MANIFEST.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
print('RESEARCH POSITIVE:')
for s in scores:
    if s['model_role']=='CHAMPION' and s['model_ev'] is not None and s['model_ev']>0:
        print(s['game'],s['market'],s['selection'],s['american_odds'],round(s['model_ev']*100,2),'%EV')
