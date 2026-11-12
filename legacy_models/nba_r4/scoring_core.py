from pathlib import Path
import csv,json,math,hashlib,collections,datetime,statistics
from scipy.stats import beta as beta_dist
def newteam():return {'elo':1500.,'last':None,'dates':[], 'margins':[], 'pf':[], 'pa':[], 'previous_margin':0.,'previous_margins':[], 'previous_pf':[], 'previous_pa':[],'ewma':0.,'games':0}
teams=collections.defaultdict(newteam);season=None;league_totals=[]
def fallback(x,prev,defval):return float(statistics.mean(x)) if x else float(statistics.mean(prev)) if prev else float(defval)
def snapshot(name,day):
 t=teams[name];delta=(day-t['last']).days if t['last'] is not None else None
 return dict(elo=t['elo'],prior_margin=t['previous_margin'],cum_margin=statistics.mean(t['margins']) if t['margins'] else 0.,ewma=t['ewma'],
 margin5=fallback(t['margins'][-5:],t['previous_margins'],0),margin10=fallback(t['margins'][-10:],t['previous_margins'],0),
 pf5=fallback(t['pf'][-5:],t['previous_pf'],112.4),pf10=fallback(t['pf'][-10:],t['previous_pf'],112.4),
 pa5=fallback(t['pa'][-5:],t['previous_pa'],112),pa10=fallback(t['pa'][-10:],t['previous_pa'],112),
 rest=min(max(delta-1,0),7) if delta is not None else 3,b2b=int(delta==1) if delta is not None else 0,
 three4=int(sum((day-x).days<=3 for x in t['dates'])>=2),four6=int(sum((day-x).days<=5 for x in t['dates'])>=3),games=t['games'])
def makefeature(home,away,d):
 h=snapshot(home,d);a=snapshot(away,d)
 f={k+'_diff_home':h[k]-a[k] for k in ('elo','prior_margin','cum_margin','ewma','margin5','margin10','rest','b2b','three4','four6')}
 f['ewma_margin_diff_home']=f.pop('ewma_diff_home')
 f['season_stage']=(h['games']+a['games'])/2
 for k in ('pf5','pa5','pf10','pa10'):
  f['home_'+k]=h[k];f['away_'+k]=a[k]
 f['league_avg_total']=statistics.mean(league_totals) if league_totals else 220.
 for k in ('rest','b2b','three4','four6'):
  f['home_'+('3in4' if k=='three4' else '4in6' if k=='four6' else k)]=h[k];f['away_'+('3in4' if k=='three4' else '4in6' if k=='four6' else k)]=a[k]
 return f

bydate=collections.defaultdict(list)
for r in hist:bydate[r['date']].append(r)
for daystr,games in sorted(bydate.items()):
 ss=games[0]['season'];assert all(g['season']==ss for g in games)
 if ss!=season:
  if season is not None:
   for t in teams.values():
    t['elo']=1500+0.65*(t['elo']-1500)
    t['previous_margin']=statistics.mean(t['margins']) if t['margins'] else t['previous_margin']
    t['previous_margins']=t['margins'][:];t['previous_pf']=t['pf'][:];t['previous_pa']=t['pa'][:]
    t['margins']=[];t['pf']=[];t['pa']=[];t['ewma']=0.;t['games']=0
  season=ss;league_totals=[]
 day=datetime.date.fromisoformat(daystr)
 prior={r['game_key']:(snapshot(r['home'],day),snapshot(r['away'],day)) for r in games}
 for g in games:
  h0,a0=prior[g['game_key']];home=g['home'];away=g['away'];h=float(g['home_score']);a=float(g['away_score'])
  ph=1/(1+10**(-(h0['elo']-a0['elo']+25)/400));delta=15*(int(h>a)-ph)
  teams[home]['elo']+=delta;teams[away]['elo']-=delta
  for name,pf,pa in ((home,h,a),(away,a,h)):
   t=teams[name];m=pf-pa
   t['margins'].append(m);t['pf'].append(pf);t['pa'].append(pa)
   t['ewma']=.1*m+.9*t['ewma'];t['dates'].append(day)
   t['dates']=[v for v in t['dates'] if (day-v).days<=5]
   t['last']=day;t['games']+=1
  league_totals.append(h+a)

def predict(model_name,features):
 model=C['models'][model_name];val=model['intercept']
 for z in model['features']:
  n=z['Feature'];val+=z['Coefficient_Standardized']*(features[n]-z['Scaler_Mean'])/z['Scaler_Scale']
 return 1/(1+math.exp(-val)) if model_name=='moneyline_structural' else val

def implied(o):return 100/(100+o) if o>0 else -o/(-o+100)
def net(o):return o/100 if o>0 else 100/-o
def ev_full(p,o):
 if p is None:return None,None
 b=net(o);ev=b*p-(1-p);return ev,max(0,ev/b)
def write(name,rows):
 if not rows:return
 path=BASE/name
 with path.open('w',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=list(rows[0]),extrasaction='ignore');wr.writeheader();wr.writerows(rows)
 return path

board=[];market_rows=[];features=[];contract_rows=[]
for game_date,game,away,home,aline,asp,hsp,aml,hml,total,oop,uop in QUOTES:
 day=datetime.date.fromisoformat(game_date)
 assert all(g['date']<game_date for g in hist)
 f=makefeature(home,away,day)
 hm=predict('spread_structural',f);mt=predict('total_structural',f);hp=predict('moneyline_structural',f)
 # Positive if model favors home more than market; qualifies only if selected side underdog.
 signed=hm-aline
 sp_side='HOME' if signed>0 else 'AWAY'
 sp_under=(aline<0 if sp_side=='HOME' else aline>0)
 sp_qual=sp_under and abs(signed)>=5
 sp_name=(home if sp_side=='HOME' else away)+f' {(-aline if sp_side=="HOME" else aline):+g}'
 sp_odds=hsp if sp_side=='HOME' else asp
 qa,qh=implied(aml),implied(hml)
 no_vig_a=qa/(qa+qh);no_vig_h=qh/(qa+qh)
 ml_side='HOME' if hp-no_vig_h>(1-hp)-no_vig_a else 'AWAY'
 ml_mp=no_vig_h if ml_side=='HOME' else no_vig_a
 ml_struct=hp if ml_side=='HOME' else 1-hp
 residual=ml_struct-ml_mp
 ml_tier='B+' if ml_mp<.30 and .03<=residual<.06 else 'Lean' if ml_mp<.30 and .06<=residual<.08 else 'Pass'
 ml_odds=hml if ml_side=='HOME' else aml
 ml_name=home if ml_side=='HOME' else away
 ml_p=None
 if ml_tier=='B+':
  off=C['production_rules']['ML_BPLUS']['offset'];z=math.log(ml_mp/(1-ml_mp))+off;ml_p=1/(1+math.exp(-z))
 ougap=total-mt
 ou_qual=ougap>=10
 # Current production rules: spread B only underdog, Under B only gap >=10, ML B+ narrow residual.
 cands=[
 ('Spread',sp_name,sp_odds,'B' if sp_qual else 'Pass',C['production_rules']['SPREAD_B']['model_p'] if sp_qual else None,abs(signed),'Model/market home margin gap, points',
   'Underdog; gap >= 5' if sp_qual else 'No qualifying underdog gap >=5'),
 ('Moneyline',ml_name+' ML',ml_odds,ml_tier,ml_p,residual,'Structural-vs-no-vig residual, probability points',
   'Underdog market P<30% and residual 3-6 pp' if ml_tier=='B+' else 'No B+ condition satisfied'),
 ('Total',f'Under {total:g}',uop,C['production_rules']['OU_B']['tier'] if ou_qual else 'Pass',C['production_rules']['OU_B']['model_p'] if ou_qual else None,ougap,'Market total minus predicted total, points',
   'Under gap >=10 points' if ou_qual else 'Under gap <10 points')]
 for market,selection,odds,tier,p,edge,edge_type,reason in cands:
  ev,k=ev_full(p,odds)
  post=C['production_rules']['SPREAD_B']['evidence']['combined_posterior'] if market=='Spread' and tier=='B' else C['production_rules']['OU_B']['evidence']['combined_posterior'] if market=='Total' and tier=='B' else None
  if post is not None:
   a,b=post['wins']+.5,post['n']-post['wins']+.5
   low,high=beta_dist.ppf([.025,.975],a,b)
   ppos=beta_dist.sf(implied(odds),a,b)
  else:low=high=ppos=None
  market_rows.append(dict(Date=game_date,Game=game,Away=away,Home=home,Market=market,Selection=selection,Odds=odds,Tier=tier,Model_P=p,EV=ev,Full_Kelly=k,
   Adjusted_Kelly='NOT_CERTIFIED' if tier in ('B','B+') else 'N/A',Edge_Metric=edge,Edge_Type=edge_type,Reason=reason,
   Model_Home_Margin=hm,Predicted_Total=mt,Structural_Home_Win_P=hp,Market_Away_Spread=aline,Market_Total=total,Selected_NoVig_ML_P=ml_mp if market=='Moneyline' else None,
   Away_B2B=f['away_b2b'],Home_B2B=f['home_b2b'],Posterior_95_Low=low,Posterior_95_High=high,Posterior_P_Positive_EV=ppos,
   Model_Health=(C['production_rules']['SPREAD_B']['health'] if market=='Spread' and tier=='B' else C['production_rules']['OU_B']['health'] if market=='Total' and tier=='B' else C['production_rules']['ML_BPLUS']['health'] if tier=='B+' else 'Pass / ungraded'),
   Validation='PREVIOUS_DEPLOYED_SCORER_RESTORED_R4',Quote_Source='USER_BOVADA_UNTIMESTAMPED'))
 # Retain all offered odds at side level (30 total)
 contracts=[('Spread',away,f'{away} {aline:+g}',aline,asp),('Spread',home,f'{home} {-aline:+g}',-aline,hsp),
 ('Moneyline',away,away+' ML',None,aml),('Moneyline',home,home+' ML',None,hml),
 ('Total','Over',f'Over {total:g}',total,oop),('Total','Under',f'Under {total:g}',total,uop)]
 for m,side,sel,line,price in contracts:
  contract_rows.append(dict(Date=game_date,Game=game,Market=m,Side=side,Selection=sel,Line=line,Odds=price,Quote_Source='USER_BOVADA_UNTIMESTAMPED'))
 board.append(dict(Date=game_date,Game=game,Away=away,Home=home,Market_Away_Spread=aline,Market_Total=total,Predicted_Home_Margin=hm,Predicted_Total=mt,Predicted_Home_Win_P_Structural=hp,
  Predicted_Winner=(home if hm>=0 else away),Model_Margin_Advantage=abs(signed),Spread_Selection=sp_name,Spread_Tier='B' if sp_qual else 'Pass',
  Moneyline_Selection=ml_name+' ML',Moneyline_Tier=ml_tier,Total_Selection=f'Under {total:g}',Total_Tier='B' if ou_qual else 'Pass',Under_Gap=ougap,
  Away_B2B=f['away_b2b'],Home_B2B=f['home_b2b'],Quote_Capture='USER_QUOTED_UNTIMESTAMPED',Reconstruction='UNVERIFIED_FEATURE_PARITY'))
 features.append(dict(Date=game_date,Game=game,Away=away,Home=home,**f,Predicted_Home_Margin=hm,Predicted_Total=mt,Structural_Home_WinP=hp))

assert len(board)==len(QUOTES) and len(market_rows)==3*len(QUOTES)
qualified=[r for r in market_rows if r['Tier'] in ('B','B+')]
write('NBA_V27_OCT29_ALL_MARKETS.csv',market_rows)
write('NBA_V27_OCT29_PROJECTIONS.csv',board)
write('NBA_V27_OCT29_FEATURES.csv',features)
write('NBA_V27_OCT29_CONTRACTS.csv',contract_rows)
write('NBA_V27_OCT29_QUALIFIERS.csv',qualified if qualified else [{'Selection':'NO_QUALIFIERS'}])
write('NBA_HISTORY_THROUGH_OCT28.csv',hist)
