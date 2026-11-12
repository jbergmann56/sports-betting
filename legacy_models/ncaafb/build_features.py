from pathlib import Path
import pandas as pd,numpy as np,json,re,unicodedata
R=Path(__file__).resolve().parent;O=R/'results';O.mkdir(exist_ok=True)
E=R/'inputs/evidence'
text=(E/'replay.py').read_text();exec(text[text.index('alias='):text.index('def schedule')])
base_norm=norm
def norm(x):return base_norm(re.sub(r'\(#[0-9]+\)','',str(x)))
s=pd.read_csv(E/'schedule2026.csv.gz',low_memory=False);s=s[(s.season_type=='regular')&(s.home_division=='fbs')&(s.away_division=='fbs')].copy();s['a']=s.away_team.map(norm);s['h']=s.home_team.map(norm)
updates=[]
for fn in [R/'inputs/finals_week8.csv',R/'inputs/finals_week9.csv']:
 d=pd.read_csv(fn)
 for r in d.itertuples():
  g=s[(s.a==norm(r.Away))&(s.h==norm(r.Home))]
  if len(g)!=1:raise RuntimeError(('unmatched result',r.Away,r.Home,len(g)))
  i=g.index[0];s.loc[i,['away_points','home_points','completed']]=[r.AwayScore,r.HomeScore,True];updates.append(dict(GameID=s.loc[i,'game_id'],Away=r.Away,Home=r.Home,Week=s.loc[i,'week'],Source=str(fn),AwayScore=r.AwayScore,HomeScore=r.HomeScore))
p=O/'oct27_scoreboard.json'
if p.exists():
 for e in json.loads(p.read_text()).get('events',[]):
  c=e['competitions'][0];cs=c['competitors'];a=next(x for x in cs if x['homeAway']=='away');h=next(x for x in cs if x['homeAway']=='home')
  if not c['status']['type']['completed']:continue
  g=s[(s.a==norm(a['team']['displayName']))&(s.h==norm(h['team']['displayName']))]
  if len(g)!=1:
   # ESPN long display names differ; authoritative numeric game ID first.
   g=s[s.game_id==int(e['id'])]
  if len(g)!=1:continue
  s.loc[g.index[0],['away_points','home_points','completed']]=[float(a['score']),float(h['score']),True];updates.append(dict(GameID=e['id'],Away=a['team']['displayName'],Home=h['team']['displayName'],Week=int(g.iloc[0].week),Source='ESPN scoreboard 20261027',AwayScore=a['score'],HomeScore=h['score']))
s['away_points']=pd.to_numeric(s.away_points);s['home_points']=pd.to_numeric(s.home_points)
missing=s[(s.week<=9)&~s.completed];print('MISSING RESULTS',missing[['week','away_team','home_team']].to_dict('records'))
pd.DataFrame(updates).to_csv(O/'result_update_provenance.csv',index=False)
s.to_csv(O/'updated_schedule2026.csv',index=False)
teams=sorted(set(s.a)|set(s.h));ix={t:i for i,t in enumerate(teams)};ratings={};ratingrows=[]
for w in range(4,10):
 g=s[(s.week<=w)&s.completed];A=[];y=[]
 for r in g.itertuples():
  v=np.zeros(len(teams));v[ix[r.a]]=1;v[ix[r.h]]=-1;A.append(v);y.append(r.away_points-r.home_points+(0 if r.neutral_site else 2.5))
 A.append(np.ones(len(teams)));y.append(0);ratings[w]=np.linalg.lstsq(np.array(A),y,rcond=None)[0]
 for t in teams:ratingrows.append(dict(Week=w,Team=t,SRS=ratings[w][ix[t]]))
late=s[s.week.between(8,10)].copy()
for wk,g in late.groupby('week'):
 slopes=np.array([-1.5,-.5,.5,1.5])@np.array([ratings[w] for w in range(wk-4,wk)])/5
 late.loc[g.index,'SlopeDiff']=[slopes[ix[a]]-slopes[ix[h]] for a,h in zip(g.a,g.h)]
 prior=s[(s.week<wk)&s.completed];pf={};pa={};ng={}
 for r in prior.itertuples():
  for t,pts,allowed in [(r.a,r.away_points,r.home_points),(r.h,r.home_points,r.away_points)]:pf[t]=pf.get(t,0)+pts;pa[t]=pa.get(t,0)+allowed;ng[t]=ng.get(t,0)+1
 for i,r in g.iterrows():late.loc[i,'PFPA_Total']=(pf[r.a]/ng[r.a]+pa[r.h]/ng[r.h]+pf[r.h]/ng[r.h]+pa[r.a]/ng[r.a])/2
for wk in [8,9,10]:late.loc[late.week==wk,'Z']=late.loc[late.week==wk,'SlopeDiff']/late[late.week<=wk].SlopeDiff.std(ddof=1)
late.to_csv(O/'features_weeks8_10.csv',index=False);pd.DataFrame(ratingrows).to_csv(O/'weekly_ratings.csv',index=False)
old=pd.read_csv(R/'inputs/prior_features.csv');v=old[['game_id','SlopeDiff','Z']].merge(late[late.week==9][['game_id','SlopeDiff','Z']],on='game_id',suffixes=('_frozen','_reconstructed'))
v['SlopeError']=v.SlopeDiff_reconstructed-v.SlopeDiff_frozen;v['ZError']=v.Z_reconstructed-v.Z_frozen;v.to_csv(O/'feature_parity.csv',index=False)
print('PARITY',len(v),'maxSlopeError',v.SlopeError.abs().max(),'maxZError',v.ZError.abs().max(),'frozenSTD',(v.SlopeDiff_frozen/v.Z_frozen).median(),'newSTD',(v.SlopeDiff_reconstructed/v.Z_reconstructed).median())
print('TARGET WEEK10',len(late[late.week==10]))
