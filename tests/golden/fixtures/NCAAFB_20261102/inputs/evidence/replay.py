import pandas as pd,numpy as np,json,re,unicodedata
from pathlib import Path
root=Path('/workspace/scratch/0c063b32c7d6');out=root/'tmp/closure_oct23'
alias={'appstate':'appalachianstate','uconn':'connecticut','miami':'miamifl','miamiflorida':'miamifl','miamifla':'miamifl','miamioh':'miamioh','miamiohio':'miamioh','pittsburgh':'pitt','centralflorida':'ucf','texaschristian':'tcu','northcarolinastate':'ncstate','ullafayette':'louisiana','louisianalafayette':'louisiana','ulmonroe':'louisianamonroe','nevadalasvegas':'unlv','samhoustonstate':'samhouston','mississippi':'olemiss','alabamabirmingham':'uab','brighamyoung':'byu','southernmiss':'southernmississippi','louisianastate':'lsu','southernmethodist':'smu','southerncalifornia':'usc','texassanantonio':'utsa','texaselpaso':'utep','middletennessee':'middletennesseestate','umass':'massachusetts'}
def norm(x):
 x=re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',str(x)).encode('ascii','ignore').decode().lower());return alias.get(x,x)
def schedule(year):
 p=root/'project_sources/06-cfb_schedules_2023.txt' if year==2023 else out/f'schedule{year}.csv.gz';s=pd.read_csv(p,low_memory=False);s=s[(s.season_type=='regular')&(s.home_division=='fbs')&(s.away_division=='fbs')].copy();s['a']=s.away_team.map(norm);s['h']=s.home_team.map(norm);s['date']=pd.to_datetime(s.start_date,utc=True).dt.tz_convert('America/Chicago').dt.strftime('%Y-%m-%d');return s
master=pd.read_csv(root/'reconciliation_sources/Gambling/NCAAFB_DB_MASTER_2025_COMPLETE_RECONSTRUCTED.csv',low_memory=False);master=master[master.year==2025].copy();master['a']=master.Away.map(norm);master['h']=master.Home.map(norm);master['date']=pd.to_datetime(master.Date,format='mixed',errors='coerce').dt.strftime('%Y-%m-%d');master=master.drop_duplicates(['date','a','h'])
def features(s,year):
 teams=sorted(set(s.a)|set(s.h));ix={t:i for i,t in enumerate(teams)};ratings={}
 maxweek=7 if year==2026 else 13
 for w in range(4,maxweek+1):
  g=s[(s.week<=w)&s.completed];A=[];y=[]
  for r in g.itertuples():
   v=np.zeros(len(teams));v[ix[r.a]]=1;v[ix[r.h]]=-1;A.append(v);y.append(r.away_points-r.home_points+(0 if r.neutral_site else 2.5))
  A.append(np.ones(len(teams)));y.append(0);ratings[w]=np.linalg.lstsq(np.array(A),y,rcond=None)[0]
 late=s[s.week.between(8,14 if year==2025 else 13 if year==2023 else 8)].copy()
 for wk,g in late.groupby('week'):
  slopes=np.array([-1.5,-.5,.5,1.5])@np.array([ratings[w] for w in range(wk-4,wk)])/5
  late.loc[g.index,'SlopeDiff']=[slopes[ix[a]]-slopes[ix[h]] for a,h in zip(g.a,g.h)]
  prior=s[(s.week<wk)&s.completed];pf={};pa={};ng={}
  for r in prior.itertuples():
   for t,pts,allowed in [(r.a,r.away_points,r.home_points),(r.h,r.home_points,r.away_points)]:pf[t]=pf.get(t,0)+pts;pa[t]=pa.get(t,0)+allowed;ng[t]=ng.get(t,0)+1
  for i,r in g.iterrows():late.loc[i,'PFPA_Total']=(pf[r.a]/ng[r.a]+pa[r.h]/ng[r.h]+pf[r.h]/ng[r.h]+pa[r.a]/ng[r.a])/2
 return late
for year in [2023,2025]:
 s=schedule(year);a=features(s,year)
 if year==2023:
  b=pd.read_csv(root/'project_sources/05-betting_2023-1-.csv');a=a.merge(b[['game_id','home_team_spread','over_under']],on='game_id',how='left');a['AwayLine']=-a.home_team_spread;a['MarketTotal']=a.over_under
 else:
  a=a.merge(master[['a','h','date','Away Line','Over Under']],on=['a','h','date'],how='left');a['AwayLine']=a['Away Line'];a['MarketTotal']=a['Over Under']
 for wk in sorted(a.week.unique()):a.loc[a.week==wk,'Z']=a.loc[a.week==wk,'SlopeDiff']/a[a.week<=wk].SlopeDiff.std(ddof=1)
 a['SpreadSelected']=(a.Z.abs()>=1.243)&(a.SlopeDiff*a.AwayLine>0);a['SpreadCover']=(a.away_points-a.home_points+a.AwayLine)*np.sign(a.SlopeDiff);a['SpreadGrade']=np.where(a.SpreadCover>0,'W',np.where(a.SpreadCover<0,'L','P'))
 a['TotalGap']=a.PFPA_Total-a.MarketTotal;a['TotalSelected']=a.TotalGap.abs()>=5;a['TotalCover']=(a.away_points+a.home_points-a.MarketTotal)*np.sign(a.TotalGap);a['TotalGrade']=np.where(a.TotalCover>0,'W',np.where(a.TotalCover<0,'L','P'))
 a.to_csv(out/f'consistent{year}.csv',index=False);print(year,'regular',len(s),'late',len(a),'market spread',a.AwayLine.notna().sum(),'market total',a.MarketTotal.notna().sum(),'spread',a[a.SpreadSelected].SpreadGrade.value_counts().to_dict(),'totals',a[a.TotalSelected].TotalGrade.value_counts().to_dict(),flush=True)
 if year==2025:print('missingmarkets',a[a.AwayLine.isna()][['date','away_team','home_team']].to_string(index=False),flush=True)
