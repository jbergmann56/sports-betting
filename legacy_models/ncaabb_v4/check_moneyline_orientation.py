"""Regression tests for home/away role invariance and cohort-specific fallback."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from ncaabb_models import odds_profit
from ncaabb_matchup import fit_cell,fit_regimes,apply_regimes,route

ROOT=Path(__file__).resolve().parents[1]
n=360
side=np.arange(n)%2==0
hits=np.arange(n)%4<2
q=pd.DataFrame({'y':np.where(side,hits,~hits).astype(float),'structural_side1':side,
    'p_Market_Benchmark':np.where(side,.25,.75),'game_date':pd.date_range('2022-01-01',periods=n).astype(str),
    'season':np.where(np.arange(n)<180,2022,2023),'pushed':False,'core_segment':'priced','context_segment':'priced','full_segment':'priced',
    'ml_segment_has_verified_pair':True})
a=fit_cell(q,'Moneyline')
flip=q.copy();flip['y']=1-q.y;flip['p_Market_Benchmark']=1-q.p_Market_Benchmark;flip['structural_side1']=~q.structural_side1
b=fit_cell(flip,'Moneyline')
assert a['delta']>0 and abs(a['delta']-b['delta'])<1e-10
u=q.copy();u['ml_segment_has_verified_pair']=False;u['p_Market_Benchmark']=np.where(side,.8,.2)
uhit=np.arange(n)%5!=0;u['y']=np.where(side,uhit,~uhit).astype(float)
u['core_segment']=u['context_segment']=u['full_segment']='unpriced'
params=fit_regimes(pd.concat([q,u]),'Moneyline')
test=q.iloc[[0,1]].copy();test['core_segment']=test['context_segment']=test['full_segment']='unseen'
p,ev=apply_regimes(params,test,'Moneyline')
assert p[0]>.25 and p[1]<.75 and abs(p[0]-(1-p[1]))<1e-12
assert ev.fallback_level.eq('Anchor group').all() and ev.evidence_segment.eq('Priced underdog').all()
pred=u.iloc[[0]].copy();pred['core_segment']=pred['context_segment']=pred['full_segment']='unseen'
up,uev=apply_regimes(params,pred,'Moneyline')
assert uev.evidence_segment.eq('Unpriced winner forecast').all()
assert abs(params['global_by_anchor']['Unpriced winner forecast']['delta'])<1e-4
assert abs(params['global_by_anchor']['Priced underdog']['delta']-a['delta'])<1e-10
checks={'side_swap_fit_delta_error':abs(a['delta']-b['delta']),'side_swap_probability_complement_error':abs(p[0]-(1-p[1])),
 'positive_offset_raises_home_or_away_underdog_probability':True,'cohort_fallbacks_separate_priced_dogs_from_unpriced_winners':True,
 'priced_fit_unchanged_by_adding_unpriced_rows':True}
rq=pd.DataFrame({'core_segment':['Dog <+250|Early','Unpriced margin <5|Early','Dog +700+|Early'], 'p_Segment_Rule':[.1,.2,.3], 'p_Logistic':[.4,.5,.6], 'p_RandomForest':[.7,.8,.9], 'p_SRS_Projection':[.11,.12,.13]})
rp,chosen=route(rq,{'Global':'Segment_Rule','anchors':{'Priced underdog':'Logistic','Unpriced winner forecast':'RandomForest'},'cells':{'Dog +700+|Early':'SRS_Projection'}})
assert chosen.tolist()==['Logistic','RandomForest','SRS_Projection'] and np.allclose(rp,[.4,.8,.13])
checks['challenger_anchor_route_and_local_override_checked']=True
d=pd.read_csv(ROOT/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv',dtype={'game_id':str},low_memory=False)
paired=d.away_moneyline.notna()&d.home_moneyline.notna()
t=d.loc[paired].copy();ap=1/(1+odds_profit(t.away_moneyline));hp=1/(1+odds_profit(t.home_moneyline));recomputed=ap/(ap+hp)
errors=np.abs(recomputed-t.away_ml_no_vig_probability)
assert errors.max()<1e-12
checks['paired_quote_anchor_rows']=len(t);checks['paired_quote_anchor_max_error']=float(errors.max())
flag=(t.away_spread.lt(-2)&(recomputed<.4))|(t.away_spread.gt(2)&(recomputed>.6))
t['recomputed_away_no_vig_p']=recomputed;t['quote_handicap_direction_flag']=flag
t.loc[flag,['game_id','season','game_date','away_team','home_team','away_spread','away_moneyline','home_moneyline','recomputed_away_no_vig_p','moneyline_time_status']].to_csv(ROOT/'NCAABB_V4_QUOTE_DIRECTION_FLAGS.csv',index=False)
checks['strong_quote_handicap_disagreement_rows']=int(flag.sum())
# This only establishes internal direction consistency, not historical timestamp authenticity.
checks['historical_timestamps_not_independently_reverified']=True
(ROOT/'NCAABB_V4_ORIENTATION_CHECKS.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))
