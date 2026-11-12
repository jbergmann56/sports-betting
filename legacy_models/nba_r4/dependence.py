"""Exact finite scenarios: common margin rank within games, independent across games.
Marginal probabilities already calibrated; no probability haircut. Assumptions explicit.
"""
import itertools,numpy as np

def scenarios(rows,push_rate):
 groups=[]
 for game in dict.fromkeys(rows.Game):
  ids=np.where(rows.Game.to_numpy()==game)[0];bounds=[0.,1.];info=[]
  for i in ids:
   r=rows.iloc[i];p=float(r.Model_P);push=push_rate if r.Market=='Spread' and float(r.Market_Away_Spread)%1==0 else 0.
   home=r.Selection.startswith(r.Home)
   threshold=0. if r.Market=='Moneyline' else float(r.Market_Away_Spread)
   if home:lo=(1-p)*(1-push);hi=lo+push
   else:lo=p*(1-push);hi=lo+push
   info.append((i,home,lo,hi,threshold));bounds.extend([lo,hi])
  # F(margin threshold) must be nondecreasing in the margin threshold.
  ordered=sorted(info,key=lambda z:z[4])
  for left,right in zip(ordered,ordered[1:]):
   if (left[4]<right[4] and left[3]>right[2]+1e-8) or (left[4]==right[4] and (abs(left[2]-right[2])>1e-8 or abs(left[3]-right[3])>1e-8)):raise ValueError('Same-game calibrated probabilities conflict with margin ordering')
  bounds=sorted(set(bounds));states=[]
  for lo,hi in zip(bounds,bounds[1:]):
   if hi-lo<1e-12:continue
   u=(lo+hi)/2;v=np.zeros(len(rows))
   for i,home,l,h,_ in info:
    r=rows.iloc[i];win=(u>h if home else u<l);push=l<u<h;b=r.Odds/100 if r.Odds>0 else 100/-r.Odds;v[i]=0 if push else b if win else -1
   states.append((hi-lo,v))
  groups.append(states)
 if np.prod([len(g) for g in groups])>200000:raise ValueError('Slate too large for exact scenarios; split by settlement availability or provide external scenarios')
 A=[];w=[]
 for combination in itertools.product(*groups):
  w.append(np.prod([z[0] for z in combination]));A.append(np.sum([z[1] for z in combination],axis=0))
 return np.array(A),np.array(w)
