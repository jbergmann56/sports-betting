"""Reconstruct verified 2026 ridge priors and score Nov 8 CBB V4/V5; no stakes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import bmat, csc_matrix, diags
from scipy.sparse.linalg import spsolve

ap=argparse.ArgumentParser()
ap.add_argument('--date',default='2026-11-10')
ap.add_argument('--out',type=Path,default=Path('outputs/bovada_20261110_raw'))
args=ap.parse_args()
ROOT=args.out
BASE=Path('recovered_sources/ncaabb_v4')
V5=Path('recovered_sources/ncaabb_v5/NCAABB_V5_PROSPECTIVE_SHADOW_PACKAGE')
BOARD=pd.read_csv(ROOT/'NCAABB_main_board.csv',dtype={'event_id':str})
MASTER=pd.read_csv(BASE/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv',low_memory=False)
ESPN=json.loads((ROOT/('cbb_espn_'+args.date.replace('-','')+'.json')).read_text())['events']

def solve_season(games,prior,baseline):
    ids=sorted(set(games.away_id)|set(games.home_id));ix={t:i for i,t in enumerate(ids)};n=len(ids)
    a=np.zeros((n,n));count=np.zeros(n);mov=np.zeros(n);scored=np.zeros(n);allowed=np.zeros(n)
    pr=np.array([prior.get(t,(0.,0.,0.))[0] for t in ids]);po=np.array([prior.get(t,(0.,0.,0.))[1] for t in ids]);pa=np.array([prior.get(t,(0.,0.,0.))[2] for t in ids])
    for r in games.itertuples():
        i,j=ix[r.away_id],ix[r.home_id]
        a[i,j]+=1;a[j,i]+=1;count[i]+=1;count[j]+=1
        mov[i]+=r.away_score-r.home_score;mov[j]+=r.home_score-r.away_score
        scored[i]+=r.away_score;scored[j]+=r.home_score
        allowed[i]+=r.home_score;allowed[j]+=r.away_score
    deg=diags(count+5.)
    srs=spsolve(deg-csc_matrix(a),mov+5*pr)
    comp=spsolve(bmat([[deg,csc_matrix(a)],[csc_matrix(a.T),deg]],format='csc'),
                np.r_[scored-baseline*count+5*po,allowed-baseline*count+5*pa])
    return {t:(float(srs[i]),float(comp[i]),float(comp[n+i])) for t,i in ix.items()}

def norm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode()
    s=re.sub(r'\s*\(#\d+\)','',s).lower()
    return re.sub('[^a-z0-9]','',s.replace('&','and'))

def f(x):
    try:return float(x)
    except:return float('nan')

rows=[]; aliases={}; ids_in_season=set()
for path in sorted((Path('outputs/bovada_20261108_raw')/'cbb_espn_prior_season_days').glob('*.json')):
    daily=json.loads(path.read_text())
    for e in daily.get('events',[]):
        comp=e['competitions'][0]
        if comp.get('status',{}).get('type',{}).get('name')!='STATUS_FINAL':continue
        cs=comp['competitors']
        if len(cs)!=2:continue
        home=next((c for c in cs if c.get('homeAway')=='home'),None)
        away=next((c for c in cs if c.get('homeAway')=='away'),None)
        if not home or not away:continue
        if home['team'].get('conferenceId') is None or away['team'].get('conferenceId') is None:
            continue
        try:
            aid,hid=int(away['team']['id']),int(home['team']['id'])
            asc,hsc=float(away['score']),float(home['score'])
        except (ValueError,TypeError,KeyError):continue
        rows.append({'id':e['id'],'date':e['date'],'away_id':aid,'home_id':hid,
                     'away_score':asc,'home_score':hsc,'away_name':away['team'].get('location'),
                     'home_name':home['team'].get('location')})
        ids_in_season.update([aid,hid])
        for c in cs:
            t=c['team'];tid=int(t['id'])
            for key in ('location','displayName','shortDisplayName','abbreviation'):
                if t.get(key):aliases[norm(t[key])]=tid

g26=pd.DataFrame(rows).drop_duplicates('id').copy()
g24=MASTER[(MASTER.season==2024)&MASTER.d1_vs_d1].copy()
g25=MASTER[(MASTER.season==2025)&MASTER.d1_vs_d1].copy()
prior24={}
for side in ('away','home'):
    for r in g25.itertuples():
        prior24[int(getattr(r,side+'_id'))]=tuple(getattr(r,side+'_'+c) for c in ('prior_srs','prior_osrs','prior_def_allowance'))
baseline24=(g24.away_score.sum()+g24.home_score.sum())/(2*len(g24))
prior25=solve_season(g25,prior24,baseline24)

# An ESPN D1 league scoreboard includes opponents outside D1; validate against
# previous D1 team IDs and observed frozen Nov7 rating priors before accepting.
known_d1=set(prior25)
old=pd.read_csv('recovered_sources/nov7/NCAABB_V4_INPUTS.csv')
known_d1.update(old.away_id.dropna().astype(int))
known_d1.update(old.home_id.dropna().astype(int))
g26=g26[g26.away_id.isin(known_d1)&g26.home_id.isin(known_d1)].copy()
baseline25=(g25.away_score.sum()+g25.home_score.sum())/(2*len(g25))
prior26=solve_season(g26,prior25,baseline25)
baseline26=(g26.away_score.sum()+g26.home_score.sum())/(2*len(g26))
# The Nov7 audit preserved the actual *frozen* 2026-season priors for the
# full D1 population. Use them as the input authority; the just-reconstructed
# ESPN season is a cross-check, not a replacement of authoritative inputs.
FROZEN=Path('recovered_sources/ncaabb_nov7_audit/scoring_and_audit/prior_2026_ratings.csv')
saved=pd.read_csv(FROZEN)
reconstruction_checks=[max(abs(prior26[int(r.team_id)][k]-val) for k,val in
    enumerate((r.srs,r.osrs,r.def_allowance))) for r in saved.itertuples()
    if int(r.team_id) in prior26]
reconstruction_discrepancy=max(reconstruction_checks) if reconstruction_checks else None
prior26={int(r.team_id):(float(r.srs),float(r.osrs),float(r.def_allowance))
         for r in saved.itertuples()}
baseline26=float(saved.league_baseline_per_team.iloc[0])
errors=[]
for r in old.itertuples():
    for side in ('away','home'):
        tid=int(getattr(r,side+'_id'))
        if tid not in prior26:continue
        actual=prior26[tid]
        expected=tuple(getattr(r,side+'_'+c) for c in ('srs_pregame','osrs_pregame','def_allowance_pregame'))
        errors.extend(abs(a-b) for a,b in zip(actual,expected))
max_error=max(errors) if errors else None
if errors:
    diagnostics=[]
    for r in old.itertuples():
        for side in ('away','home'):
            tid=int(getattr(r,side+'_id'))
            if tid in prior26:
                expected=tuple(getattr(r,side+'_'+c) for c in ('srs_pregame','osrs_pregame','def_allowance_pregame'))
                err=max(abs(a-b) for a,b in zip(prior26[tid],expected))
                diagnostics.append((round(err,5),tid,getattr(r,side+'_team')))
    print('Prior parity top differences:',sorted(set(diagnostics),reverse=True)[:8],flush=True)

for e in ESPN:
    for c in e['competitions'][0]['competitors']:
        t=c['team'];tid=int(t['id'])
        for key in ('location','displayName','shortDisplayName','abbreviation'):
            if t.get(key):aliases[norm(t[key])]=tid
aliases.update({'saintmarysca':2608,'csbakersfield':2934,'stthomasmn':2900,
                'wisconsingreenbay':2739,'stjohns':2599,'utarlington':250,
                'semissouristate':aliases.get('southeastmissouristate')})
games={frozenset(int(c['team']['id']) for c in e['competitions'][0]['competitors']):e for e in ESPN}

ready=[];blocked=[];features=[]
for b in BOARD.to_dict('records'):
    if not b['start_central'].startswith(args.date):continue
    aid,hid=aliases.get(norm(b['away'])),aliases.get(norm(b['home']))
    event=games.get(frozenset((aid,hid))) if aid and hid else None
    issues=[]
    if not (pd.Timestamp(b['start_utc'])>pd.Timestamp(b['captured_utc']) and b['pregame']):issues.append('NOT_PREGAME')
    if aid not in prior26 or hid not in prior26:issues.append('NO_VERIFIED_D1_PRIOR')
    if event is None:issues.append('ESPN_PAIR_UNVERIFIED')
    elif abs((pd.Timestamp(event['date'])-pd.Timestamp(b['start_utc'])).total_seconds())>3600:issues.append('ESPN_START_MISMATCH')
    if any(not np.isfinite(f(b[x])) for x in ('away_spread_line','away_spread_odds','home_spread_odds','total_line','over_odds','under_odds')):issues.append('SPREAD_TOTAL_MARKET_MISSING')
    if max_error is None or max_error>1e-5:issues.append(f'PRIOR_PARITY_FAILED:{max_error}')
    inp={'game_id':'BOVADA_'+b['event_id'],'bovada_event_id':b['event_id'],
       'season':2027,'game_date':args.date,'start_time_utc':b['start_utc'],
       'away_id':aid,'home_id':hid,'away_team':b['away'],'home_team':b['home'],
       'quote_captured_utc':b['captured_utc'],'season_week':1,
       'model_week_source':'Verified opening week (2027 season)',
       'model_srs_snapshot_season':2026,'away_games_before':0,'home_games_before':0,
       'rating_asof_date':'2026-10-31',
       'rating_max_result_date':'2026-04-07','pregame_no_future_results':True,
       'prior_scoring_baseline_per_team':baseline26,
       'rating_method':'Original ridge graph v1, prior weight 5, parity tested vs Nov7',
       'd1_vs_d1':aid in prior26 and hid in prior26,
       'away_srs_slope_28d':np.nan,'home_srs_slope_28d':np.nan,
       'espn_game_id':event['id'] if event else None,
       'neutral_site':bool(event['competitions'][0].get('neutralSite',False)) if event else False,
       'away_spread':f(b['away_spread_line']),'home_spread':f(b['home_spread_line']),
       'spread_away_odds':f(b['away_spread_odds']),'spread_home_odds':f(b['home_spread_odds']),
       'total_line':f(b['total_line']),'over_odds':f(b['over_odds']),
       'under_odds':f(b['under_odds']),'away_moneyline':f(b['away_ml_odds']),
       'home_moneyline':f(b['home_ml_odds']),
       'input_status':'BLOCKED: '+'; '.join(issues) if issues else 'Ready'}
    for market in ('spread','total','moneyline'):
        offered=market!='moneyline' or (np.isfinite(inp['away_moneyline']) and np.isfinite(inp['home_moneyline']))
        inp[market+'_snapshot_utc']=b['captured_utc']
        inp[market+'_time_status']='Verified before scheduled tip' if offered and not issues else 'Missing'
        inp[market+'_source']='Bovada public event API, '+args.date+' capture'
    for side,tid in (('away',aid),('home',hid)):
        if tid not in prior26:continue
        for field,k in (('prior_srs',0),('srs_pregame',0),('prior_osrs',1),
                        ('osrs_pregame',1),('prior_def_allowance',2),('def_allowance_pregame',2)):
            inp[side+'_'+field]=prior26[tid][k]
    features.append(inp)
    (blocked if issues else ready).append(inp)

pd.DataFrame(features).to_csv(ROOT/'NCAABB_FEATURE_AND_COVERAGE.csv',index=False)
pd.DataFrame(blocked).to_csv(ROOT/'NCAABB_BLOCKED.csv',index=False)
if ready:
    inp=ROOT/'NCAABB_V4_INPUTS.csv';pd.DataFrame(ready).to_csv(inp,index=False)
    subprocess.run([sys.executable,str(BASE/'code/score_ncaabb_v4.py'),str(inp),
        '--output',str(ROOT/'NCAABB_V4_SCORES.csv')],check=True)
    subprocess.run([sys.executable,str(V5/'score_ncaabb_v5_shadow.py'),str(inp),
        '--v4-root',str(BASE),'--prediction-output',str(ROOT/'NCAABB_V5_PREDICTIONS.csv'),
        '--opportunity-output',str(ROOT/'NCAABB_V5_OPPORTUNITIES.csv'),
        '--snapshot-id',args.date.replace('-','')+'BOVADA'],check=True)
manifest={'observed_2026_prior_season_games':len(g26),'all_2026_espn_games':len(rows),
 '2026_reconstruction_max_difference_from_frozen':reconstruction_discrepancy,
 'frozen_prior_2026_rating_source':'NCAABB_NOV7_SCORING_AND_TOTALS_AUDIT.zip:prior_2026_ratings.csv',
 'reconstruction_parity_max_error':max_error,'old_parity_count':len(errors),
 'bovada_nov10_games':len(features),'ready':len(ready),'blocked':len(blocked),
 'blocked_games':[(x['away_team'],x['home_team'],x['input_status']) for x in blocked],
 'prior_snapshot_asof':'2026-04-07','models':'NCAABB V4 frozen and V5 prospective shadow'}
(ROOT/'NCAABB_MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2),flush=True)
if ready:
    d=pd.read_csv(ROOT/'NCAABB_V4_SCORES.csv')
    q=d[d.stake_eligible.eq(True)&d.tier.isin(['A','B+','B'])&d.expected_unit_net_at_quote.gt(0)]
    print('V4 QUALIFIERS',len(q));print(q[['away_team','home_team','market','selected_side','quoted_odds','tier','selected_probability','expected_unit_net_at_quote','full_kelly']].to_string(index=False))
