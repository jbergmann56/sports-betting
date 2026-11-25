import itertools,json,numpy as np
from portfolio_kelly import portfolio_kelly,full_kelly
checks={}
f=portfolio_kelly([[1],[-1]],[.6,.4]);assert abs(f['adjusted_kelly'][0]-.2)<1e-5;checks['single_bet_matches_full_kelly']=True
f=portfolio_kelly([[1],[-1]],[.45,.55]);assert f['adjusted_kelly'][0]<1e-7;checks['negative_edge_zero']=True
# Two perfectly duplicated bets receive the same total stake as a single exposure.
f=portfolio_kelly([[1,1],[-1,-1]],[.6,.4]);assert abs(sum(f['adjusted_kelly'])-.2)<1e-5;checks['perfect_correlation_total_exposure']=True
A=np.array(list(itertools.product([1,-1],repeat=2)));w=np.array([.36,.24,.24,.16]);f=portfolio_kelly(A,w);assert .18<f['adjusted_kelly'][0]<.21 and abs(f['adjusted_kelly'][0]-f['adjusted_kelly'][1])<1e-5;checks['independent_symmetric_joint_optimum']=True
# Posterior mixture with the same predictive mean gives identical single-bet Kelly.
a=portfolio_kelly([[1],[-1],[1],[-1]],[.35,.15,.25,.25]);assert abs(a['adjusted_kelly'][0]-.2)<1e-5;checks['no_double_uncertainty_haircut']=True
try:portfolio_kelly([[1],[-1]],[1,-1]);raise AssertionError()
except ValueError:checks['invalid_weights_rejected']=True
print(json.dumps(checks,indent=2))
from pathlib import Path
Path(__file__).with_name('KELLY_TEST_RESULTS.json').write_text(json.dumps(checks,indent=2))
