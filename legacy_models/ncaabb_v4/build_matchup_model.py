"""Rebuild structural segments using cached chronological base-model predictions."""
from __future__ import annotations
import argparse, json, shutil, sys, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss,log_loss
from ncaabb_models import boolean,market_mask,targets
from ncaabb_matchup import *

def clean_json(x):
    if isinstance(x,dict):return {str(k):clean_json(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean_json(v) for v in x]
    if isinstance(x,np.generic):return clean_json(x.item())
    if isinstance(x,float) and not np.isfinite(x):return None
    return x

def dump(path,value):path.write_text(json.dumps(clean_json(value),indent=2))

def roi_interval(ledger,mask,weighted=False):
    q=ledger.loc[mask&ledger.realized_unit_net.notna()].copy()
    if len(q)<2:return np.nan,np.nan
    w=q.final_recommended_kelly.to_numpy() if weighted else np.ones(len(q))
    daily=pd.DataFrame({'d':q.game_date,'net':q.realized_unit_net.to_numpy()*w,'w':w}).groupby('d')[['net','w']].sum()
    if len(daily)<2:return np.nan,np.nan
    rng=np.random.default_rng(27052025);ix=rng.integers(0,len(daily),(1000,len(daily)))
    den=daily.w.to_numpy()[ix].sum(axis=1);ratio=daily.net.to_numpy()[ix].sum(axis=1)/np.maximum(den,1e-12)
    return tuple(np.quantile(ratio,[.025,.975]))

def metrics(q,ledger,market,year,candidate,p):
    y=q.y.to_numpy(float);good=np.isfinite(y)
    priced=ledger.pricing_status.eq('Verified quote')&ledger.expected_unit_net_at_quote.gt(0)&ledger.realized_unit_net.notna()
    hit=((p[good]>=.5)==y[good]).mean()
    lo,hi=roi_interval(ledger,priced)
    w=ledger.loc[priced,'final_recommended_kelly'];net=ledger.loc[priced,'realized_unit_net']
    wr=(w*net).sum()/w.sum() if w.sum()>0 else np.nan
    wl,wh=roi_interval(ledger,priced,weighted=True)
    scenario=ledger.get('scenario_minus110_positive_ev',pd.Series(False,index=ledger.index)).fillna(False)
    return {'market':market,'season':year,'candidate':candidate,'games':len(q),'nonpush_n':int(good.sum()),'pushes':int(q.pushed.sum()),'hit_rate':float(hit),'brier':float(brier_score_loss(y[good],p[good])),'log_loss':float(log_loss(y[good],p[good],labels=[0,1])),'actual_price_bets':int(priced.sum()),'actual_price_flat_roi':float(net.mean()) if len(net) else np.nan,'roi_ci_low':lo,'roi_ci_high':hi,'actual_price_net_units':float(net.sum()) if len(net) else np.nan,'evidence_adjusted_roi':wr,'adjusted_roi_ci_low':wl,'adjusted_roi_ci_high':wh,'scenario_minus110_bets':int(scenario.sum()),'scenario_minus110_roi':float(ledger.loc[scenario,'scenario_minus110_unit_net'].mean()) if scenario.any() else np.nan,'evaluation_role':'2022 development' if year==2022 else ('Retrospective 2025 test; previously viewed' if year==2025 else 'Chronological validation')}

def brier_comparison(q,p,reference):
    y=q.y.to_numpy(float);v=np.isfinite(y)
    dif=(p[v]-y[v])**2-(reference[v]-y[v])**2
    daily=pd.DataFrame({'date':q.loc[v,'game_date'],'diff':dif}).groupby('date')['diff'].agg(['sum','size'])
    rng=np.random.default_rng(27052025);ix=rng.integers(0,len(daily),(1000,len(daily)))
    sims=daily['sum'].to_numpy()[ix].sum(1)/daily['size'].to_numpy()[ix].sum(1)
    return {'brier_difference':float(dif.mean()),'ci_low':float(np.quantile(sims,.025)),'ci_high':float(np.quantile(sims,.975))}

def build(source,out):
    start=time.time();out.mkdir(parents=True,exist_ok=True);(out/'models').mkdir(exist_ok=True)
    d=pd.read_csv(source/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv',low_memory=False,dtype={'game_id':str})
    wf=pd.read_csv(source/'NCAABB_WALK_FORWARD_PREDICTIONS.csv',dtype={'game_id':str})
    if d.game_id.duplicated().any():raise ValueError('Duplicated games')
    safe=d.loc[boolean(d,'d1_vs_d1') & boolean(d,'model_week_rule_safe')]
    if not boolean(safe,'pregame_no_future_results').all():raise ValueError('Unsafe rating flag')
    cut=pd.to_datetime(safe.rating_max_result_date,errors='coerce');dt=pd.to_datetime(safe.game_date)
    if (cut>=dt).any():raise ValueError('Rating cutoff leak')
    hf={}
    for year in [2021,2022,2023,2024,2025,2026]:
        train=safe.loc[(safe.season<year)] if year>2021 else safe.loc[(safe.season==2021)&(safe.game_date<'2021-02-07')]
        hf[year]=estimate_hfa(train)
    dump(out/'SPECIFICATION.json',{'architecture':'Football-style matchup segments with empirical calibration and tested challenger routing','created':'2026-10-06 UTC / 2026-10-05 Chicago','early_rule':'Weeks below 8 use previous-season SRS and component ratings; Week 8+ uses current pregame ratings; weeks >90 are a separate postseason regime','home_court':'OLS-estimated court coefficient from earlier outcomes only; neutral=0','spread_absolute_edge_cuts':[2,4,5,7,10],'spread_context':['early/established/postseason','favorite/dog/pickem','court/neutral','slope confirms/opposes/unavailable'],'total_signed_offense_edge_cuts':[-12,-8,-4,0,4,8,12],'total_context':['early/established/postseason','market total <135 / 135-<145 / 145-<155 / 155+','venue'],'ml_dog_odds_cuts':[250,400,700],'ml_favorite_srs_cuts':[0,10],'ml_dog_cover_edge_cuts':[-5,0,5],'ml_context':['early/established/postseason','market total band','favorite quality','reverse SRS disagreement'],'ml_calibration_orientation':'Offset applies to underdog for verified paired prices; otherwise structural winner side. Convert back to away probability with signed offset. Priced/unpriced global fallbacks are separate.', 'ml_probability_anchor':'Verified paired no-vig quote; otherwise explicitly labeled spread proxy winner forecast','fallback':'Deepest full -> context -> core with N_eff>=100 and >=20 game dates; otherwise global','calibration':'Spread/total Beta(25,25) with effective counts. ML market-logit offset with 50 prior-equivalent observations. No uniform probability haircut.','effective_n':'Minimum information implied by independent Bernoulli variance, date clusters, and excess season heterogeneity; <= raw N','challenger_selection':'Earlier-year OOS paired Brier differences; >=200 games, >=2 seasons, >=30 dates; improved in every prior season and Holm-adjusted one-sided clustered p<.05. Full family includes every market, core cell, priced/unpriced ML anchor group and challenger.','tier_A':'No promotion without independent priced validation following model-selection; current 2024/2025 prices absent, so no Tier A assigned','sizing':'Full Kelly x N_eff/(N_eff+50); health metadata has no discretionary multiplier','portfolio':'100% daily bankroll allocation constraint only; correlation optimization not estimated','2025_status':'Excluded from every fit/selection for frozen model but previously inspected. Revised-model test is retrospective, not a fresh confirmatory holdout.','football_threshold_status':'Analogous structural axes; football probabilities and betting approvals are not transferred to basketball','base_models':'Base estimators retrained under the user Week 8 rating policy; legacy v1 predictions retained only as a historical reference','home_court_points_by_evaluation_season':hf})
    allq={}; raw_files={}
    for market in MARKETS:
        raw=pd.read_csv(source/f'{market.upper()}_CORE_OUT_OF_FOLD.csv',dtype={'game_id':str})
        raw_files[market]=raw
        q=raw.merge(d.drop(columns=['season','game_date']),on='game_id',validate='one_to_one')
        for c in MODELS[1:]:q[f'p_{c}']=q[f'raw_{c}']
        z=wf.loc[wf.market==market].set_index('game_id')
        for c in MODELS[1:]:q[f'p_{c}']=q.game_id.map(z[f'p_{c}']).fillna(q[f'p_{c}'])
        parts=[prepare(g,market,hf[int(year)]) for year,g in q.groupby('season')]
        allq[market]=pd.concat(parts,ignore_index=True)
    past=[];scores=[];comparisons=[];ledgers=[];tests=[];evidence_rows=[];frozen=None;production=None
    old_frozen=joblib.load(source/'models/NCAABB_FROZEN_2025_VALIDATION.joblib')
    old_prod=joblib.load(source/'models/NCAABB_PRODUCTION_V1.joblib')
    for year in [2022,2023,2024,2025,2026]:
        hist_preds=pd.concat(past,ignore_index=True) if past else pd.DataFrame(columns=['market','season','core_segment'])
        routers,tt=fit_routers(hist_preds,year);tests.append(tt)
        current_bundle={'model_version':'V4 role-oriented moneyline calibration','purpose':'Frozen retrospective 2025 test' if year==2025 else 'Production candidate refit through 2025','trained_through_season':year-1,'home_court_points':hf[year],'markets':{}}
        for market in MARKETS:
            aq=allq[market];hist=aq.loc[aq.season<year].copy();test=aq.loc[aq.season==year].copy().reset_index(drop=True)
            regimes=fit_regimes(hist,market)
            priced_history=[s for s in scores if s['market']==market and s['candidate']=='Matchup_Champion_v4' and 2023<=s['season']<year and s['actual_price_bets']>0]
            latest=max(priced_history,key=lambda s:s['season']) if priced_history else None
            regimes['market_health']='Degrading' if latest and latest['roi_ci_high']<0 else ('Stable' if latest and latest['roi_ci_low']>0 else 'Watch')
            regimes['market_health_price_season']=latest['season'] if latest else np.nan
            base=(old_frozen if year==2025 else old_prod)['markets'][market]
            current_bundle['markets'][market]={'base_models':base['base_models'],'calibrators':base['calibrators'],'regimes':regimes,'router':routers[market]}
            for level,cells in regimes['cells'].items():
                for key,stats in cells.items():evidence_rows.append({'fit_before_season':year,'market':market,'level':level,'segment':key,**stats})
            if year==2026:continue
            rule,ev=apply_regimes(regimes,test,market);test['p_Segment_Rule']=rule
            test['market']=market
            p,chosen=route(test,routers[market]);test['p_Matchup_Champion_v4']=p;test['chosen_model']=chosen
            test['p_Previous_v1']=test.game_id.map(wf.loc[wf.market==market].set_index('game_id').p_Segment_Champion_v1)
            final_led=make_ledger(test,p,ev,market,chosen)
            final_led['fit_before_season']=year
            ledgers.append(final_led)
            for c in MODELS+['Matchup_Champion_v4','Previous_v1']:
                pp=test[f'p_{c}'].to_numpy();ll=make_ledger(test,pp,ev,market,np.full(len(test),c))
                scores.append(metrics(test,ll,market,year,c,pp))
            if year==2025:
                for c in ['Previous_v1','Market_Benchmark','Segment_Rule','RandomForest']:
                    comparisons.append({'market':market,'reference':c,**brier_comparison(test,p,test[f'p_{c}'].to_numpy())})
            past.append(test)
            print(f'{year} {market}: {len(test)} games; global={routers[market]["Global"]}; local overrides={len(routers[market]["cells"])}',flush=True)
        if year==2025:frozen=current_bundle
        elif year==2026:production=current_bundle
    pd.DataFrame(scores).to_csv(out/'NCAABB_V4_MODEL_COMPARISON.csv',index=False)
    pd.DataFrame(comparisons).to_csv(out/'NCAABB_V4_2025_PAIRED_BRIER.csv',index=False)
    pred=pd.concat(past,ignore_index=True)
    pred[['game_id','season','game_date','market','y','pushed','regime','core_segment','context_segment','full_segment','chosen_model']+[f'p_{c}' for c in MODELS+['Matchup_Champion_v4','Previous_v1']]].to_csv(out/'NCAABB_V4_WALK_FORWARD_PREDICTIONS.csv',index=False)
    ledger=apply_portfolio_budget(pd.concat(ledgers,ignore_index=True))
    ledger.to_csv(out/'NCAABB_V4_WALK_FORWARD_SCORING.csv',index=False)
    ledger.loc[ledger.season==2025].to_csv(out/'NCAABB_V4_2025_SCORING.csv',index=False)
    pd.concat(tests,ignore_index=True).to_csv(out/'NCAABB_V4_CHALLENGER_SELECTION_TESTS.csv',index=False)
    pd.DataFrame(evidence_rows).to_csv(out/'NCAABB_V4_REGIME_PARAMETERS.csv',index=False)
    # Exact descriptive regime results; previously frozen decisions are preserved.
    split=[]
    for (year,market,core),q in pred.groupby(['season','market','core_segment']):
        y=q.y.to_numpy();valid=np.isfinite(y);p=q.p_Matchup_Champion_v4.to_numpy()
        ll=ledger.loc[(ledger.season==year)&(ledger.market==market)&(ledger.core_segment==core)]
        hit=(p[valid]>=.5)==y[valid]
        priced=ll.pricing_status.eq('Verified quote')&ll.expected_unit_net_at_quote.gt(0)&ll.realized_unit_net.notna()
        lo,hi=roi_interval(ll,priced)
        split.append({'season':year,'market':market,'core_segment':core,'games':len(q),'nonpush_n':int(valid.sum()),'wins':int(hit.sum()),'losses':int(valid.sum()-hit.sum()),'pushes':int(q.pushed.sum()),'hit_rate':float(hit.mean()),'brier':float(np.mean((p[valid]-y[valid])**2)),'selected_models':','.join(sorted(set(q.chosen_model))),'actual_price_bets':int(priced.sum()),'actual_price_roi':float(ll.loc[priced,'realized_unit_net'].mean()) if priced.any() else np.nan,'roi_ci_low':lo,'roi_ci_high':hi,'mean_effective_n':float(ll.effective_n.mean()),'most_used_evidence_level':ll.fallback_level.mode().iloc[0]})
    pd.DataFrame(split).to_csv(out/'NCAABB_V4_REGIME_VALIDATION.csv',index=False)
    coverage=[]
    for year,g in safe.groupby('season'):
        for market in MARKETS:
            mask=market_mask(g,market)
            prices=verified(g,market)&num(g,odds_columns(market)[0]).notna()&num(g,odds_columns(market)[1]).notna()
            coverage.append({'season':int(year),'market':market,'d1_game_opportunities':len(g),'probability_gradeable_games':int(mask.sum()),'probability_coverage':float(mask.mean()),'paired_priced_games':int((prices&mask).sum()),'paired_price_coverage':float((prices&mask).mean())})
    pd.DataFrame(coverage).to_csv(out/'NCAABB_V4_COVERAGE.csv',index=False)
    for b,name in [(frozen,'NCAABB_V4_FROZEN_2025.joblib'),(production,'NCAABB_V4_PRODUCTION_CANDIDATE.joblib')]:joblib.dump(b,out/'models'/name,compress=3)
    loaded=joblib.load(out/'models/NCAABB_V4_FROZEN_2025.joblib')
    rerun=score_bundle(loaded,d.loc[d.season==2025]);saved=ledger.loc[ledger.season==2025]
    compare=rerun.merge(saved[['game_id','market','p_positive']],on=['game_id','market'],validate='one_to_one',suffixes=('_reload','_saved'))
    error=float(np.abs(compare.p_positive_reload-compare.p_positive_saved).max())
    if len(compare)!=len(saved) or error>1e-8:raise ValueError(f'Frozen reproduction failure {error}')
    if rerun.final_recommended_kelly.ne(0).any():raise ValueError('2025 missing quotes generated a stake')
    examples=pd.read_csv(source/'NCAABB_SCORING_INPUT_EXAMPLES_HISTORICAL.csv',dtype={'game_id':str})
    example_score=score_bundle(joblib.load(out/'models/NCAABB_V4_PRODUCTION_CANDIDATE.joblib'),examples,bankroll=1000)
    if not example_score.result.eq('Unknown').all() or example_score.realized_unit_net.notna().any():raise ValueError('Future outcome invented')
    example_score.to_csv(out/'NCAABB_V4_SCORING_OUTPUT_EXAMPLES.csv',index=False)
    examples.to_csv(out/'NCAABB_V4_SCORING_INPUT_EXAMPLES.csv',index=False)
    pd.DataFrame(columns=examples.columns).to_csv(out/'NCAABB_V4_SCORING_INPUT_TEMPLATE.csv',index=False)
    # Outcome permutation must have no effect on segment assignment or probabilities.
    perm=d.loc[d.season==2025].copy();rng=np.random.default_rng(27052025)
    for c in ['actual_away_margin','actual_total','away_score','home_score']:perm[c]=rng.permutation(perm[c])
    perm_score=score_bundle(loaded,perm)
    leakage_error=float(np.abs(perm_score.p_positive.to_numpy()-rerun.p_positive.to_numpy()).max())
    for market in MARKETS:pd.testing.assert_frame_equal(feature_table(d.loc[d.season==2025],market),feature_table(perm,market))
    if leakage_error>1e-12:raise ValueError('Outcome feature leakage')
    if (ledger.effective_n>ledger.raw_n+1e-9).any():raise ValueError('Effective N inflation')
    if ledger.latest_evidence_season.ge(ledger.season).any():raise ValueError('Future segment evidence')
    if not ledger.health_stake_multiplier.eq(1).all():raise ValueError('Discretionary health sizing')
    if ledger.groupby(['season','game_date']).final_recommended_kelly.sum().gt(1+1e-8).any():raise ValueError('Daily allocation overdraw')
    checks={'frozen_trained_through':2024,'frozen_routing_uses_outcomes_through':2024,'production_trained_through':2025,'2025_previously_viewed':True,'serialization_rows':len(compare),'serialization_max_probability_error':error,'outcome_permutation_probability_error':leakage_error,'outcome_permutation_allowlisted_features_identical':True,'outcome_permutation_tolerance':1e-12,'effective_n_never_exceeds_raw_n':True,'all_frozen_segment_evidence_precedes_test_season':True,'health_stake_multiplier_always_one':True,'2025_verified_stakes_zero':True,'future_score_without_outcomes_verified':True,'daily_cash_budget_checked':True,'home_court_by_season':hf,'elapsed_seconds':time.time()-start}
    dump(out/'NCAABB_V4_VALIDATION_CHECKS.json',checks)
    dump(out/'NCAABB_V4_ROUTING_FROZEN_2025.json',{m:frozen['markets'][m]['router'] for m in MARKETS})
    dump(out/'NCAABB_V4_ROUTING_PRODUCTION.json',{m:production['markets'][m]['router'] for m in MARKETS})
    # Reusable input checkpoint; original source package remains independently intact.
    cache=out/'training_cache';cache.mkdir(exist_ok=True)
    for f in ['NCAABB_DB_CLEAN_REBUILT_2021_2025.csv','NCAABB_WALK_FORWARD_PREDICTIONS.csv','SPREAD_CORE_OUT_OF_FOLD.csv','MONEYLINE_CORE_OUT_OF_FOLD.csv','TOTAL_CORE_OUT_OF_FOLD.csv','NCAABB_SCORING_INPUT_EXAMPLES_HISTORICAL.csv']:
        if (source/f).resolve()!=(cache/f).resolve():shutil.copy2(source/f,cache/f)
    (cache/'models').mkdir(exist_ok=True)
    for f in ['NCAABB_FROZEN_2025_VALIDATION.joblib','NCAABB_PRODUCTION_V1.joblib']:
        if (source/'models'/f).resolve()!=(cache/'models'/f).resolve():shutil.copy2(source/'models'/f,cache/'models'/f)
    print(json.dumps(clean_json(checks)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.source.resolve(),a.output.resolve())
