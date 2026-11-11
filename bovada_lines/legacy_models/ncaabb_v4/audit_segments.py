"""Retrospective fixed-cell audit; does not change frozen models or routing."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import norm
from ncaabb_models import num,odds_columns,odds_profit
from ncaabb_matchup import cluster_info

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'segment_audit'
OUT.mkdir(exist_ok=True)
d=pd.read_csv(ROOT/'NCAABB_DB_CLEAN_REBUILT_2021_2025.csv',dtype={'game_id':str},low_memory=False)
l=pd.read_csv(ROOT/'NCAABB_V4_WALK_FORWARD_SCORING.csv',dtype={'game_id':str},low_memory=False)
p=pd.read_csv(ROOT/'NCAABB_V4_WALK_FORWARD_PREDICTIONS.csv',dtype={'game_id':str})
assert not l.duplicated(['game_id','market']).any()
cols=['game_id','away_ml_no_vig_probability']+list({c for m in ['Spread','Moneyline','Total'] for c in odds_columns(m)})
q=l.merge(p[['game_id','market','y','pushed','p_Segment_Rule','p_Market_Benchmark']],on=['game_id','market'],validate='one_to_one').merge(d[cols],on='game_id',validate='many_to_one')
q['structural_hit']=np.nan;q['structural_quote_return']=np.nan;q['structural_break_even']=np.nan
for market,ix in q.groupby('market').groups.items():
    s=q.loc[ix]
    if market=='Spread':side=s.structure_cover_edge.ge(0)
    elif market=='Total':side=s.structure_total_edge.ge(0)
    else:side=pd.Series(np.where(s.structural_role.eq('Underdog'),s.away_ml_no_vig_probability.lt(.5),s.structure_away_margin.ge(0)),index=s.index)
    hit=s.y.where(side,1-s.y)
    a,b=odds_columns(market);price=np.where(side,num(s,a),num(s,b));profit=odds_profit(price)
    priced=s.pricing_status.eq('Verified quote')&np.isfinite(profit)
    q.loc[ix,'structural_hit']=hit
    q.loc[ix,'structural_quote_return']=np.where(priced,np.where(s.pushed,0,np.where(hit==1,profit,-1)),np.nan)
    q.loc[ix,'structural_break_even']=np.where(priced,1/(1+profit),np.nan)
q['champion_ev_quote_return']=q.realized_unit_net.where(q.pricing_status.eq('Verified quote')&q.expected_unit_net_at_quote.gt(0))
q['champion_hit']=((q.p_positive>=.5)==q.y).astype(float).where(q.y.notna())

def returns_stats(s,c):
    t=s.loc[s[c].notna(),['game_date',c]]
    if len(t)==0:return {'n':0,'roi':np.nan,'se':np.nan,'ci_low':np.nan,'ci_high':np.nan,'days':0,'p_one_sided':np.nan}
    mu=float(t[c].mean());daily=(t[c]-mu).groupby(t.game_date).sum();g=len(daily)
    se=float(np.sqrt((daily**2).sum()/len(t)**2*g/max(g-1,1))) if g>1 else np.nan
    return {'n':len(t),'roi':mu,'se':se,'ci_low':mu-1.96*se,'ci_high':mu+1.96*se,'days':g,'p_one_sided':float(norm.sf(mu/se)) if np.isfinite(se) and se>0 else np.nan}

rows=[]
for level in ['core_segment','context_segment','full_segment']:
 for (market,key,year),s in q.groupby(['market',level,'season']):
    v=s.y.notna();h=s.loc[v,'structural_hit'];info=cluster_info(h,np.full(len(h),h.mean()),s.loc[v,'game_date'],s.loc[v,'season'])
    row={'level':level,'market':market,'segment':key,'season':int(year),'games':len(s),'nonpush_n':int(v.sum()),'pushes':int(s.pushed.sum()),'structural_wins':int(h.sum()),'structural_hit_rate':h.mean(),'structural_effective_n':info['n_eff'],'champion_hit_rate':s.champion_hit.mean(),'champion_brier':((s.loc[v,'p_positive']-s.loc[v,'y'])**2).mean(),'rule_brier':((s.loc[v,'p_Segment_Rule']-s.loc[v,'y'])**2).mean(),'benchmark_brier':((s.loc[v,'p_Market_Benchmark']-s.loc[v,'y'])**2).mean(),'selected_models':','.join(sorted(s.selected_model.unique()))}
    for prefix,c in [('structural_priced','structural_quote_return'),('champion_ev_priced','champion_ev_quote_return')]:row.update({prefix+'_'+k:v for k,v in returns_stats(s,c).items()})
    rows.append(row)
season=pd.DataFrame(rows);season.to_csv(OUT/'NCAABB_V4_SEGMENTS_BY_SEASON.csv',index=False)

summaries=[]
for (level,market,key),ss in season.groupby(['level','market','segment']):
    s=q.loc[(q.market==market)&q[level].eq(key)&q.season.isin([2022,2023])]
    row={'level':level,'market':market,'segment':key,'audit_role':'Retrospective exploratory; no post-selection independent priced validation'}
    for policy,col in [('structural','structural_quote_return'),('champion_ev','champion_ev_quote_return')]:
        stats=returns_stats(s,col);row.update({policy+'_'+k:v for k,v in stats.items()})
        subset=ss.loc[ss.season.isin([2022,2023])]
        enough=len(subset)==2 and subset[policy.replace('structural','structural_priced').replace('champion_ev','champion_ev_priced')+'_n'].ge(100).all()
        prefix=policy+'_priced'
        row[policy+'_adequate_two_priced_seasons']=bool(enough)
        row[policy+'_positive_both_priced_seasons']=bool(enough and subset[prefix+'_roi'].gt(0).all())
        for year in [2022,2023,2024,2025]:
            t=ss.loc[ss.season==year]
            for metric in ['n','roi']:
                row[f'{policy}_{year}_{metric}']=t[prefix+'_'+metric].iloc[0] if len(t) else np.nan
    for year in [2022,2023,2024,2025]:
        t=ss.loc[ss.season==year]
        row[f'hit_{year}']=t.structural_hit_rate.iloc[0] if len(t) else np.nan
        row[f'games_{year}']=t.nonpush_n.iloc[0] if len(t) else 0
    summaries.append(row)
summary=pd.DataFrame(summaries)
# One pooled multiplicity family includes both policies, all markets and levels.
family=[]
for idx,row in summary.iterrows():
 for policy in ['structural','champion_ev']:
    if row[policy+'_adequate_two_priced_seasons'] and np.isfinite(row[policy+'_p_one_sided']):family.append((row[policy+'_p_one_sided'],idx,policy))
prev=0
for rank,(pval,idx,policy) in enumerate(sorted(family)):
    prev=max(prev,min(1,float(pval)*(len(family)-rank)))
    summary.loc[idx,policy+'_holm_p']=prev
for policy in ['structural','champion_ev']:
    if policy+'_holm_p' not in summary:summary[policy+'_holm_p']=np.nan
    summary[policy+'_screen_pass']=summary[policy+'_positive_both_priced_seasons']&summary[policy+'_holm_p'].lt(.05)
summary['research_status']=np.where(summary.structural_screen_pass|summary.champion_ev_screen_pass,'B+ research candidate; price validation still needed',np.where((summary.structural_positive_both_priced_seasons&summary.structural_ci_low.gt(0))|(summary.champion_ev_positive_both_priced_seasons&summary.champion_ev_ci_low.gt(0)),'B research candidate; independent validation needed',np.where(summary.structural_positive_both_priced_seasons|summary.champion_ev_positive_both_priced_seasons,'Lean research watchlist; uncertain or inconsistent',np.where(summary.structural_roi.gt(0)|summary.champion_ev_roi.gt(0),'Exploratory positive estimate; repeatability unproven','Negative/flat estimate; no cash promotion'))))
summary.loc[summary.structural_n.lt(100),'research_status']='Insufficient priced observations (<100)'
summary.loc[summary.structural_n.eq(0),'research_status']='Unpriced forecast / cash evidence unavailable'
summary.to_csv(OUT/'NCAABB_V4_SEGMENT_REPEATABILITY.csv',index=False)

# Exposes calibration by rating regime and pricing status; no probability haircut.
cal=[]
for (year,market,regime,pricing),s in q.groupby(['season','market','regime','pricing_status']):
    s=s.loc[s.y.notna()].copy();s['prob_bin']=pd.cut(s.p_positive,[0,.1,.2,.3,.4,.45,.5,.55,.6,.7,.8,.9,1],include_lowest=True)
    for bucket,t in s.groupby('prob_bin',observed=True):
        cal.append({'season':year,'market':market,'regime':regime,'pricing_status':pricing,'probability_bin':str(bucket),'n':len(t),'mean_probability':t.p_positive.mean(),'actual_positive_rate':t.y.mean(),'calibration_gap':t.p_positive.mean()-t.y.mean(),'brier':((t.p_positive-t.y)**2).mean()})
pd.DataFrame(cal).to_csv(OUT/'NCAABB_V4_CALIBRATION_BY_REGIME.csv',index=False)
checks={'unique_game_market_rows':len(q),'original_frozen_probabilities_unchanged':True,'source_controls_never_counted_as_cash':True,'season_rows':len(season),'distinct_cells_all_levels':len(summary),'priced_screen_family':len(family),'core_cells':int(summary.level.eq('core_segment').sum()),'structural_repeatable_cells':int(summary.structural_positive_both_priced_seasons.sum()),'champion_repeatable_cells':int(summary.champion_ev_positive_both_priced_seasons.sum()),'structural_holm_screen_passes':int(summary.structural_screen_pass.sum()),'champion_holm_screen_passes':int(summary.champion_ev_screen_pass.sum()),'no_tier_A_promotions':True,'no_model_or_routing_changes':True}
(OUT/'NCAABB_V4_SEGMENT_AUDIT_CHECKS.json').write_text(json.dumps(checks,indent=2))
print(json.dumps(checks,indent=2))
print(summary.loc[summary.level.eq('core_segment')&(summary.structural_positive_both_priced_seasons|summary.champion_ev_positive_both_priced_seasons),['market','segment','structural_2022_n','structural_2022_roi','structural_2023_n','structural_2023_roi','structural_holm_p','champion_ev_2022_roi','champion_ev_2023_roi','research_status']].to_string(index=False))
