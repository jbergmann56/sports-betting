"""Append Nov11 five-sport quotes and scores; join Nov10 ESPN game finals.

Preserves the existing rolling SQLite history, does not infer actual wagers.
"""
import csv
import datetime as dt
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'outputs/bovada_20261111_raw'
OUT=ROOT/'outputs/NOV11_CROSS_SPORT'
MASTER=ROOT/'recovered_sources/rolling_master_v27'
BATCH='FIVE_SPORT_20261111_0039CST_V1'
NOW=dt.datetime.now(dt.timezone.utc).isoformat()


def iso(x):
    return dt.datetime.fromisoformat(str(x).replace('Z','+00:00')).astimezone(dt.timezone.utc).isoformat().replace('+00:00','Z')


def dig(s): return hashlib.sha256(str(s).encode()).hexdigest()[:24]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clean(v):
    if pd.isna(v):return None
    if isinstance(v,(bool,)):return int(v)
    if hasattr(v,'item'):v=v.item()
    return v
def american_be(x):
    if x is None or pd.isna(x) or float(x)==0:return None
    x=float(x);return (100/(100+x)) if x>0 else (-x/(-x+100))


boards={s:pd.read_csv(SOURCE/f'{s}_main_board.csv') for s in ('NCAABB','NBA','NHL','NCAAFB','NFL')}
events=[];quotes=[];scores=[];files=[]
lookup={};quote_map={}
for sport,df in boards.items():
    for _,r in df.iterrows():
        event_id=str(r.event_id)
        key=f'{sport}:BOVADA:{event_id}'
        captured=iso(r.captured_utc)
        ev=dict(batch_id=BATCH,sport=sport,event_id=event_id,game_key=key,game=r.game,
            away=r.away,home=r.home,start_utc=iso(r.start_utc),
            quote_captured_utc=captured,quote_cohort_id=None,
            pregame_quote=int(bool(r.pregame) and not bool(r.live)),physical_game=1,
            bovada_url=str(r.bovada_url) if pd.notna(r.bovada_url) else None,
            raw_board_json=json.dumps({str(k):clean(v) for k,v in r.items()},sort_keys=True))
        events.append(ev)
        lookup[(sport,event_id)]=ev
        lookup[(sport,str(r.game))]=ev

        for market,sides in (
            ('Moneyline',[('Away',None,r.away_ml_odds),('Home',None,r.home_ml_odds)]),
            ('Spread',[('Away',r.away_spread_line,r.away_spread_odds),('Home',r.home_spread_line,r.home_spread_odds)]),
            ('Total',[('Over',r.total_line,r.over_odds),('Under',r.total_line,r.under_odds)])):
            for side,line,odds in sides:
                valid_odds=clean(odds)
                qid=dig(f'{BATCH}|{sport}|{event_id}|{market}|{side}|{line}|{valid_odds}')
                q=dict(quote_id=qid,batch_id=BATCH,sport=sport,event_id=event_id,game_key=key,
                    quote_cohort_id=None,quote_captured_utc=captured,market=market,period='Full game',
                    side=side,line=clean(line),odds_american=valid_odds,
                    break_even_probability=american_be(valid_odds),
                    quote_status='OFFERED_PREGAME' if valid_odds is not None else 'NOT_OFFERED',
                    source_file=f'{sport}_main_board.csv',source_sha256=sha(SOURCE/f'{sport}_main_board.csv'))
                quotes.append(q)
                quote_map[(sport,event_id,market,side)]=q

times=sorted(events,key=lambda x:x['quote_captured_utc']);groups=[]
for e in times:
    t=dt.datetime.fromisoformat(e['quote_captured_utc'].replace('Z','+00:00'))
    if not groups or (t-dt.datetime.fromisoformat(groups[-1][0]['quote_captured_utc'].replace('Z','+00:00'))).total_seconds()>120:
        groups.append([])
    groups[-1].append(e)
cohorts=[]
for i,g in enumerate(groups,1):
    cid=f'{BATCH}:COHORT:{i:03}'
    for e in g:e['quote_cohort_id']=cid
    ts=[dt.datetime.fromisoformat(e['quote_captured_utc'].replace('Z','+00:00')) for e in g]
    cohorts.append(dict(cohort_id=cid,batch_id=BATCH,min_quote_utc=iso(min(ts)),max_quote_utc=iso(max(ts)),
        quote_skew_seconds=(max(ts)-min(ts)).total_seconds(),sports_json=json.dumps(sorted({e['sport'] for e in g})),physical_games=len(g)))
cohort_by={(e['sport'],e['event_id']):e['quote_cohort_id'] for e in events}
for q in quotes:q['quote_cohort_id']=cohort_by[(q['sport'],q['event_id'])]


def save_score(sport,event_id,market,side,role,model,tier,p,ev,full,adjusted,auth,action,reason,row,source):
    game=lookup.get((sport,str(event_id)))
    if game is None:return
    quote=quote_map.get((sport,str(event_id),market,side))
    qid=quote['quote_id'] if quote and quote['quote_status']=='OFFERED_PREGAME' else None
    row_json=json.dumps({str(k):clean(v) for k,v in row.items()},sort_keys=True,default=str)
    scores.append(dict(score_id=dig(f'{BATCH}|{sport}|{event_id}|{source}|{role}|{market}|{side}|{row_json}'),
        batch_id=BATCH,sport=sport,event_id=str(event_id),game_key=game['game_key'],
        quote_cohort_id=game['quote_cohort_id'],quote_captured_utc=game['quote_captured_utc'],
        scored_at_utc=NOW,scored_time_provenance='RUN_COMPLETION_TIMESTAMP',model_probability_asof_utc=None,
        market=market,selection_side=side,selection_display=None,quote_id=qid,
        quoted_line=quote['line'] if quote else None,quoted_odds=quote['odds_american'] if quote else None,
        model_role=role,model_version=model,tier=str(tier),
        model_probability=clean(p),model_probability_provenance='SOURCE_MODEL_OUTPUT' if pd.notna(p) else 'NOT_AVAILABLE',
        expected_value=clean(ev),full_kelly=clean(full),adjusted_kelly=clean(adjusted),
        adjusted_kelly_status='SOURCE_SINGLE_MODEL_DIAGNOSTIC_NOT_JOINT' if pd.notna(adjusted) else 'BLOCKED_OR_NOT_AVAILABLE',
        production_authorized=int(auth),action_status=action,pass_or_block_reason=reason,
        model_health=None,source_file=source,source_sha256=sha(SOURCE/source),source_row_json=row_json))


def side_from(sel,ev,market):
    if market=='Total':return 'Over' if str(sel).lower().startswith('over') else 'Under'
    if str(sel).lower().startswith(str(ev['away']).lower()):return 'Away'
    if str(sel).lower().startswith(str(ev['home']).lower()):return 'Home'
    return None


for folder,role,model in (('R4_champion','CHAMPION','NBA_PREVIOUS_PRODUCTION_R4'),('R3_challenger','CHALLENGER','NBA_R3_SRS_CHALLENGER')):
    src=f'NBA_R4_R3_SCORE/{folder}/forecasts.csv'
    for _,r in pd.read_csv(SOURCE/src).iterrows():
        ev=lookup.get(('NBA',r.Game))
        if ev is None:continue
        side=side_from(r.Selection,ev,r.Market)
        auth=role=='CHAMPION' and r.Tier!='Pass' and pd.notna(r.EV) and r.EV>0
        action=('PRODUCTION_QUALIFIED' if auth else
                'RESEARCH_POSITIVE_EV' if role=='CHALLENGER' and pd.notna(r.EV) and r.EV>0 else 'PASS')
        save_score('NBA',ev['event_id'],r.Market,side,role,model,r.Tier,r.Model_P,r.EV,r.Full_Kelly,
            r.Adjusted_Kelly,auth,action,str(r.Reason),r,src)

src='NCAABB_V4_SCORES.csv'
for _,r in pd.read_csv(SOURCE/src).iterrows():
    evid=str(r.game_id).removeprefix('BOVADA_')
    auth=bool(r.stake_eligible) and pd.notna(r.expected_unit_net_at_quote) and r.expected_unit_net_at_quote>0
    action='PRODUCTION_QUALIFIED' if auth else 'PASS'
    save_score('NCAABB',evid,r.market,r.selected_side,'CHAMPION','NCAABB_V4_THROUGH_2025',
        r.tier,r.selected_probability,r.expected_unit_net_at_quote,r.full_kelly,r.final_recommended_kelly,
        auth,action,f'{r.health}: {r.pricing_status}',r,src)

src='NCAABB_V5_OPPORTUNITIES.csv'
for _,r in pd.read_csv(SOURCE/src).iterrows():
    evid=str(r.game_id).removeprefix('BOVADA_')
    action='RESEARCH_POSITIVE_EV' if pd.notna(r.shadow_ev) and r.shadow_ev>0 else 'PASS'
    save_score('NCAABB',evid,r.market,r.side,'CHALLENGER','NCAABB_V5_SHADOW',
        r.shadow_research_tier,r.shadow_p,r.shadow_ev,r.shadow_full_kelly,None,False,action,
        'Challenger not approved',r,src)

src='NHL_DAY0_ALL_SCORES.csv'
for _,r in pd.read_csv(SOURCE/src).iterrows():
    ev=lookup.get(('NHL',r.game))
    if ev is None:continue
    market={'OU':'Total','ML':'Moneyline','PL':'Spread'}[r.market]
    side=side_from(r.selection,ev,market)
    action='RESEARCH_POSITIVE_EV' if r.display_section=='Research candidate' and pd.notna(r.model_ev) and r.model_ev>0 else 'PASS'
    save_score('NHL',ev['event_id'],market,side,r.model_role,str(r.model),r.tier,
        r.model_p_win,r.model_ev,r.full_kelly_diagnostic,r.adjusted_kelly,False,action,
        str(r.scoring_status),r,src)

stamps=[dt.datetime.fromisoformat(e['quote_captured_utc'].replace('Z','+00:00')) for e in events]
data=dict(batch=dict(batch_id=BATCH,source_name='Nov11 Bovada five sport snapshot: individual event page recovery for CBB/CFB',
    min_quote_utc=iso(min(stamps)),max_quote_utc=iso(max(stamps)),
    quote_skew_seconds=(max(stamps)-min(stamps)).total_seconds(),
    coherent_all_sports=0,cohort_max_seconds=120,source_snapshot_library_id=None,
    ingested_utc=NOW,notes='41 games; four separate capture cohorts. 23 CBB partial book coverage; CFB price-only because latest model not refreshed. Parlays shadow-only.'),
    cohorts=cohorts,events=events,market_quotes=quotes,model_scores=scores,
    source_files=[dict(batch_id=BATCH,source_name=f'{sport}_main_board.csv',file_sha256=sha(SOURCE/f'{sport}_main_board.csv'),source_library_id=None) for sport in boards])
(OUT/'NOV11_CANONICAL_SCORING_IMPORT.json').write_text(json.dumps(data,indent=2,default=str))

# Result evidence is separate from frozen model outputs. Match ESPN teams to
# pre-existing Nov10 Bovada games only when both teams and the Nov10 date agree.
def norm(s):
    s=re.sub(r'\(#[0-9]+\)','',str(s)).lower().replace('&','and')
    return ' '.join(re.findall(r'[a-z0-9]+',s))
def team_sim(a,b):
    x,y=norm(a),norm(b)
    aliases=(('queens nc','queens university'),('central florida','ucf'),
             ('detroit u','detroit mercy'),('nicholls state','nicholls'))
    if any((x.startswith(left) and y.startswith(right)) or (x.startswith(right) and y.startswith(left)) for left,right in aliases):
        return 0.99
    if x==y:return 1.0
    if y.startswith(x+' ') or x.startswith(y+' '):return 0.99
    return difflib.SequenceMatcher(None,x,y).ratio()

prev_sqlite=MASTER/'GAMBLING_ROLLING_SCORING_HISTORY.sqlite'
db=sqlite3.connect(prev_sqlite)
prior=list(db.execute("SELECT DISTINCT game_key,sport,away,home FROM events WHERE game_key LIKE '%:BOVADA:%' AND substr(start_utc,1,10) IN ('2026-11-10','2026-11-11')"))
prevsettled={r[0] for r in db.execute('SELECT game_key FROM settlements')}
results=[];matched=[];ambiguous=[]
for sport in ('NBA','NHL','NCAABB','NCAAFB','NFL'):
    ep=SOURCE/'nov10_results'/f'{sport}_espn_nov10.json'
    d=json.loads(ep.read_text())
    for ev in d.get('events',[]):
        if ev['status']['type']['name']!='STATUS_FINAL':continue
        cp=ev['competitions'][0]['competitors']
        home=next(c for c in cp if c['homeAway']=='home')
        away=next(c for c in cp if c['homeAway']=='away')
        res=dict(sport=sport,espn_game_id=str(ev['id']),game_date='2026-11-10',
            away_id=str(away['team']['id']),home_id=str(home['team']['id']),
            away_team=away['team']['displayName'],home_team=home['team']['displayName'],
            away_score=int(away['score']),home_score=int(home['score']),status='Final',
            observed_utc=NOW,source_file=ep.name)
        results.append(res)
        opts=[]
        for key,s,a,h in prior:
            if s!=sport:continue
            scoresim=(team_sim(a,res['away_team'])+team_sim(h,res['home_team']))/2
            opts.append((scoresim,key,a,h))
        opts.sort(reverse=True)
        if opts and opts[0][0]>=.84 and (len(opts)<2 or opts[0][0]-opts[1][0]>.08):
            matched.append(dict(**res,game_key=opts[0][1],match_score=opts[0][0]))
        else:
            ambiguous.append(dict(**res,nearest=str(opts[:2])))

pd.DataFrame(results).to_csv(OUT/'NOV10_FINAL_RESULTS_ESPN.csv',index=False)
pd.DataFrame(matched).to_csv(OUT/'NOV10_MATCHED_FINALS_FOR_ROLLING_LEDGER.csv',index=False)
pd.DataFrame(ambiguous).to_csv(OUT/'NOV10_UNMATCHED_ESPN_FINALS.csv',index=False)
(OUT/'NOV10_FINALS_MANIFEST.json').write_text(json.dumps(dict(results=len(results),matched_games=len(matched),
    new_matches=sum(x['game_key'] not in prevsettled for x in matched),unmatched=len(ambiguous),
    matches_by_sport={str(k):int(v) for k,v in pd.Series([x['sport'] for x in matched]).value_counts().items()},settlement_authority='ESPN_FINAL_GAME_SCORES_NOT_ACTUAL_BETS'),indent=2))
db.close()
print(json.dumps(dict(batch_id=BATCH,events=len(events),quotes=len(quotes),scores=len(scores),
    quote_cohorts=len(cohorts),result_games=len(results),results_matched=len(matched),
    new_settlements=sum(x['game_key'] not in prevsettled for x in matched),
    unmatched=len(ambiguous)),indent=2))
print('UNMATCHED:')
for x in ambiguous[:12]:print(x['sport'],x['away_team'],'@',x['home_team'],x['nearest'][:110])
