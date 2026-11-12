"""One release entry point. score --quotes JSON --out NEW_DIR [--history CSV]
settle --forecast CSV --outcomes CSV --output NEW_CSV
"""
from pathlib import Path
import argparse,csv,json,hashlib,runpy,datetime,os,shutil,tempfile
import pandas as pd,numpy as np
from portfolio_kelly import full_kelly,portfolio_kelly
from dependence import scenarios
R=Path(__file__).resolve().parent

def verify():
 for name,digest in json.load(open(R/'RELEASE_HASHES.json')).items():
  if hashlib.sha256((R/name).read_bytes()).hexdigest()!=digest:raise ValueError('Release integrity mismatch: '+name)

def score(quotes,out,history=None):
 verify();policy=json.load(open(R/'ACTIVE_RELEASE.json'));C=json.load(open(R/'data/v27_coefficients.json'));dep=json.load(open(R/'DEPENDENCE_MODEL.json'));Q=json.load(open(quotes));out=Path(out)
 if out.exists():raise FileExistsError('Output already exists; preserve prior forecast')
 if not Q or any(len(q)!=12 for q in Q):raise ValueError('Quotes must have twelve fields per game')
 if len({(q[0],q[2],q[3]) for q in Q})!=len(Q):raise ValueError('Duplicate games')
 if len({q[0] for q in Q})!=1:raise ValueError('One slate date per invocation')
 cutoff=Q[0][0];datetime.date.fromisoformat(cutoff)
 for q in Q:
  if q[2]==q[3] or any(not np.isfinite(float(v)) for v in q[4:]) or any(float(q[i])==0 for i in [5,6,7,8,10,11]):raise ValueError('Invalid quote')
 H=Path(history) if history else R/'data/history.csv';hist=list(csv.DictReader(open(H)));dates=[g['date'] for g in hist]
 if not hist or max(dates)>=cutoff:raise ValueError('History includes forecast date or future results')
 if (datetime.date.fromisoformat(cutoff)-datetime.date.fromisoformat(max(dates))).days>7:raise ValueError('Stale history: append completed results')
 if len({g['game_key'] for g in hist})!=len(hist):raise ValueError('Duplicate history')
 known={g['home'] for g in hist}|{g['away'] for g in hist}
 if any(q[2] not in known or q[3] not in known for q in Q):raise ValueError('Unknown team')
 corrections=pd.read_csv(R/'data/previous_historical_master.csv').set_index('Game_Key')
 for g in hist:
  datetime.date.fromisoformat(g['date'])
  if g['game_key'] in corrections.index:
   c=corrections.loc[g['game_key']];g['home_score']=str(c.Resolved_Home_Score);g['away_score']=str(c.Resolved_Away_Score)
  if not all(np.isfinite(float(g[k])) and float(g[k])>=0 for k in ['home_score','away_score']):raise ValueError('Invalid final scores')
 hist.sort(key=lambda g:(g['date'],g['game_key']))
 out.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=out.parent) as temp:
  T=Path(temp);ns=runpy.run_path(str(R/'scoring_core.py'),init_globals=dict(BASE=T,hist=hist,C=C,QUOTES=Q,POLICY=policy));d=pd.DataFrame(ns['market_rows']);d['Release']=policy['revision'];d['Frozen_UTC']=datetime.datetime.now(datetime.timezone.utc).isoformat();d['Full_Kelly']=0.;d['Adjusted_Kelly']=0.;d['Sizing_Status']='PASS';d['Adjusted_Kelly_Status']='SHADOW_CONDITIONAL_DEPENDENCE_MODEL';d['Result']='PENDING'
  eligible=d.Tier.isin(['B','B+'])&d.Model_P.notna()
  for i,row in d[eligible].iterrows():
   b=row.Odds/100 if row.Odds>0 else 100/-row.Odds;d.loc[i,'Full_Kelly']=float(full_kelly(row.Model_P,b));d.loc[i,'Sizing_Status']='QUALIFIED_POSITIVE_EV' if d.loc[i,'Full_Kelly']>0 else 'NO_POSITIVE_EV'
  active=d[eligible&(d.Full_Kelly>0)].copy()
  if len(active):
   try:
    if (active.Market=='Total').any():raise ValueError('Joint ML/spread/total distribution not implemented; portfolio sizing unavailable')
    A,w=scenarios(active,dep['integer_spread_push_rate']);result=portfolio_kelly(A,w);d.loc[active.index,'Adjusted_Kelly']=result['adjusted_kelly'];json.dump(result,open(T/'portfolio.json','w'),indent=2)
   except ValueError as error:
    d.loc[active.index,'Adjusted_Kelly']=np.nan;d.loc[active.index,'Adjusted_Kelly_Status']='UNAVAILABLE: '+str(error)
  d.to_csv(T/'forecasts.csv',index=False)
  json.dump({'release':policy['revision'],'history_sha256':hashlib.sha256(H.read_bytes()).hexdigest(),'history_last':max(dates),'quotes_sha256':hashlib.sha256(Path(quotes).read_bytes()).hexdigest(),'rows':len(d),'joint_model_status':dep['operational_status'],'known_quote_limitations':'ACCEPTED'},open(T/'run_manifest.json','w'),indent=2)
  shutil.copytree(T,out)
 json.dump({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()},open(out/'OUTPUT_HASHES.json','w'),indent=2)
 return d

def settle(forecast,outcomes,output):
 if Path(output).exists():raise FileExistsError('Settlement exists')
 d=pd.read_csv(forecast);o=pd.read_csv(outcomes);keys=['Date','Game','Market']
 if o.duplicated(keys).any() or not o.Result.isin(['WIN','LOSS','PUSH']).all():raise ValueError('Invalid outcomes')
 # Pending forecast results remain untouched; settlement is a separate column/file.
 o=o.rename(columns={'Result':'Settled_Result'});r=d.merge(o[keys+['Settled_Result']],on=keys,how='left',validate='one_to_one');r.to_csv(output,index=False);return r
if __name__=='__main__':
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True);s=sub.add_parser('score');s.add_argument('--quotes',required=True);s.add_argument('--out',required=True);s.add_argument('--history');s=sub.add_parser('settle');s.add_argument('--forecast',required=True);s.add_argument('--outcomes',required=True);s.add_argument('--output',required=True);a=p.parse_args();values=vars(a);cmd=values.pop('command');score(**{'quotes':a.quotes,'out':a.out,'history':a.history}) if cmd=='score' else settle(a.forecast,a.outcomes,a.output)
