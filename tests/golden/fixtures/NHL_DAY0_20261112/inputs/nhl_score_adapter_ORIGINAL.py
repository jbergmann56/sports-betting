"""Frozen NHL Day-0 research scorer. Probability parity is checked with archived Nov7 run.

This scorer deliberately never authorizes any wager. Official control file is frozen
through 2025; V15 and PL challenger missing features remain unscored.
"""
import csv, hashlib, math
from pathlib import Path
from collections import defaultdict
from models.nhl_day0 import day0_production as model

BASE=Path(__file__).resolve().parent / 'models' / 'nhl_day0'
CONTROLS=BASE/'OBSERVED_PRICE_ALL_CONTROLS.csv'
CONTROL_SHA=hashlib.sha256(CONTROLS.read_bytes()).hexdigest()
PARAMS=model.historical_segments(CONTROLS)

def score(quotes):
    if isinstance(quotes,str):
        with open(quotes,newline='') as f: quotes=list(csv.DictReader(f))
    grouped=defaultdict(dict)
    for q in quotes:
        if q['sport']=='NHL':
            grouped[q['event_id']][(q['market'],q['side'])]=q
    games=[]; incomplete=[]
    for eid,qs in grouped.items():
        if len(qs)!=6 or any(q['quote_status']!='OFFERED_PREGAME' for q in qs.values()):
            incomplete.append(eid); continue
        def row(m,s):
            q=qs[m,s];return float(q['odds_american']),float(q['line']) if q['line'] else None
        try:
            away_ml,_=row('Moneyline','Away');home_ml,_=row('Moneyline','Home')
            away_sp,away_line=row('Spread','Away');home_sp,home_line=row('Spread','Home')
            over,over_line=row('Total','Over');under,under_line=row('Total','Under')
            assert abs(away_line+home_line)<1e-10 and abs(over_line-under_line)<1e-10
            q=qs['Moneyline','Away'];away,home=q['description'].split(' @ ')
            assert all(q['start_utc']>x['snapshot_as_of_utc'] for x in qs.values()),'quote after start'
            games.append(dict(game_id=eid,start_utc=q['start_utc'],away=away,home=home,
               quote_away=dict(ml_price=away_ml,pl_price=away_sp,pl_line=away_line,total_price=over,total_line=over_line),
               quote_home=dict(ml_price=home_ml,pl_price=home_sp,pl_line=home_line,total_price=under,total_line=under_line)))
        except (KeyError,ValueError,AssertionError) as ex:incomplete.append(eid)
    scored, audits=model.score_games(games,PARAMS)
    if any(abs(x[k])>1e-10 for x in audits for k in ('ml_complement_residual','pl_complement_residual','total_probability_residual')) or not all(x['favorite_margin_constraint'] for x in audits):
        raise ValueError('NHL coherence audit failed')
    lookup={(x['event_id'],x['market'],x['side']):x for items in grouped.values() for x in items.values()}
    out=[]
    for r in scored:
        market={'ML':'Moneyline','PL':'Spread','OU':'Total'}[r['market']]
        side=('Over' if r['selection']=='Over' else 'Under') if market=='Total' else ('Away' if r['selection'].startswith(r['game'].split(' @ ')[0]) else 'Home')
        q=lookup[r['game_id'],market,side]
        p=r['model_p_win'];ev=r['model_ev'];role=r['model_role']
        if p is None:status='UNSCORED';tier='Unscored'
        elif role=='CHAMPION' and ev>0:status='RESEARCH_POSITIVE_EV';tier='Lean'
        else:status='PASS';tier='Pass'
        out.append(dict(sport='NHL',event_id=r['game_id'],start_utc=r['start_utc'],game=r['game'],market=market,
            selection=r['selection'],side=side,line=r['line'],odds=r['american_odds'],quote_status=q['quote_status'],
            model_role=role,model_version=r['model'],model_p=p,ev=ev,full_kelly=r['full_kelly_diagnostic'],
            adjusted_kelly=None,tier=tier,status=status,
            reason=r['research_status']+'; NHL research only / no production authorization',
            quote_timestamp=q['snapshot_as_of_utc'],feature_cutoff='2025-12-31',
            feature_source='NHL_DAY0/OBSERVED_PRICE_ALL_CONTROLS.csv sha256='+CONTROL_SHA))
    return out,incomplete,audits
