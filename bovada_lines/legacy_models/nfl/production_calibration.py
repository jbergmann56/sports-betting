import numpy as np
from scipy.special import expit,logit,betaln,logsumexp
from scipy.optimize import minimize_scalar,minimize
def pooled(d):
 return (d.y.sum()+.5)/(len(d)+1)

def fit(d,method,k=0):
 if d.empty:raise ValueError('Empty calibration training set')
 p=pooled(d);z={'method':method,'pooled_p':float(p),'n':len(d),'wins':int(d.y.sum()),'k':k}
 if method=='Pooled Jeffreys':z.update(a=float(d.y.sum()+.5),b=float(len(d)-d.y.sum()+.5))
 elif method=='Season partial pooling':
  z['groups']={}
  for group in ['W1-7','W8+']:
   g=d[d.regime==group];z['groups'][group]={'n':len(g),'wins':int(g.y.sum())}
  if k==0:
   for v in z['groups'].values():v.update(a=v['wins']+.5,b=v['n']-v['wins']+.5)
  else:
   # Exact grid integration of a shared mu ~ Beta(.5,.5), p_group|mu ~ Beta(k*mu,k*(1-mu)).
   # Each observation enters the beta-binomial likelihood once; pooled data is not reused as an independent prior.
   nodes,quad=np.polynomial.legendre.leggauss(240);mu=(nodes+1)/2;logw=np.log(quad/2)-.5*np.log(mu)-.5*np.log(1-mu)
   for v in z['groups'].values():logw+=betaln(v['wins']+k*mu,v['n']-v['wins']+k*(1-mu))-betaln(k*mu,k*(1-mu))
   weights=np.exp(logw-logsumexp(logw));z['mu_nodes']=mu.tolist();z['mu_weights']=weights.tolist()
 elif method in ['ML market offset','ML market offset by season']:
  anchor=np.clip(d.market_novig_dog.to_numpy(),1e-6,1-1e-6)
  if not np.isfinite(anchor).all():raise ValueError('Missing no-vig market anchor')
  y=d.y.to_numpy();base=logit(anchor)
  def obj(alpha):
   eta=base+alpha
   return float(np.logaddexp(0,eta).sum()-np.dot(y,eta)+.5*(alpha/1.5)**2)
  if method=='ML market offset':
   res=minimize_scalar(obj,bounds=(-4,4),method='bounded');z['alpha']=float(res.x);ph=expit(base+res.x);z['alpha_sd']=float(1/np.sqrt(np.sum(ph*(1-ph))+1/1.5**2))
  else:
   phase=np.where(d.regime.eq('W1-7'),1.,-1.)
   def objective(v):
    eta=base+v[0]+v[1]*phase
    return float(np.logaddexp(0,eta).sum()-np.dot(y,eta)+.5*(v[0]/1.5)**2+.5*v[1]**2)
   res=minimize(objective,[0.,0.],method='BFGS')
   if not np.isfinite(res.fun):raise ValueError('Failed ML calibration')
   z['alpha']=float(res.x[0]);z['phase_contrast']=float(res.x[1]);z['approx_covariance']=np.asarray(res.hess_inv).tolist()
 return z

def predict(z,d):
 if z['method']=='Pooled Jeffreys':return np.repeat(z['a']/(z['a']+z['b']),len(d))
 if z['method']=='Season partial pooling':
  mu=np.dot(z['mu_nodes'],z['mu_weights']) if z['k'] else None
  return np.array([(z['groups'][g]['wins']+z['k']*mu)/(z['groups'][g]['n']+z['k']) if z['k'] else z['groups'][g]['a']/(z['groups'][g]['a']+z['groups'][g]['b']) for g in d.regime])
 offset=z['alpha']+z.get('phase_contrast',0)*np.where(d.regime.eq('W1-7'),1.,-1.)
 return expit(logit(np.clip(d.market_novig_dog.to_numpy(),1e-6,1-1e-6))+offset)