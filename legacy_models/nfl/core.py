"""Auditable NFL REV1 primitives. No outcome-dependent selection or automatic promotions."""
import math
import numpy as np
import pandas as pd
from scipy.optimize import minimize

VERSION='REV1-audited-tools-2026-10-24'
PROBS={'Spread':.545903045903,'Moneyline':.33223684210526316,'Total':.564274536105522}

def payout(odds):
    if not np.isfinite(odds) or abs(odds)<100: raise ValueError('American odds must be <=-100 or >=100')
    return 100/-odds if odds<0 else odds/100

def kelly(p,odds):
    if not 0<=p<=1: raise ValueError('Probability outside [0,1]')
    return max(0.,p-(1-p)/payout(odds))

def score(away,home,line,away_odds,home_odds,away_ml,home_ml,total,over_odds,under_odds,asrs,hsrs,appg,hppg,week=7,hfa=1.5):
    nums=[line,away_odds,home_odds,away_ml,home_ml,total,over_odds,under_odds,asrs,hsrs,appg,hppg]
    if not all(np.isfinite(x) for x in nums): raise ValueError('Missing/nonfinite scoring input')
    m=hsrs-asrs+hfa; d=m-line; modeltotal=appg+hppg; edge=total-modeltotal
    side=away if d<0 else home; sel_line=line if d<0 else -line
    tier='A' if 5<=abs(d)<7 else 'Lean' if abs(d)>=4 else 'Pass'
    spread=dict(market='Spread',selection=side,line=sel_line,odds=away_odds if d<0 else home_odds,tier=tier,signal=d,model_projection=m)
    da=away_ml>0; dog=away if da else home; dogprice=away_ml if da else home_ml
    reverse=-d if da else d
    # REV1 contrarian dog regime: SRS >5 points more pessimistic than the market.
    mtier='A' if 250<=dogprice<400 and reverse< -5 else 'Lean' if dogprice>0 and reverse< -5 else 'Pass'
    ml=dict(market='Moneyline',selection=dog,line=None,odds=dogprice,tier=mtier,signal=reverse,model_projection=m)
    utier=('A' if week<=7 else 'B+') if 4<=edge<12 else 'Lean' if abs(edge)>=4 else 'Pass'
    ou=dict(market='Total',selection='Under' if edge>=0 else 'Over',line=total,odds=under_odds if edge>=0 else over_odds,tier=utier,signal=edge,model_projection=modeltotal)
    ans=[]
    for r in [spread,ml,ou]:
        p=PROBS[r['market']] if r['tier']=='A' else None
        r.update(away=away,home=home,week=week,model_p=p,break_even=1/(1+payout(r['odds'])),full_kelly=kelly(p,r['odds']) if p is not None else None,
                 adjusted_kelly=None,recommended_kelly=None,sizing_status='Joint scenarios / existing exposure required',model_version=VERSION)
        r['ev']=p*payout(r['odds'])-(1-p) if p is not None else None
        ans.append(r)
    return ans

def ats_result(away_score,home_score,away_line,selected_away):
    v=away_score-home_score+away_line
    if not selected_away: v=-v
    return 'W' if v>0 else 'L' if v<0 else 'P'

def build_ratings(games):
    """SRS: least-squares margin vs opponent; sum-zero. Report disconnected components."""
    teams=sorted(set(games.away_team)|set(games.home_team)); ix={t:i for i,t in enumerate(teams)}
    x=np.zeros((len(games)+1,len(teams))); y=np.zeros(len(games)+1)
    for k,r in enumerate(games.itertuples()):
        x[k,ix[r.away_team]]=1;x[k,ix[r.home_team]]=-1;y[k]=r.away_score-r.home_score
    x[-1,:]=1
    vals=np.linalg.lstsq(x,y,rcond=None)[0]; rank=np.linalg.matrix_rank(x)
    return dict(zip(teams,vals)),rank==len(teams)

def pregame_features(games,season,week):
    # Strict season/week cutoff excludes the scoring week, even if result data is present.
    prior=games[(games.season==season-1)&games.away_score.notna()&games.home_score.notna()]
    current=games[(games.season==season)&(games.week<week)&games.away_score.notna()&games.home_score.notna()]
    used=prior if week<=7 else current
    if used.empty: raise ValueError('No completed games available before cutoff')
    srs,connected=build_ratings(used)
    long=pd.concat([used[['away_team','away_score']].rename(columns={'away_team':'team','away_score':'pf'}),used[['home_team','home_score']].rename(columns={'home_team':'team','home_score':'pf'})])
    ppg=long.groupby('team').pf.mean().to_dict()
    return srs,ppg,dict(input_season=season-1 if week<=7 else season,through_week=int(used.week.max()),games=len(used),connected=connected,method='prior final' if week<=7 else 'current through previous week')

def joint_kelly(probabilities,returns,existing_returns=None,max_committed=1.-1e-8):
    """Exact finite-scenario expected-log optimizer. Returns are net $ per $ staked.

    Probabilities must already integrate posterior predictive uncertainty. No extra N haircut.
    existing_returns are net returns as fraction of the same starting bankroll in each scenario.
    max_committed is remaining bankroll funding, not an arbitrary model risk cap.
    """
    p=np.asarray(probabilities,float);R=np.asarray(returns,float)
    if R.ndim!=2 or len(p)!=len(R) or np.any(p<0) or not np.isclose(p.sum(),1): raise ValueError('Invalid scenario distribution')
    if not np.isfinite(R).all():raise ValueError('Nonfinite scenario return')
    e=np.zeros(len(p)) if existing_returns is None else np.asarray(existing_returns,float)
    if e.shape!=p.shape or np.any(1+e<=0):raise ValueError('Invalid existing positions')
    if not 0<=max_committed<1:raise ValueError('Remaining funding fraction must be in [0,1)')
    def objective(f):
        w=1+e+R@f
        if np.any(w<=0):return 1e12
        return -np.dot(p,np.log(w))
    constraints=[{'type':'ineq','fun':lambda f:max_committed-f.sum()}, {'type':'ineq','fun':lambda f:1+e+R@f-1e-10}]
    res=minimize(objective,np.zeros(R.shape[1]),bounds=[(0,max_committed)]*R.shape[1],constraints=constraints,method='SLSQP',options={'ftol':1e-12,'maxiter':2000})
    if not res.success:raise RuntimeError(res.message)
    return {'fractions':res.x.tolist(),'expected_log_growth':-res.fun,'min_bankroll_multiple':float((1+e+R@res.x).min()),'solver_success':True}

def mutually_exclusive_pair(p1,p2,odds1,odds2):
    if p1<0 or p2<0 or p1+p2>1:raise ValueError('Incoherent mutually exclusive probabilities')
    return np.array([p1,p2,1-p1-p2]),np.array([[payout(odds1),-1],[-1,payout(odds2)],[-1,-1]])

def posterior_scenarios(probability_draws,odds,weights=None,conditional_independence=False):
    """Integrate shared posterior draws before optimizing, preserving induced dependence.

    Call only when conditional independence given the draws is defensible. Same-game
    mutually exclusive outcomes require a constrained joint model instead.
    """
    import itertools
    if not conditional_independence:raise ValueError('Must explicitly justify conditional independence')
    p=np.asarray(probability_draws,float)
    if p.ndim!=2 or p.shape[1]!=len(odds) or not 1<=p.shape[1]<=16 or np.any((p<0)|(p>1)):raise ValueError('Invalid probability draws')
    w=np.ones(len(p))/len(p) if weights is None else np.asarray(weights,float)
    if w.shape!=(len(p),) or np.any(w<0) or not np.isclose(w.sum(),1):raise ValueError('Invalid posterior weights')
    states=np.array(list(itertools.product([0,1],repeat=p.shape[1])))
    probs=np.array([np.dot(w,np.prod(np.where(state,p,1-p),axis=1)) for state in states])
    returns=np.where(states,np.array([payout(o) for o in odds]),-1)
    return probs,returns

def clv(entry_line,entry_odds,close_line,close_odds,market,side,same_book,close_timestamp=None):
    if close_timestamp is None or not same_book:return dict(status='Missing verified same-book timestamped close',point_clv=None,price_clv=None)
    # Positive means the bettor got more points (spread), lower total (Over), higher total (Under).
    point=entry_line-close_line if market=='Spread' or side=='Under' else close_line-entry_line
    price=payout(entry_odds)-payout(close_odds) if entry_line==close_line else None
    return dict(status='Comparable',point_clv=point,price_clv=price)
