"""Basketball adaptation of football matchup regimes and champion/challenger testing.

Outcome-free feature assignment, effective-sample calibration, and chronological
model routing. Base estimators are retrained under the source WEEK policy. Frozen 2025
estimators use outcomes through 2024 only. See SPECIFICATION.json for fixed design choices.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, logit
from scipy.stats import beta, norm
from ncaabb_models import (num, boolean, verified, feature_table, predict_base,
                          calibrate, market_mask, targets, odds_columns, odds_profit,week_early,rating_input)

PRIOR_N=50
MODELS=['Segment_Rule','Logistic','HistGradientBoosting','RandomForest','SRS_Projection','Market_Benchmark']
MARKETS=['Spread','Moneyline','Total']

def effective_ratings(d):
    a=rating_input(d,'away','srs')
    h=rating_input(d,'home','srs')
    return a,h

def estimate_hfa(train):
    a,h=effective_ratings(train)
    court=(~boolean(train,'neutral_site')).astype(float)
    y=num(train,'actual_away_margin')
    good=a.notna()&h.notna()&y.notna()
    x=np.column_stack([np.ones(good.sum()),(a-h)[good],court[good]])
    b=np.linalg.lstsq(x,y[good],rcond=None)[0]
    return float(-b[2])

def band(values, cuts, labels):
    values=np.asarray(values,float)
    out=np.asarray(labels,dtype=object)[np.digitize(values,cuts)]
    out[~np.isfinite(values)]='Missing'
    return out

def prepare(d,market,hfa):
    """Only pregame columns enter segment construction. Canonical away spread."""
    q=d.copy(); a,h=effective_ratings(q)
    early=week_early(q)
    post=boolean(q,'model_postseason') if 'model_postseason' in q else num(q,'season_week').gt(90)
    reg=np.where(post,'Postseason',np.where(early,'Early','Established'))
    venue=np.where(boolean(q,'neutral_site'),'Neutral','Court')
    gap=(a-h-hfa*(~boolean(q,'neutral_site')).astype(float)).to_numpy()
    sp=num(q,'away_spread').where(verified(q,'Spread')).to_numpy()
    edge=gap+sp
    total_off=(2*num(q,'prior_scoring_baseline_per_team')+rating_input(q,'away','osrs')+rating_input(q,'home','osrs')).to_numpy()
    total_line=num(q,'total_line').where(verified(q,'Total')).to_numpy()
    off_edge=total_off-total_line
    totalband=band(total_line,[135,145,155],['<135','135-<145','145-<155','155+'])
    q['structure_away_margin']=gap
    q['structure_cover_edge']=edge
    q['structure_total_off']=total_off
    q['structure_total_edge']=off_edge
    q['regime']=reg; q['venue']=venue; q['learned_home_court_points']=hfa
    if market=='Spread':
        b=band(np.abs(edge),[2,4,5,7,10],['<2','2-<4','4-<5','5-<7','7-<10','10+'])
        side=edge>=0
        role=np.where(sp==0,'Pickem',np.where(side==(sp<0),'Favorite','Underdog'))
        slope=(num(q,'away_srs_slope_28d')-num(q,'home_srs_slope_28d')).to_numpy()
        slope_role=np.where(early|~np.isfinite(slope)|np.isclose(slope,0),'Unavailable/flat',np.where(slope*edge>=0,'Confirms','Opposes'))
        core=[f'Edge {bb}|{rr}' for bb,rr in zip(b,reg)]
        context=[f'{c}|{r}' for c,r in zip(core,role)]
        full=[f'{c}|{v}|Slope {s}' for c,v,s in zip(context,venue,slope_role)]
        q['structural_side1']=side
        q['structural_role']=role; q['slope_agreement']=slope_role
    elif market=='Total':
        b=band(off_edge,[-12,-8,-4,0,4,8,12],['<-12','-12-<-8','-8-<-4','-4-<0','0-<4','4-<8','8-<12','12+'])
        side=off_edge>=0
        core=[f'Offense edge {bb}|{rr}' for bb,rr in zip(b,reg)]
        context=[f'{c}|Total {t}' for c,t in zip(core,totalband)]
        full=[f'{c}|{v}' for c,v in zip(context,venue)]
        q['structural_side1']=side
        q['structural_role']=np.where(side,'Over','Under')
    else:
        anchor=num(q,'away_ml_no_vig_probability').where(verified(q,'Moneyline')).to_numpy()
        priced=np.isfinite(anchor)
        awaydog=anchor<.5
        dog_odds=np.where(awaydog,num(q,'away_moneyline'),num(q,'home_moneyline'))
        oddsband=band(dog_odds,[250,400,700],['<+250','+250-<400','+400-<700','+700+'])
        favsrs=np.where(awaydog,h,a)
        favband=band(favsrs,[0,10],['<0','0-<10','10+'])
        dogedge=np.where(awaydog,edge,-edge)
        reverse=band(dogedge,[-5,0,5],['<-5','-5-<0','0-<5','5+'])
        mb=band(np.abs(gap),[5,10,15],['<5','5-<10','10-<15','15+'])
        core=[f'Dog {ob}|{rr}' if pp else f'Unpriced margin {m}|{rr}' for ob,rr,pp,m in zip(oddsband,reg,priced,mb)]
        context=[f'{c}|Total {t}|Favorite SRS {f}' if pp else c for c,t,f,pp in zip(core,totalband,favband,priced)]
        full=[f'{c}|Dog cover edge {e}' if pp else c for c,e,pp in zip(context,reverse,priced)]
        q['structural_side1']=np.where(priced,awaydog,gap>=0)
        q['structural_role']=np.where(priced,'Underdog','Winner forecast / unpriced')
        q['dog_cover_edge']=np.where(priced,dogedge,np.nan)
        q['favorite_effective_srs']=np.where(priced,favsrs,np.nan)
        q['ml_segment_has_verified_pair']=priced
    q['core_segment']=core; q['context_segment']=context; q['full_segment']=full
    return q

def cluster_info(y,p,dates,seasons):
    y,p=np.asarray(y,float),np.asarray(p,float)
    n=len(y)
    if n==0:return {'n':0,'n_eff':0.,'days':0,'seasons':0,'se':np.nan}
    r=y-p; centered=r-r.mean()
    daily=pd.DataFrame({'date':dates,'r':centered}).groupby('date').r.sum()
    g=len(daily)
    v=float(np.sum(daily.to_numpy()**2)/n**2*g/max(g-1,1))
    iid=max(float(np.mean(p*(1-p)))/n,1e-12)
    # Retain a season heterogeneity design effect, with no effective-N inflation.
    sf=pd.DataFrame({'season':seasons,'r':r}).groupby('season').r.agg(['mean','size'])
    if len(sf)>=2:
        within=float(np.mean(p*(1-p)))*float(np.mean(1/sf['size']))
        excess=max(0.,float(sf['mean'].var(ddof=1))-within)
        v=max(v,excess/len(sf))
    v=max(v,iid)
    return {'n':n,'n_eff':min(float(n),float(np.mean(p*(1-p)))/v),'days':g,'seasons':len(sf),'se':float(np.sqrt(v))}

def fit_cell(q,market):
    y=q.y.to_numpy(float); ok=np.isfinite(y); qq=q.loc[ok]
    yy=y[ok]; side=qq.structural_side1.to_numpy(bool)
    hits=np.where(side,yy,1-yy)
    if market=='Moneyline':
        p=qq.p_Market_Benchmark.to_numpy(float)
        # Calibrate the chosen structural side, irrespective of home/away.
        oriented_p=np.where(side,p,1-p)
        info=cluster_info(hits,oriented_p,qq.game_date,qq.season)
        z=logit(np.clip(oriented_p,1e-6,1-1e-6)); w=info['n_eff']/max(len(yy),1)
        obj=lambda delta: float(w*np.sum(np.logaddexp(0,z+delta)-hits*(z+delta))+.5*(PRIOR_N*.25)*delta**2)
        delta=float(minimize_scalar(obj,bounds=(-3,3),method='bounded').x) if len(yy) else 0.
        fitted=expit(z+delta)
        fisher=float(w*np.sum(fitted*(1-fitted))+PRIOR_N*.25)
        info.update(delta=delta,logit_se=1/np.sqrt(fisher),posterior_mean=np.nan,ci_low=np.nan,ci_high=np.nan)
    else:
        raw=float(hits.mean()) if len(hits) else .5
        info=cluster_info(hits,np.full(len(hits),raw),qq.game_date,qq.season)
        aa=25+raw*info['n_eff']; bb=25+(1-raw)*info['n_eff']
        lo,hi=beta.ppf([.025,.975],aa,bb)
        info.update(delta=0.,posterior_mean=aa/(aa+bb),alpha=aa,beta=bb,ci_low=float(lo),ci_high=float(hi))
    info['raw_structural_wins']=int(hits.sum()); info['raw_structural_win_rate']=float(hits.mean()) if len(hits) else np.nan
    info['prior_strength']=PRIOR_N; info['evidence_factor']=info['n_eff']/(info['n_eff']+PRIOR_N)
    info['latest_evidence_season']=int(qq.season.max()) if len(qq) else None
    info['health']='Watch' if info['n_eff']<100 or info['seasons']<2 else 'Stable'
    # Health is descriptive calibration drift, never a stake multiplier.
    if market!='Moneyline' and info['seasons']>=2:
        ss=qq.season.to_numpy(); last=ss==ss.max(); old=~last
        a=cluster_info(hits[last],np.full(last.sum(),info['posterior_mean']),qq.game_date.to_numpy()[last],ss[last])
        b=cluster_info(hits[old],np.full(old.sum(),info['posterior_mean']),qq.game_date.to_numpy()[old],ss[old])
        se=np.hypot(a['se'],b['se']); zz=(hits[last].mean()-hits[old].mean())/se if se>0 else 0.
        info['drift_z']=float(zz)
        if zz<=-3:info['health']='Degrading'
        elif zz<=-2:info['health']='Watch'
        elif zz>=2:info['health']='Strengthening'
    if market!='Moneyline':
        line=num(q,'away_spread' if market=='Spread' else 'total_line')
        ints=line.notna()&np.isclose(line,np.round(line))
        info['integer_push_rate']=float(q.loc[ints,'pushed'].mean()) if ints.any() else 0.
    else:info['integer_push_rate']=0.
    return info

def fit_regimes(hist,market):
    params={'market':market,'global':fit_cell(hist,market),'cells':{},'minimum_cell_effective_n':100,'minimum_cell_days':20}
    if market=='Moneyline':
        priced=boolean(hist,'ml_segment_has_verified_pair')
        params['global_by_anchor']={'Priced underdog':fit_cell(hist.loc[priced],market),'Unpriced winner forecast':fit_cell(hist.loc[~priced],market)}
    for level in ['core_segment','context_segment','full_segment']:
        cells={}
        for key,q in hist.groupby(level,sort=True):cells[str(key)]=fit_cell(q,market)
        params['cells'][level]=cells
    return params

def apply_regimes(params,q,market):
    pp=[]; selected=[]
    for row in q.itertuples(index=False):
        stats=params['global']; chosen='Global'; key='Global'
        if market=='Moneyline':
            key='Priced underdog' if row.ml_segment_has_verified_pair else 'Unpriced winner forecast'
            stats=params['global_by_anchor'][key]; chosen='Anchor group'
        for level in ['full_segment','context_segment','core_segment']:
            k=getattr(row,level); s=params['cells'][level].get(k)
            if s and s['n_eff']>=100 and s['days']>=20:
                stats=s; chosen=level; key=k; break
        if market=='Moneyline':
            orientation=1 if row.structural_side1 else -1
            p=float(expit(logit(np.clip(row.p_Market_Benchmark,1e-6,1-1e-6))+orientation*stats['delta']))
        else:p=stats['posterior_mean'] if row.structural_side1 else 1-stats['posterior_mean']
        pp.append(p); selected.append({'evidence_segment':key,'fallback_level':chosen,'market_health':params.get('market_health','Watch'),'market_health_price_season':params.get('market_health_price_season',np.nan),**stats})
    return np.asarray(pp),pd.DataFrame(selected,index=q.index)

def paired_test(q,candidate):
    if len(q)<200:return None
    yy=q.y.to_numpy(float); m=np.isfinite(yy); qq=q.loc[m]; yy=yy[m]
    if len(yy)<200 or qq.season.nunique()<2 or qq.game_date.nunique()<30:return None
    diff=(qq[f'p_{candidate}'].to_numpy()-yy)**2-(qq.p_Segment_Rule.to_numpy()-yy)**2
    mu=float(diff.mean())
    daily=pd.DataFrame({'d':qq.game_date,'r':diff-mu}).groupby('d').r.sum().to_numpy()
    se=float(np.sqrt(np.sum(daily**2)/len(yy)**2*len(daily)/max(len(daily)-1,1)))
    yearly=pd.DataFrame({'s':qq.season,'diff':diff}).groupby('s')['diff'].mean()
    good_years=int((yearly<0).sum())
    p=float(norm.cdf(mu/se)) if se>0 else (0. if mu<0 else 1.)
    return {'candidate':candidate,'n':len(yy),'seasons':len(yearly),'days':len(daily),'brier_difference_vs_rule':mu,'paired_se_date_cluster':se,'ci_low':mu-1.96*se,'ci_high':mu+1.96*se,'p_value_one_sided':p,'improvement_seasons':good_years,'consistent':good_years==len(yearly)}

def fit_routers(history,year):
    """Holm correction covers all markets, cells and challengers for this review."""
    tests=[]
    for market in MARKETS:
        h=history.loc[history.market==market]
        groups=[('Global',h),*list(h.groupby('core_segment',sort=True))]
        if market=='Moneyline':
            groups += [('Anchor: Priced underdog',h.loc[h.core_segment.str.startswith('Dog ',na=False)]),('Anchor: Unpriced winner forecast',h.loc[h.core_segment.str.startswith('Unpriced ',na=False)])]
        for key,q in groups:
            for c in MODELS[1:]:
                t=paired_test(q,c)
                if t:tests.append({'market':market,'routing_segment':key,'decision_before_season':year,**t})
    ordered=sorted(tests,key=lambda t:t['p_value_one_sided']); prev=0.
    for i,t in enumerate(ordered):
        prev=max(prev,min(1.,t['p_value_one_sided']*(len(ordered)-i)))
        t['holm_p_value']=prev
        t['eligible_promotion']=bool(prev<.05 and t['consistent'] and t['brier_difference_vs_rule']<0)
    routers={m:{'Global':'Segment_Rule','anchors':{},'cells':{}} for m in MARKETS}
    for m in MARKETS:
        keys=set(t['routing_segment'] for t in tests if t['market']==m)
        for key in keys:
            eligible=[t for t in tests if t['market']==m and t['routing_segment']==key and t['eligible_promotion']]
            if eligible:
                best=min(eligible,key=lambda t:t['brier_difference_vs_rule'])['candidate']
                if key=='Global':routers[m]['Global']=best
                elif key.startswith('Anchor: '):routers[m]['anchors'][key.removeprefix('Anchor: ')]=best
                else:routers[m]['cells'][key]=best
    return routers,pd.DataFrame(tests)

def route(q,router):
    chosen=[]
    for k in q.core_segment:
        anchor='Priced underdog' if k.startswith('Dog ') else 'Unpriced winner forecast'
        chosen.append(router['cells'].get(k,router.get('anchors',{}).get(anchor,router['Global'])))
    p=np.array([q.iloc[i][f'p_{c}'] for i,c in enumerate(chosen)],float)
    return p,np.asarray(chosen)

def make_ledger(q,p,evidence,market,chosen):
    out=q[[c for c in ['game_id','season','game_date','away_team','home_team','model_week','model_week_source','source_week_codes','model_srs_snapshot_season','self_made_control_observations','source_control_only_game','away_spread','total_line','regime','venue','core_segment','context_segment','full_segment','structural_role','slope_agreement','structure_away_margin','structure_cover_edge','structure_total_off','structure_total_edge','learned_home_court_points'] if c in q]].copy()
    out['market']=market; out['selected_model']=chosen; out['p_positive']=p
    o1,o0=[num(q,c).to_numpy() for c in odds_columns(market)]
    b1,b0=odds_profit(o1),odds_profit(o0)
    ev1,ev0=b1*p-(1-p),b0*(1-p)-p
    both=np.isfinite(b1)&np.isfinite(b0)
    side=np.where(both,ev1>=ev0,p>=.5)
    selp=np.where(side,p,1-p); odds=np.where(side,o1,o0); b=np.where(side,b1,b0)
    be=1/(1+b); ce=b*selp-(1-selp)
    factor=evidence.evidence_factor.to_numpy(); neff=evidence.n_eff.to_numpy()
    # Conditional nonpush probability; push does not change Kelly's solution.
    push=evidence.integer_push_rate.to_numpy()
    if market!='Moneyline':
        line=num(q,'away_spread' if market=='Spread' else 'total_line').to_numpy()
        push=np.where(np.isfinite(line)&np.isclose(line,np.round(line)),push,0.)
    full=np.maximum(0,ce/b)
    quote_ok=verified(q,market).to_numpy()&np.isfinite(b)
    safe=boolean(q,'pregame_no_future_results').to_numpy()
    eligible=quote_ok&safe&(neff>=1)&(ce>0)
    stat_adjusted=np.where(eligible,full*factor,0.)
    edgeconf=norm.cdf((selp-be)/np.sqrt(selp*(1-selp)/np.maximum(neff,1)))
    tier=np.where(ce<=0,'Pass',np.where((neff>=200)&(edgeconf>=.9),'B+',np.where((neff>=75)&(edgeconf>=.75),'B','Lean')))
    # A requires an independently validated priced regime; no automatic A from p.
    tier=np.where(~np.isfinite(b),np.where(selp>.5,'Lean','Pass'),tier)
    out['selected_side']=np.where(side,*(('Over','Under') if market=='Total' else ('Away','Home')))
    out['selected_probability']=selp;out['quoted_odds']=odds;out['break_even_p']=be
    anchor=num(q,'away_ml_no_vig_probability').where(verified(q,'Moneyline')).to_numpy() if market=='Moneyline' else np.where(both,(1/(1+b1))/(1/(1+b1)+1/(1+b0)),np.nan)
    out['selected_market_no_vig_p']=np.where(side,anchor,1-anchor)
    out['probability_edge_no_vig']=selp-out.selected_market_no_vig_p
    out['expected_unit_net_at_quote']=(1-push)*ce;out['full_kelly']=full
    out['raw_n']=evidence.n.to_numpy();out['effective_n']=neff
    out['evidence_factor']=factor;out['probability_positive_edge_approx']=edgeconf
    out['adjusted_kelly_before_portfolio']=stat_adjusted
    out['portfolio_factor']=1.;out['final_recommended_kelly']=stat_adjusted
    out['calibration_health']=evidence.health.to_numpy()
    out['market_financial_health']=evidence.market_health.to_numpy()
    severity={'Strengthening':0,'Stable':1,'Watch':2,'Degrading':3,'Broken':4}
    out['health']=[m if severity[m]>severity[c] else c for m,c in zip(out.market_financial_health,out.calibration_health)]
    out['market_health_price_season']=evidence.market_health_price_season.to_numpy()
    out['health_stake_multiplier']=1.
    out['evidence_segment']=evidence.evidence_segment.to_numpy();out['fallback_level']=evidence.fallback_level.to_numpy()
    out['latest_evidence_season']=evidence.latest_evidence_season.to_numpy()
    out['tier']=tier;out['pricing_status']=np.where(quote_ok,'Verified quote',np.where(np.isfinite(b),'Quote time unverified','Unpriced'))
    out['stake_eligible']=eligible;out['estimated_push_probability']=push
    yy,pushed=targets(q,market); yy=yy.to_numpy(); pushed=pushed.to_numpy()
    selected_y=np.where(side,yy,1-yy)
    out['result']=np.where(pushed,'Push',np.where(np.isfinite(selected_y),np.where(selected_y==1,'Win','Loss'),'Unknown'))
    out['realized_unit_net']=np.where(np.isfinite(b),np.where(pushed,0,np.where(selected_y==1,b,np.where(selected_y==0,-1,np.nan))),np.nan)
    if market in ['Spread','Total']:
        sp=np.maximum(p,1-p); sy=np.where(p>=.5,yy,1-yy); sb=100/110
        out['scenario_minus110_positive_ev']=sb*sp-(1-sp)>0
        out['scenario_minus110_unit_net']=np.where(pushed,0,np.where(sy==1,sb,np.where(sy==0,-1,np.nan)))
    out['cash_bet_status']='Simulation / no bet executed'
    return out

def apply_portfolio_budget(ledger):
    """Only a cash budget constraint, not an optimized correlation haircut."""
    ledger=ledger.copy()
    daily=ledger.groupby('game_date').adjusted_kelly_before_portfolio.transform('sum')
    ledger['portfolio_factor']=np.minimum(1.,1./np.maximum(daily,1e-12))
    ledger['final_recommended_kelly']=ledger.adjusted_kelly_before_portfolio*ledger.portfolio_factor
    ledger['portfolio_budget_policy']='At most 100% of bankroll allocated per calendar day; no correlation optimizer'
    return ledger

def score_bundle(bundle,d,bankroll=None):
    frames=[]
    for market in MARKETS:
        dm=d.loc[market_mask(d,market)].copy().reset_index(drop=True)
        if not len(dm):continue
        q=prepare(dm,market,bundle['home_court_points'])
        spec=bundle['markets'][market]
        for c in MODELS[1:]:q[f'p_{c}']=calibrate(spec['calibrators'][c],predict_base(spec['base_models'][c],dm,market))
        q['p_Segment_Rule'],evidence=apply_regimes(spec['regimes'],q,market)
        p,chosen=route(q,spec['router'])
        frames.append(make_ledger(q,p,evidence,market,chosen))
    out=apply_portfolio_budget(pd.concat(frames,ignore_index=True)) if frames else pd.DataFrame()
    if bankroll is not None:out['recommended_stake']=out.final_recommended_kelly*float(bankroll)
    return out
