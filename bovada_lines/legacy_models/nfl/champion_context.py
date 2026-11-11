import pandas as pd
import numpy as np
from core import build_ratings,payout
def early_population(raw):
 out=[]
 for season in range(2013,2026):
  prior=raw[(raw.season==season-1)&raw.away_score.notna()&raw.home_score.notna()]
  ratings,_=build_ratings(prior)
  l=pd.concat([prior[['away_team','away_score']].rename(columns={'away_team':'team','away_score':'pf'}),prior[['home_team','home_score']].rename(columns={'home_team':'team','home_score':'pf'})]);ppg=l.groupby('team').pf.mean()
  for r in raw[(raw.season==season)&raw.week.le(7)].itertuples():
   if not np.isfinite([r.spread_line,r.total_line,r.away_score,r.home_score]).all():continue
   a,h=r.away_team,r.home_team;diff=ratings[h]-ratings[a]+1.5-r.spread_line;home=diff>=0;da=r.away_moneyline>0
   specs=[]
   if 5<=abs(diff)<7:specs.append(('Spread',h if home else a,r.home_spread_odds if home else r.away_spread_odds,(r.home_score-r.away_score-r.spread_line)*(1 if home else -1),np.nan))
   dogprice=r.away_moneyline if da else r.home_moneyline;other=r.home_moneyline if da else r.away_moneyline;reverse=-diff if da else diff
   if 250<=dogprice<400 and reverse< -5 and np.isfinite(other) and abs(other)>=100:
    x=1/(1+payout(dogprice));y=1/(1+payout(other));specs.append(('Moneyline',a if da else h,dogprice,(r.away_score-r.home_score)*(1 if da else -1),x/(x+y)))
   gap=r.total_line-ppg[a]-ppg[h]
   if 4<=gap<12:specs.append(('Total','Under',r.under_odds,r.total_line-r.away_score-r.home_score,np.nan))
   for market,selection,odds,value,anchor in specs:
    if not np.isfinite(odds) or abs(odds)<100:continue
    out.append(dict(game_id=r.game_id,season=season,week=r.week,market=market,selection=selection,odds=odds,y=1 if value>0 else 0 if value<0 else np.nan,result='W' if value>0 else 'L' if value<0 else 'P',market_novig_dog=anchor,regime='W1-7'))
 return pd.DataFrame(out)