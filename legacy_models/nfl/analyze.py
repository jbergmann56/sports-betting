from pathlib import Path
import json,sys,numpy as np,pandas as pd
from scipy.optimize import minimize
from scipy.special import expit,logit
from core import payout,kelly
from segments import menu,cuts,indicators
from production_calibration import fit as champion_fit,predict as champion_predict
from champion_context import early_population
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';RNG=np.random.default_rng(26102601)

def prepare(d):
    ids=d[['game_id','season','week']].drop_duplicates().sort_values(['season','week','game_id']).reset_index(drop=True);ids['idx']=np.arange(len(ids))
    side=d.drop(columns=['idx'],errors='ignore').merge(ids,on=['game_id','season','week']).sort_values(['idx','sign'],ascending=[True,False]).reset_index(drop=True)
    home=side[side.sign==1].sort_values('idx').reset_index(drop=True);away=side[side.sign==-1].sort_values('idx').reset_index(drop=True)
    assert np.array_equal(home.game_id,away.game_id)
    return side,home,away

def fit_model(h,C,S=None):
    x=np.c_[np.ones(len(h)),C] if S is None else np.c_[np.ones(len(h)),C,S]
    valid=h.canonical_y.notna().to_numpy();xx=x[valid];y=h.canonical_y.to_numpy()[valid];offset=logit(h.canonical_anchor.to_numpy()[valid])
    def fun(b):
        eta=offset+xx@b;return np.sum(np.logaddexp(0,eta)-y*eta)+.5*np.sum((b/.5)**2)
    def jac(b):return xx.T@(expit(offset+xx@b)-y)+b/.25
    z=minimize(fun,np.zeros(x.shape[1]),jac=jac,method='BFGS',options={'gtol':1e-6});assert np.linalg.norm(jac(z.x))<.002
    ph=expit(offset+xx@z.x);H=xx.T@((ph*(1-ph))[:,None]*xx)+np.eye(x.shape[1])/.25
    return dict(beta=z.x.tolist(),covariance=np.linalg.inv(H).tolist(),train_n=len(y))

def predict(h,C,S,model):
    x=np.c_[np.ones(len(h)),C] if len(model['beta'])==2 else np.c_[np.ones(len(h)),C,S]
    mu=logit(h.canonical_anchor.to_numpy())+x@np.array(model['beta']);v=np.maximum(0,np.einsum('ij,jk,ik->i',x,np.array(model['covariance']),x));n,w=np.polynomial.hermite.hermgauss(20)
    return expit(mu[:,None]+np.sqrt(2*v)[:,None]*n)@(w/np.sqrt(np.pi))

def score_policy(h,a,sign,ph):
    home=sign>=0;eligible=sign!=0;p=np.where(home,ph,1-ph);odds=np.where(home,h.odds,a.odds);profit=np.where(home,h.profit,a.profit);y=np.where(home,h.y,a.y)
    pay=np.array([payout(o) for o in odds]);ev=p*pay-(1-p);bets=eligible&(ev>0);f=np.maximum(0,p-(1-p)/pay)*eligible
    return dict(eligible=eligible,p=p,odds=odds,profit=profit,y=y,ev=ev,bets=bets,f=f,flat=bets*profit,raw=eligible*profit,growth=np.log1p(f*profit),brier=(p-y)**2,loss=-y*np.log(p)-(1-y)*np.log(1-p))

def canonical_global(h):return fit_model(h,np.zeros(len(h)))

def summarize(s):
    ix=s['eligible'];b=s['bets'];v=ix&np.isfinite(s['y']);n=len(ix);nb=int(b.sum());ne=int(ix.sum())
    return dict(games=n,eligible=ne,decisive=int(v.sum()),bets=nb,wins=int(((s['y']==1)&b).sum()),losses=int(((s['y']==0)&b).sum()),pushes=int((b&~np.isfinite(s['y'])).sum()),profit=float(s['flat'].sum()),roi=float(s['flat'].sum()/nb) if nb else np.nan,unfiltered_roi=float(s['raw'].sum()/ne) if ne else np.nan,profit_per_game=float(s['flat'].mean()),mean_loggrowth=float(s['growth'].mean()),brier=float(np.nanmean(s['brier'][v])) if v.any() else np.nan,logloss=float(np.nanmean(s['loss'][v])) if v.any() else np.nan,mean_probability=float(np.mean(s['p'][v])) if v.any() else np.nan,observed_rate=float(np.mean(s['y'][v])) if v.any() else np.nan,mean_estimated_ev=float(np.mean(s['ev'][ix])) if ix.any() else np.nan)

def champion_sign(d,market):
    q=(d.gap.ge(5)&d.gap.lt(7)) if market=='Spread' else (d.odds.ge(250)&d.odds.lt(400)&d.gap.lt(-5)) if market=='Moneyline' else (d.selection.eq('Under')&d.gap.ge(4)&d.gap.lt(12))
    v=d[q].drop_duplicates('idx');s=np.zeros(int(d.idx.max())+1);s[v.idx.to_numpy(int)]=v.sign
    return s

def champion_population(sides,early):
    parts=[early]
    for market,d in sides.groupby('market'):
        side,h,a=prepare(d);sign=champion_sign(side,market);picked=side[side.sign.to_numpy()==sign[side.idx.to_numpy(int)]].copy()
        picked['regime']='W8+';picked['market_novig_dog']=picked.anchor;parts.append(picked)
    return pd.concat(parts,ignore_index=True)

def long_record(h,a,sign,s,other,global_s,year,rule):
    ix=np.flatnonzero(s['eligible']);hh=h.iloc[ix];home=sign[ix]>0
    return pd.DataFrame(dict(game_id=hh.game_id.to_numpy(),season=year,week=hh.week.to_numpy(),rule=rule,sign=sign[ix],selection=np.where(home,hh.selection.to_numpy(),a.iloc[ix].selection.to_numpy()),odds=s['odds'][ix],anchor=np.where(home,hh.anchor.to_numpy(),a.iloc[ix].anchor.to_numpy()),y=s['y'][ix],profit=s['profit'][ix],p=s['p'][ix],estimated_ev=s['ev'][ix],bet=s['bets'][ix],full_kelly=s['f'][ix],adjusted_kelly=np.nan,flat_profit=s['flat'][ix],raw_profit=s['raw'][ix],loggrowth=s['growth'][ix],brier=s['brier'][ix],logloss=s['loss'][ix],no_slope_p=other['p'][ix],no_slope_flat=other['flat'][ix],no_slope_growth=other['growth'][ix],no_slope_brier=other['brier'][ix],market_only_p=global_s['p'][ix],market_only_flat=global_s['flat'][ix],market_only_brier=global_s['brier'][ix]))

def run_scope(sides,early,start,lineage):
    scope='primary2018' if start==2018 else 'legacy_extended2013';eval_start=start+3;all_records=[];policy_records=[];folds=[];final={};innerrows=[]
    population=champion_population(sides[sides.season>=start],early[early.season>=start])
    for market,data in sides[sides.season>=start].groupby('market'):
        rules=menu(market);inner={r['name']:[] for r in rules};final[market]={}
        for year in range(start+1,2027):
            if year==2026:
                tr=data;test=data.iloc[:0]
            else:tr=data[data.season<year];test=data[data.season==year]
            d,h,a=prepare(tr);threshold=cuts(d,market);gm=canonical_global(h)
            if year<2026:
                td,th,ta=prepare(test);globalph=predict(th,np.zeros(len(th)),np.zeros(len(th)),gm)
                cp=population[(population.market==market)&(population.season<year)&population.y.notna()]
                z=champion_fit(cp,'ML market offset by season' if market=='Moneyline' else 'Season partial pooling',100)
                cs=champion_sign(td,market);ch_test=th.copy();ch_test['regime']='W8+';ch_test['market_novig_dog']=np.where(cs>0,th.anchor,ta.anchor)
                cpred=champion_predict(z,ch_test);cph=np.where(cs>=0,cpred,1-cpred);champ=score_policy(th,ta,cs,cph)
            ranking=[]
            if year>=eval_start:
                for r in rules:
                    hist=inner[r['name']]
                    if not hist:continue
                    n=sum(v['games'] for v in hist);profit=sum(v['profit'] for v in hist);growth=sum(v['growth'] for v in hist);delta=sum(v['growth_delta'] for v in hist)
                    if profit>0 and growth>0 and delta>0:ranking.append((growth/n,r['name']))
            selected=[name for _,name in sorted(ranking,reverse=True)[:3]]
            rule_scores={};rule_models={}
            for rule in rules:
                C,S=indicators(d,rule,threshold);ns=fit_model(h,C);sm=fit_model(h,C,S)
                rule_models[rule['name']]=dict(rule=rule,thresholds=threshold,structural=ns,slope=sm,global_market=gm)
                if year==2026:continue
                TC,TS=indicators(td,rule,threshold);ph=predict(th,TC,TS,sm);pns=predict(th,TC,TS,ns)
                s=score_policy(th,ta,TS,ph);n=score_policy(th,ta,TS,pns);g=score_policy(th,ta,TS,globalph)
                rule_scores[rule['name']]=(TS,s,n,g)
                inner[rule['name']].append(dict(season=year,games=len(th),eligible=int(s['eligible'].sum()),bets=int(s['bets'].sum()),profit=float(s['flat'].sum()),growth=float(s['growth'].sum()),growth_delta=float((s['growth']-n['growth']).sum())))
                if year>=eval_start:
                    rr=long_record(th,ta,TS,s,n,g,year,rule['name']);rr['market']=market;all_records.append(rr)
            if year==2026:
                final[market]=dict(selected_rules=selected,models={name:rule_models[name] for name in selected},all_rules=rule_models,through_season=2025,scope=scope,lineage=lineage)
                continue
            if year>=eval_start:
                # Choose best positive expected EV among the training-selected rules.
                best=np.full(len(th),-np.inf);which=np.full(len(th),'',object);ps=np.zeros(len(th));pph=globalph.copy()
                for name in selected:
                    TS,s,_,_=rule_scores[name];eligible=s['eligible']&(s['ev']>0);take=eligible&(s['ev']>best)
                    best[take]=s['ev'][take];which[take]=name;ps[take]=TS[take];pph[take]=np.where(TS[take]>0,s['p'][take],1-s['p'][take])
                pol=score_policy(th,ta,ps,pph)
                for version,sco in [('Nested slope policy',pol),('Champion replay',champ)]:
                    policy_records.append(pd.DataFrame(dict(game_id=th.game_id,season=year,week=th.week,market=market,version=version,rule=which if version=='Nested slope policy' else 'champion',sign=ps if version=='Nested slope policy' else cs,bet=sco['bets'],p=sco['p'],odds=sco['odds'],full_kelly=sco['f'],adjusted_kelly=np.nan,profit=sco['flat'],loggrowth=sco['growth'],eligible=sco['eligible'])))
                folds.append(dict(market=market,year=year,train_start=start,train_max=year-1,selected_rules=selected,eligible_games=len(th),champion_qualified=int(champ['eligible'].sum()),champion_bets=int(champ['bets'].sum()),challenger_bets=int(pol['bets'].sum())))
        for rule,values in inner.items():
            for row in values:innerrows.append(dict(market=market,rule=rule,**row))
    prefix=scope+'__'+lineage
    rec=pd.concat(all_records,ignore_index=True);rec['scope']=scope;rec['lineage']=lineage;rec.to_csv(OUT/(prefix+'__candidate_predictions.csv'),index=False)
    pol=pd.concat(policy_records,ignore_index=True);pol['scope']=scope;pol['lineage']=lineage;pol.to_csv(OUT/(prefix+'__policy_predictions.csv'),index=False)
    pd.DataFrame(innerrows).to_csv(OUT/(prefix+'__inner_selection_history.csv'),index=False)
    json.dump(folds,open(OUT/(prefix+'__fold_selection.json'),'w'),indent=2)
    json.dump(final,open(OUT/(prefix+'__frozen_models.json'),'w'),indent=2)
    print(prefix,'candidate rows',len(rec),'policy rows',len(pol),'folds',len(folds),flush=True)
    return rec,pol,folds

def block_inference(values,blocks,signs):
    # Fixed-denominator week-cluster multiplier bootstrap for mean profit.
    n=len(values);mu=float(np.mean(values));g=np.bincount(blocks,weights=values-mu,minlength=signs.shape[1]);error=signs@g/n
    return dict(mean=mu,low=float(mu-np.quantile(error,.975)),high=float(mu-np.quantile(error,.025)),p=float((1+np.sum(error>=mu))/(len(error)+1)))

def holm(p):
    p=np.asarray(p);order=np.argsort(p);q=np.ones(len(p));last=0
    for i,j in enumerate(order):last=max(last,min(1,(len(p)-i)*p[j]));q[j]=last
    return q

def main():
    raw=pd.read_csv(ROOT/'data/nflverse_games.csv');raw=raw[(raw.game_type=='REG')&raw.away_score.notna()&raw.home_score.notna()]
    for c in ['away_team','home_team']:raw[c]=raw[c].replace({'OAK':'LV','SD':'LAC','STL':'LA'})
    early=early_population(raw);early.to_csv(ROOT/'data/champion_early_context.csv',index=False)
    allrec=[];allpol=[];allfold=[]
    for start in [2018,2013]:
        for lin in ['reconstructed','hybrid']:
            if '--inference-only' in sys.argv:
                prefix=('primary2018' if start==2018 else 'legacy_extended2013')+'__'+lin
                rec=pd.read_csv(OUT/(prefix+'__candidate_predictions.csv'));pol=pd.read_csv(OUT/(prefix+'__policy_predictions.csv'));fold=json.load(open(OUT/(prefix+'__fold_selection.json')))
            else:
                sides=pd.read_csv(ROOT/'data'/f'{lin}_sides.csv');rec,pol,fold=run_scope(sides,early,start,lin)
            allrec.append(rec);allpol.append(pol);allfold.extend(fold)
    summaries=[];tests=[];policy_summaries=[];policy_tests=[];seasonrows=[]
    for rec,pol in zip(allrec,allpol):
        scope=rec.scope.iloc[0];lineage=rec.lineage.iloc[0]
        for market,pp in pol.groupby('market'):
            base=pp[pp.version=='Champion replay'].sort_values('game_id');nested=pp[pp.version=='Nested slope policy'].sort_values('game_id')
            assert np.array_equal(base.game_id,nested.game_id)
            idx=pd.factorize(base.season.astype(str)+'_'+base.week.astype(str))[0];sg=RNG.choice([-1.,1.],size=(50000,len(np.unique(idx))))
            for version,g in pp.groupby('version'):
                bets=g[g.bet];policy_summaries.append(dict(scope=scope,lineage=lineage,market=market,version=version,games=len(g),bets=len(bets),profit=g.profit.sum(),roi=bets.profit.mean(),mean_loggrowth=g.loggrowth.mean()))
            for metric,col in [('profit','profit'),('loggrowth','loggrowth')]:policy_tests.append(dict(scope=scope,lineage=lineage,market=market,metric=metric,**block_inference(nested[col].to_numpy()-base[col].to_numpy(),idx,sg)))
            games=base[['game_id','season','week']].reset_index(drop=True);N=len(games);lookup=dict(zip(games.game_id,np.arange(N)))
            rmarket=rec[rec.market==market]
            for rule,g in rmarket.groupby('rule'):
                ix=np.array([lookup[v] for v in g.game_id]);assert len(ix)==len(np.unique(ix))
                values=np.zeros(N);values[ix]=g.flat_profit;rawvalues=np.zeros(N);rawvalues[ix]=g.raw_profit;inc=np.zeros(N);inc[ix]=g.flat_profit-g.no_slope_flat
                mktinc=np.zeros(N);mktinc[ix]=g.flat_profit-g.market_only_flat
                nb=int(g.bet.sum());ne=len(g);actual=g[g.bet];decisive=g.y.notna();no_slope_bets=(g.no_slope_flat!=0).sum()
                slope_brier=float(np.mean(g.loc[decisive,'brier']));ns_brier=float(np.mean(g.loc[decisive,'no_slope_brier']));mk_brier=float(np.mean(g.loc[decisive,'market_only_brier']))
                summaries.append(dict(scope=scope,lineage=lineage,market=market,rule=rule,games=N,eligible=ne,decisive=int(decisive.sum()),bets=nb,wins=int(actual.y.eq(1).sum()),losses=int(actual.y.eq(0).sum()),pushes=int(actual.y.isna().sum()),profit=float(g.flat_profit.sum()),roi=float(g.flat_profit.sum()/nb) if nb else np.nan,raw_profit=float(g.raw_profit.sum()),raw_roi=float(g.raw_profit.sum()/ne),profit_per_game=float(values.mean()),mean_loggrowth=float(g.loggrowth.sum()/N),brier=slope_brier,no_slope_brier=ns_brier,market_only_brier=mk_brier,mean_p=float(g.p.mean()),observed_rate=float(g.y.mean()),mean_estimated_ev=float(g.estimated_ev.mean()),mean_price=float(g.odds.mean()),positive_profit_years=int(g.groupby('season').flat_profit.sum().gt(0).sum()),active_years=int(actual.season.nunique())))
                for endpoint,val in [('raw_profit',rawvalues),('positive_ev_profit',values),('incremental_vs_no_slope',inc),('incremental_vs_market',mktinc)]:
                    inference=block_inference(val,idx,sg)
                    tests.append(dict(scope=scope,lineage=lineage,market=market,rule=rule,endpoint=endpoint,**inference))
                for year,v in g.groupby('season'):seasonrows.append(dict(scope=scope,lineage=lineage,market=market,rule=rule,season=year,eligible=len(v),bets=int(v.bet.sum()),profit=v.flat_profit.sum(),raw_profit=v.raw_profit.sum(),loggrowth=v.loggrowth.sum()))
    summary=pd.DataFrame(summaries);test=pd.DataFrame(tests)
    policytest=pd.DataFrame(policy_tests)
    allq=holm(np.r_[test.p.to_numpy(),policytest.p.to_numpy()])
    test['holm_p']=allq[:len(test)];policytest['holm_p']=allq[len(test):]
    merged=summary.merge(test[test.endpoint=='positive_ev_profit'][['scope','lineage','market','rule','low','high','holm_p']],on=['scope','lineage','market','rule'])
    merged['roi_low']=merged.low*merged.games/merged.bets.replace(0,np.nan);merged['roi_high']=merged.high*merged.games/merged.bets.replace(0,np.nan)
    def tier(r):
        if r.bets==0:return 'Pass'
        if r.profit<=0:return 'Lean' if r.mean_estimated_ev>0 else 'Pass'
        if r.low>0 and r.holm_p<.05 and r.positive_profit_years>=2:return 'A historical candidate'
        if r.low>0 and r.positive_profit_years>=2:return 'B+ candidate'
        return 'B candidate'
    merged['tier']=merged.apply(tier,axis=1);merged['status']='Challenger; champion unchanged'
    merged.to_csv(OUT/'segment_evidence.csv',index=False);test.to_csv(OUT/'all_segment_tests.csv',index=False);pd.DataFrame(policy_summaries).to_csv(OUT/'champion_policy_comparison.csv',index=False);policytest.to_csv(OUT/'champion_paired_tests.csv',index=False);pd.DataFrame(seasonrows).to_csv(OUT/'segment_season_stability.csv',index=False)
    main=merged[(merged.scope=='primary2018')&(merged.lineage=='reconstructed')]
    main.sort_values(['market','profit'],ascending=[True,False]).to_csv(OUT/'primary_ranked_segments.csv',index=False)
    checks=dict(all_markets=set(main.market)=={'Spread','Moneyline','Total'},broader_than_champion=main.eligible.max()>100,earlier_years_evaluated=any(z['year']==2021 for z in allfold),prior_only=all(z['train_max']<z['year'] for z in allfold),no_automatic_champion_change=True,menu_fully_reported=len(main)==sum(len(menu(m)) for m in ['Spread','Moneyline','Total']),both_outcome_directions_in_population=True)
    for lin in ['reconstructed','hybrid']:
        side=pd.read_csv(ROOT/'data'/f'{lin}_sides.csv');checks[lin+'_one_row_per_side']=not side.duplicated(['game_id','market','sign']).any();pairs=side.groupby(['game_id','market']);checks[lin+'_complementary_anchors']=np.allclose(pairs.anchor.sum(),1);checks[lin+'_opposite_y']=bool(pairs.y.sum(min_count=2).dropna().eq(1).all());checks[lin+'_cutoff']=bool(side.feature_cutoff_week.lt(side.week).all())
    checks={k:bool(v) for k,v in checks.items()};json.dump(checks,open(OUT/'validation.json','w'),indent=2);assert all(checks.values())
    print('PRIMARY strongest segments\n',main.sort_values('profit',ascending=False).head(12).to_string(index=False));print('PRIMARY tiers\n',main.groupby(['market','tier']).size().to_string());print('TOTAL TESTS',len(test),'CHECKS',len(checks),flush=True)
if __name__=='__main__':main()
