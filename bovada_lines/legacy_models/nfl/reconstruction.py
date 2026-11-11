import numpy as np
import pandas as pd
from core import build_ratings
ASOF='2026-10-27'
SAVED_SLOPES={}
def ols_slope(values,weeks):
    x=np.asarray(weeks,float);y=np.asarray(values,float)
    if len(x)!=4 or not np.isfinite(y).all():return np.nan
    x=x-x.mean();return float(x@y/(x@x))

def snapshot(games,season,through):
    # Delayed nominal prior-week games must also have occurred before next week.
    nextweek=games[(games.season==season)&(games.week==through+1)]
    cutoff=nextweek.gameday.min() if len(nextweek) else ASOF
    g=games[(games.season==season)&(games.week<=through)&(games.gameday<cutoff)]
    if not len(g):return {}
    ratings,connected=build_ratings(g)
    a=g[['away_team','away_score','home_score']].copy();a.columns=['team','pf','pa']
    h=g[['home_team','home_score','away_score']].copy();h.columns=a.columns
    v=pd.concat([a,h]).groupby('team')[['pf','pa']].mean()
    return {t:dict(srs=float(ratings[t]),off=float(v.loc[t,'pf']),defense=float(v.loc[t,'pa']),margin=float(v.loc[t,'pf']-v.loc[t,'pa']),connected=connected) for t in ratings}

def team_features(games,season,week,cache):
    out={};weeks=list(range(week-4,week))
    for w in weeks:
        if (season,w) not in cache:cache[season,w]=snapshot(games,season,w)
    last=cache[season,week-1]
    for team,vals in last.items():
        d=dict(vals)
        for key in ['srs','off','defense','margin']:
            values=[cache[season,w].get(team,{}).get(key,np.nan) for w in weeks]
            d[key+'_slope']=float(values[-1]-values[0]) if np.isfinite(values).all() else np.nan
        d['reconstructed_srs_slope']=d['srs_slope']
        stored=SAVED_SLOPES.get((int(season),int(week),team))
        d['slope_source']='stored historical' if stored is not None else 'rebuilt four-snapshot endpoint change'
        if stored is not None:d['srs_slope']=stored
        d.update(team=team,season=season,scoring_week=week,snapshot_weeks=','.join(map(str,weeks)),through_week=week-1)
        out[team]=d
    return out