"""Long-only expected-log portfolio Kelly from weighted JOINT return scenarios.
Rows may represent posterior-predictive mixtures. Dependence must be provided,
never inferred from marginal probabilities alone. Stakes are bankroll fractions.
"""
import numpy as np
from scipy.optimize import minimize

def full_kelly(p,decimal_profit):
 p=np.asarray(p,float);b=np.asarray(decimal_profit,float)
 if np.any((p<0)|(p>1)|(b<=0)):raise ValueError('Invalid probability or payout')
 return np.maximum(0,(b*p-(1-p))/b)

def portfolio_kelly(returns,weights=None):
 A=np.asarray(returns,float)
 if A.ndim!=2 or not A.size or not np.isfinite(A).all() or np.any(A < -1):raise ValueError('Invalid joint scenarios')
 w=np.ones(len(A))/len(A) if weights is None else np.asarray(weights,float)
 if w.shape!=(len(A),) or np.any(w<0) or not np.isfinite(w).all() or w.sum()<=0:raise ValueError('Invalid weights')
 w=w/w.sum();n=A.shape[1]
 def obj(f):
  wealth=1+A@f
  if np.any(wealth<=0):return 1e20,np.full(n,1e20)
  return -w@np.log(wealth),-A.T@(w/wealth)
 result=minimize(obj,np.zeros(n),jac=True,method='SLSQP',bounds=[(0,1)]*n,constraints=[{'type':'ineq','fun':lambda f:1-1e-10-f.sum(),'jac':lambda f:-np.ones(n)}],options={'ftol':1e-12,'maxiter':2000})
 if not result.success:raise RuntimeError(result.message)
 f=result.x
 return {'adjusted_kelly':f.tolist(),'expected_log_growth':float(-obj(f)[0]),'scenario_expected_returns':(w@A).tolist(),'method':'JOINT_POSTERIOR_PREDICTIVE_EXPECTED_LOG'}
