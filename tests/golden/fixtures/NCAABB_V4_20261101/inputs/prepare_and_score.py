"""Normalize Bovada markets and extend the original ridge rating pipeline to 2026.

The frozen V4 estimators and calibration remain unchanged. No bets are submitted.
"""
from pathlib import Path
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
import numpy as np
import pandas as pd
from scipy.sparse import bmat, csc_matrix, diags
from scipy.sparse.linalg import spsolve

ROOT=Path(__file__).resolve().parent
V4=ROOT.parent/'basketball_audit/v4'
UTC=dt.timezone.utc
captured=dt.datetime.fromtimestamp((ROOT/'bovada_raw.json').stat().st_mtime,UTC)
master=pd.read_csv(V4/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv',low_memory=False)

def solve_season(games, prior, baseline):
    ids=sorted(set(games.away_id)|set(games.home_id))
    ix={t:i for i,t in enumerate(ids)}; n=len(ids)
    a=np.zeros((n,n)); count=np.zeros(n); mov=np.zeros(n)
    scored=np.zeros(n); allowed=np.zeros(n)
    pr=np.array([prior.get(t,(0.,0.,0.))[0] for t in ids])
    po=np.array([prior.get(t,(0.,0.,0.))[1] for t in ids])
    pa=np.array([prior.get(t,(0.,0.,0.))[2] for t in ids])
    for r in games.itertuples():
        i,j=ix[r.away_id],ix[r.home_id]
        a[i,j]+=1; a[j,i]+=1; count[i]+=1; count[j]+=1
        mov[i]+=r.away_score-r.home_score;mov[j]+=r.home_score-r.away_score
        scored[i]+=r.away_score;scored[j]+=r.home_score
        allowed[i]+=r.home_score;allowed[j]+=r.away_score
    deg=diags(count+5.)
    srs=spsolve(deg-csc_matrix(a),mov+5*pr)
    comp=spsolve(bmat([[deg,csc_matrix(a)],[csc_matrix(a.T),deg]],format='csc'),
        np.r_[scored-baseline*count+5*po,allowed-baseline*count+5*pa])
    return {t:(float(srs[i]),float(comp[i]),float(comp[n+i])) for t,i in ix.items()}

def games_for(y):
    return master[(master.season==y)&master.d1_vs_d1].copy()

g25=games_for(2025);g24=games_for(2024)
prior24={}
for side in ['away','home']:
    for r in g25.itertuples():
        prior24[getattr(r,side+'_id')]=tuple(getattr(r,side+'_'+c) for c in
            ['prior_srs','prior_osrs','prior_def_allowance'])
baseline24=(g24.away_score.sum()+g24.home_score.sum())/(2*len(g24))
prior25=solve_season(g25,prior24,baseline24)
# Verify the recovered algorithm reproduces the master on its final pregame day.
last25=g25.game_date.max()
before=g25[g25.game_date<last25]
check=solve_season(before,prior24,baseline24)
errors=[]
for r in g25[g25.game_date==last25].itertuples():
    for side in ['away','home']:
        got=check[getattr(r,side+'_id')]
        want=tuple(getattr(r,side+'_'+c) for c in
            ['srs_pregame','osrs_pregame','def_allowance_pregame'])
        errors.extend(abs(np.array(got)-np.array(want)))
assert max(errors)<1e-7, max(errors)
s26=pd.read_csv(ROOT/'mbb_schedule_2026.csv',low_memory=False)
g26=s26[(s26.status_type_name=='STATUS_FINAL')&s26.away_conference_id.notna()&s26.home_conference_id.notna()].copy()
g26=g26.drop_duplicates('id')
assert g26.season.eq(2026).all()
baseline25=(g25.away_score.sum()+g25.home_score.sum())/(2*len(g25))
prior26=solve_season(g26,prior25,baseline25)
baseline26=(g26.away_score.sum()+g26.home_score.sum())/(2*len(g26))
names={}
for side in ['away','home']:
    names.update(dict(zip(s26[side+'_id'],s26[side+'_location'])))
pd.DataFrame([{'team_id':t,'team':names.get(t),'rating_season':2026,
    'srs':v[0],'osrs':v[1],'def_allowance':v[2],
    'league_baseline_per_team':baseline26,
    'method':'Original ridge graph v1, prior weight 5, reconstructed 2025 EOY prior'}
    for t,v in prior26.items()]).to_csv(ROOT/'prior_2026_ratings.csv',index=False)

def norm(s):
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode()
    s=re.sub(r'\s*\(#\d+\)','',s).lower()
    return re.sub('[^a-z0-9]','',s.replace('&','and'))
lookup={norm(n):int(i) for i,n in names.items()}
lookup.update({'miamiflorida':2390,'denveru':2172})
events=[]
for date in ['20261101','20261102']:
    events+=json.loads((ROOT/f'espn_{date}.json').read_text()).get('events',[])
for e in events:
    for c in e['competitions'][0]['competitors']:
        t=c['team']
        for k in ['location','shortDisplayName','displayName','abbreviation']:
            if t.get(k):lookup[norm(t[k])]=int(t['id'])
schedule={frozenset(int(c['team']['id']) for c in e['competitions'][0]['competitors']):e for e in events}
def price(o):
    p=o.get('price',{}).get('american')
    return 100. if p in ['EVEN','EV','+EVEN'] else float(p)

inputs=[]; board=[]; exceptions=[]
raw=json.loads((ROOT/'bovada_raw.json').read_text())
for block in raw:
    assert block['path'][0]['link']=='/basketball/college-basketball'
    for e in block.get('events',[]):
        away=next(c for c in e['competitors'] if not c['home'])
        home=next(c for c in e['competitors'] if c['home'])
        aid,hid=lookup.get(norm(away['name'])),lookup.get(norm(home['name']))
        tip=dt.datetime.fromtimestamp(e['startTime']/1000,UTC)
        row={'game_id':'BOVADA_'+e['id'],'bovada_event_id':e['id'],
            'season':2027,'game_date':tip.astimezone(__import__('zoneinfo').ZoneInfo('America/Chicago')).date().isoformat(),
            'start_time_utc':tip.isoformat(),'away_id':aid,'home_id':hid,
            'away_team':away['name'],'home_team':home['name'],
            'quote_captured_utc':captured.isoformat(),
            'season_week':1,'model_week_source':'Explicit opening-week inference; no observed source week code',
            'model_srs_snapshot_season':2026,'away_games_before':0,'home_games_before':0,
            'away_score':np.nan,'home_score':np.nan,'actual_away_margin':np.nan,'actual_total':np.nan,
            'away_win':np.nan,'home_win':np.nan,
            'rating_asof_date':'2026-10-31','rating_max_result_date':pd.to_datetime(g26.date,utc=True).max().date().isoformat(),
            'pregame_no_future_results':True,'prior_scoring_baseline_per_team':baseline26,
            'rating_method':'Original ridge graph v1 extended to 2026; weight=5',
            'd1_vs_d1':aid in prior26 and hid in prior26,
            'away_srs_slope_28d':np.nan,'home_srs_slope_28d':np.nan}
        match=schedule.get(frozenset([aid,hid]))
        reason=[]
        if match:
            comp=match['competitions'][0]
            row['espn_game_id']=match['id'];row['neutral_site']=bool(comp.get('neutralSite',False))
            espntip=pd.to_datetime(match['date'],utc=True).to_pydatetime()
            if abs((espntip-tip).total_seconds())>3600:reason.append('Schedule start mismatch >1h')
        else:reason.append('Venue/schedule not verified')
        if tip<=captured or e.get('live'):reason.append('Captured after scheduled tip / not a pregame quote')
        if not row['d1_vs_d1']:reason.append('Missing 2026 prior ratings or D1 mapping')
        for side,t in [('away',aid),('home',hid)]:
            if t in prior26:
                v=prior26[t]
                for c,k in [('prior_srs',0),('srs_pregame',0),('prior_osrs',1),('osrs_pregame',1),('prior_def_allowance',2),('def_allowance_pregame',2)]:row[side+'_'+c]=v[k]
        for market in ['spread','total','moneyline']:
            row[market+'_time_status']='Missing'
            row[market+'_snapshot_utc']=captured.isoformat()
            row[market+'_source']='Bovada public event API'
        for dg in e.get('displayGroups',[]):
            for m in dg.get('markets',[]):
                if m.get('period',{}).get('description')!='Game':continue
                outs=m.get('outcomes',[]);desc=m.get('description')
                if len(outs)!=2:continue
                if desc in ['Moneyline','Point Spread']:
                    for o in outs:
                        side='away' if norm(o['description'])==norm(away['name']) else 'home' if norm(o['description'])==norm(home['name']) else None
                        assert side is not None,(e['description'],o['description'])
                        if desc=='Moneyline':row[side+'_moneyline']=price(o)
                        else:
                            row[side+'_spread']=float(o['price']['handicap']);row['spread_'+side+'_odds']=price(o)
                    key='moneyline' if desc=='Moneyline' else 'spread'
                elif desc=='Total':
                    for o in outs:
                        row[o['description'].lower()+'_odds']=price(o)
                        row['total_line']=float(o['price']['handicap'])
                    key='total'
                else:continue
                row[key+'_time_status']='Verified before scheduled tip' if tip>captured and not e.get('live') else 'Captured after scheduled tip'
        row['input_status']='BLOCKED: '+'; '.join(reason) if reason else 'Ready'
        board.append(row)
        if reason:exceptions.append({k:row.get(k) for k in ['game_id','away_team','home_team','input_status']})
        else:inputs.append(row)
pd.DataFrame(board).to_csv(ROOT/'bovada_normalized_board.csv',index=False)
pd.DataFrame(inputs).to_csv(ROOT/'V4_scoring_inputs.csv',index=False)
pd.DataFrame(exceptions).to_csv(ROOT/'blocked_events.csv',index=False)
manifest={'endpoint':'https://www.bovada.lv/services/sports/event/v2/events/A/description/basketball/college-basketball',
    'captured_utc':captured.isoformat(),'events':len(board),'ready':len(inputs),'blocked':len(exceptions),
    'model':'Authoritative V4 through-2025 production bundle; no model refit',
    'rating_source':'Original V1 reconstruction algorithm extended to completed 2026 SportsDataverse/ESPN D1 games',
    'rating_2026_final_games':len(g26),'rating_2025_reproduction_max_abs_error':max(errors),
    'rating_prior_weight':5,'baseline_2026':baseline26,
    'rating_source_url':'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_schedules/mbb_schedule_2026.csv',
    'model_sha256':hashlib.sha256((V4/'models/NCAABB_V4_PRODUCTION_CANDIDATE.joblib').read_bytes()).hexdigest(),
    'sizing':'Original V4 evidence-factor Adjusted Kelly; not joint portfolio Kelly',
    'bankroll':'Unspecified; report fractions only','cash_wagers_submitted':0}
(ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2),flush=True)
if inputs:
    subprocess.run([sys.executable,str(V4/'code/score_ncaabb_v4.py'),str(ROOT/'V4_scoring_inputs.csv'),
        '--output',str(ROOT/'V4_scored_markets.csv')],check=True)
