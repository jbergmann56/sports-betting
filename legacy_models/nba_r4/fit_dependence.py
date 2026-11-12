from pathlib import Path
import pandas as pd,numpy as np,json
R=Path(__file__).resolve().parent
p=pd.read_csv(R/'evidence/ml_spread_predictions.csv');p=p[p.engine=='corrected'];tr=p[p.Season!='2024/2025'];te=p[p.Season=='2024/2025'];e=tr.correct_margin-tr.spread_structural;mu=e.mean();sd=e.std(ddof=1)
def pairs(d):
 out=[]
 for date,g in d.groupby('Date'):
  z=((g.correct_margin-g.spread_structural-mu)/sd).to_numpy()
  if len(z)>1:
   a,b=np.triu_indices(len(z),1);out.extend((date,float(z[i]),float(z[j])) for i,j in zip(a,b))
 return pd.DataFrame(out,columns=['Date','a','b'])
a=pairs(tr);b=pairs(te);rho=float(np.clip((a.a*a.b).mean(),0,.5));b['ll_delta']=-.5*np.log(1-rho*rho)-.5*((b.a**2+b.b**2-2*rho*b.a*b.b)/(1-rho*rho)-(b.a**2+b.b**2))
rng=np.random.default_rng(3);agg=b.groupby('Date').ll_delta.agg(['sum','count']).to_numpy();sim=[]
for _ in range(2000):
 z=agg[rng.integers(len(agg),size=len(agg))].sum(axis=0);sim.append(z[0]/z[1])
raw=a.assign(product=a.a*a.b).groupby('Date').product.agg(['sum','count']).to_numpy();rho_samples=[]
for _ in range(2000):
 z=raw[rng.integers(len(raw),size=len(raw))].sum(axis=0);rho_samples.append(z[0]/z[1])
push=tr[tr.away_line.notna()&(tr.away_line%1==0)];rate=float((push.correct_margin==push.away_line).mean())
result=dict(train_last=tr.Date.max(),holdout_first=te.Date.min(),training_pairs=len(a),unconstrained_training_cross_product=float((a.a*a.b).mean()),training_date_bootstrap_cross_product_ci=np.quantile(rho_samples,[.025,.975]).tolist(),holdout_pairs=len(b),estimated_nonnegative_daily_margin_rho=rho,holdout_pair_logscore_delta=float(b.ll_delta.mean()),holdout_date_bootstrap_ci=np.quantile(sim,[.025,.975]).tolist(),integer_spread_push_rate=rate,working_cross_game_assumption='INDEPENDENT_GAMES',same_game_assumption='COMMON_HOME_MARGIN_RANK_WITH_MONOTONICITY_CHECK',operational_status='SHADOW_ADJUSTED_KELLY; conditional scenario model, not validated joint calibration')
json.dump(result,open(R/'DEPENDENCE_MODEL.json','w'),indent=2);b.to_csv(R/'evidence/dependence_holdout_pairs.csv',index=False);print(json.dumps(result,indent=2))
