from pathlib import Path
import pandas as pd,numpy as np,json,re,unicodedata
from scipy.special import expit,logit
R=Path(__file__).resolve().parent;O=R/'results';O.mkdir(exist_ok=True)
code=(R/'inputs/evidence/replay.py').read_text();exec(code[code.index('alias='):code.index('def schedule')]);base_norm=norm
def norm(x):return base_norm(re.sub(r'\(#[0-9]+\)','',str(x)))
q=pd.read_csv(R/'inputs/quoted_lines.csv');q['a']=q.Away.map(norm);q['h']=q.Home.map(norm)
f=pd.read_csv(O/'features_weeks8_10.csv');f=f[f.week==10];board=q.merge(f[['game_id','a','h','SlopeDiff','Z','PFPA_Total']],on=['a','h'],validate='one_to_one');assert len(board)==62
A=R/'inputs/authority.json';authority=json.loads(A.read_text());cal={c['Group']:c['ModelP'] for c in authority['Calibration']}
post=pd.read_csv(R/'inputs/posterior_quadrature.csv');assert abs(post.PosteriorWeight.sum()-1)<1e-10
# Current published gate values. UAB is intentionally unresolved: only stale 4-3 primary pages were recoverable.
srs={'ohio':(.19,'https://www.sports-reference.com/cfb/schools/ohio/'),'baylor':(10.06,'https://www.sports-reference.com/cfb/schools/baylor/2026-schedule.html'),'auburn':(9.04,'https://www.sports-reference.com/cfb/schools/auburn/2026-schedule.html'),'georgiasouthern':(-.10,'https://www.sports-reference.com/cfb/schools/georgia-southern/2026-schedule.html'),'sanjosestate':(-7.36,'https://www.sports-reference.com/cfb/schools/san-jose-state/2026-schedule.html'),'hawaii':(-11.14,'https://www.sports-reference.com/cfb/conferences/mwc/2026-ratings.html')}
pd.DataFrame([dict(Team=t,SRS=v[0],SourceURL=v[1],GateStatus='Current indexed published source') for t,v in srs.items()]).to_csv(O/'published_srs_gates.csv',index=False)
def odds(o):return 100. if o=='EVEN' else float(o)
def pay(o):return 100/-o if o<0 else o/100
def imp(o):return -o/(100-o) if o<0 else 100/(100+o)
def metrics(p,o):
 ev=p*(1+pay(o))-1;return ev,max(0,ev/pay(o))
def fill(row,p,o,prefix,tier):
 ev,k=metrics(p,o);row.update({prefix+'P':p,prefix+'EV':ev,prefix+'FullKelly':k,prefix+'Tier':tier if ev>0 or tier=='B descriptive' else 'Pass'})
rows=[]
for r in board.itertuples():
 base=dict(EventID=r.EventID,GameID=r.game_id,KickoffCT=r.KickoffCT,Away=r.Away,Home=r.Home,CapturedUTC=r.CapturedUTC,FeatureCutoff='Completed FBS-v-FBS regular-season games through Week9 / Oct31',ChampionTier='Pass',ChallengerTier='Pass',ChampionP=np.nan,ChallengerP=np.nan,ChampionEV=np.nan,ChallengerEV=np.nan,ChampionFullKelly=np.nan,ChallengerFullKelly=np.nan,ChampionAdjustedKelly=np.nan,ChallengerAdjustedKelly=np.nan,AdditionalStakeUSD=np.nan,SizingStatus='Joint sizing not run; current exposure not reconciled')
 away=r.SlopeDiff>0;sel=r.Away if away else r.Home;line=float(r.AwaySpread if away else r.HomeSpread);o=odds(r.AwaySpreadOdds if away else r.HomeSpreadOdds);z=abs(r.Z);eligible=line>0 and z>=1.243;group='Strong' if z>=1.75 else 'Moderate';tier='B+ provisional' if group=='Strong' else 'B provisional'
 row=dict(**base,Market='Spread',Selection=sel,Line=line,Odds=o,Z=r.Z,SignalGroup=group if eligible else '',Reason='Higher-slope team favored' if line<=0 else 'Below |Z|1.243' if z<1.243 else 'Signal qualified; price EV determines tier',ChampionModel=authority['ModelVersion'],ChallengerModel='FROZEN-CONTINUOUS-v1-20261023',ProbabilityBasis='Conditional on decisive settlement; integer-line push probability unestimated')
 if eligible:
  p=cal[group];pc=float(post.PosteriorWeight@expit(post.Intercept+post.Slope*(z-1.243)));fill(row,p,o,'Champion',tier);fill(row,pc,o,'Challenger',tier)
 rows.append(row)
 ao=odds(r.AwayML);ho=odds(r.HomeML);away=ao>ho;dog=r.Away if away else r.Home;fav=r.Home if away else r.Away;do=max(ao,ho);fo=min(ao,ho);gate=250<=do<=400 and 45<=r.Total<=55
 row=dict(**base,Market='ML',Selection=dog,Line=np.nan,Odds=do,Favorite=fav,MarketTotal=r.Total,Reason='Outside dog+250..400 / total45..55 regime',ChampionModel='EXISTING-W8PLUS-ML-UNCHANGED',ChallengerModel='SHARED-ML-COMPONENT; no distinct ML challenger adopted',ProbabilityBasis='No-vig anchor plus fixed0.10 log-odds when favorite publishedSRS<10')
 if gate:
  anchor=imp(do)/(imp(do)+imp(fo));sv=srs.get(norm(fav));row['NoVigP']=anchor
  if sv is None:
   row.update(ChampionTier='Unscored: SRS gate',ChallengerTier='Unscored: SRS gate',Reason='Current published UAB SRS not recovered; stale 4-3 source not substituted')
   hypothetical=float(expit(logit(anchor)+.1));row['ConditionalIfFavoriteSRSBelow10P']=hypothetical;row['ConditionalIfFavoriteSRSBelow10EV']=metrics(hypothetical,do)[0]
  else:
   row.update(FavoritePublishedSRS=sv[0],SRSSourceURL=sv[1]);tier='A existing' if sv[0]<10 else 'B descriptive';p=float(expit(logit(anchor)+.1)) if sv[0]<10 else anchor
   fill(row,p,do,'Champion',tier);fill(row,p,do,'Challenger',tier);row['Reason']='Shared unchanged ML rule; '+('favorite publishedSRS<10' if sv[0]<10 else 'favorite publishedSRS>=10; descriptive only')
   if tier=='B descriptive':row['ChampionFullKelly']=row['ChallengerFullKelly']=0.
 rows.append(row)
 gap=r.PFPA_Total-r.Total;o=odds(r.UnderOdds);under=gap<=-5
 row=dict(**base,Market='Total',Selection='Under' if under else '',Line=r.Total,Odds=o if under else np.nan,PFPA=r.PFPA_Total,PFPA_Gap=gap,Reason='PFPA Under research only; zero normal allocation' if under else 'No supported PFPA Under research signal',ChampionModel='EXISTING-OU-RESEARCH-UNCHANGED',ChallengerModel='SHARED-OU-RESEARCH; no distinct current total challenger adopted',ProbabilityBasis='Existing research54/99; not validated production probability')
 if under:
  for prefix in ['Champion','Challenger']:fill(row,54/99,o,prefix,'Lean');row[prefix+'AdjustedKelly']=0.
 rows.append(row)
out=pd.DataFrame(rows).sort_values(['KickoffCT','Away','Market']).reset_index(drop=True);assert len(out)==186
out.to_csv(O/'ALL_62_GAMES_BOTH_MODEL_TIERS.csv',index=False)
pos=out[(out.ChampionEV>0)|(out.ChallengerEV>0)].copy();pos.to_csv(O/'POSITIVE_EV_BOTH_MODEL_TIERS.csv',index=False)
board.to_csv(O/'CURRENT_PRICED_FEATURES.csv',index=False)
print(pos[['KickoffCT','Market','Selection','Line','Odds','Z','ChampionTier','ChampionP','ChampionEV','ChampionFullKelly','ChallengerTier','ChallengerP','ChallengerEV','ChallengerFullKelly']].to_string(index=False))
print('COUNTS',out.groupby(['Market','ChampionTier','ChallengerTier']).size().to_dict());print('SIGNALS',out[(out.Market=='Spread')&out.ChampionP.notna()][['Selection','Line','Odds','Z']].to_dict('records'))
