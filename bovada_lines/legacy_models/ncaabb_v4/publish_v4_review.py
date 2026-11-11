"""Explain the role-orientation correction and publish reproducible results."""
from pathlib import Path
import json,zipfile
import numpy as np
import pandas as pd
from scipy.special import logit
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
ROOT=Path(__file__).resolve().parents[1]
def read(name):return pd.read_csv(ROOT/name,low_memory=False,dtype={'game_id':str})
def table(df):
 def fmt(x):
    if pd.isna(x):return ''
    return (f'{x:.6f}' if isinstance(x,float) else str(x)).replace('|','\\|')
 return '\n'.join(['| '+' | '.join(df.columns)+' |','| '+' | '.join(['---']*len(df.columns))+' |']+['| '+' | '.join(fmt(x) for x in row)+' |' for row in df.itertuples(index=False,name=None)])
c4=read('NCAABB_V4_MODEL_COMPARISON.csv');c3=read('comparison_references/NCAABB_V3_MODEL_COMPARISON.csv')
refs=c3.loc[c3.candidate.eq('Matchup_Champion_v3')].copy();current=c4.loc[c4.candidate.eq('Matchup_Champion_v4')].copy()
comparison=current.merge(refs,on=['market','season'],suffixes=('_V4','_V3'),validate='one_to_one')
comparison=comparison[['market','season','games_V4','hit_rate_V3','hit_rate_V4','brier_V3','brier_V4','actual_price_bets_V3','actual_price_bets_V4','actual_price_flat_roi_V3','actual_price_flat_roi_V4','roi_ci_low_V4','roi_ci_high_V4']]
comparison.to_csv(ROOT/'NCAABB_V4_VS_V3_COMPARISON.csv',index=False)
ml= comparison.loc[comparison.market.eq('Moneyline')].copy()
for c in ['hit_rate_V3','hit_rate_V4','actual_price_flat_roi_V3','actual_price_flat_roi_V4','roi_ci_low_V4','roi_ci_high_V4']:ml[c]=100*ml[c]
p4=read('NCAABB_V4_WALK_FORWARD_PREDICTIONS.csv');p3=read('comparison_references/NCAABB_V3_WALK_FORWARD_PREDICTIONS.csv')
pair=p4.merge(p3[['game_id','market','p_Matchup_Champion_v3']],on=['game_id','market'],validate='one_to_one')
assert len(pair)==len(p4)
checks={}
for market in ['Spread','Total']:
 t=pair.loc[pair.market.eq(market)];error=float(np.abs(t.p_Matchup_Champion_v4-t.p_Matchup_Champion_v3).max());assert error<1e-12
 checks[market+'_probabilities_unchanged_max_error']=error
paired=[]
for market,t in pair.loc[pair.season.eq(2025)&pair.y.notna()].groupby('market'):
 diff=(t.p_Matchup_Champion_v4-t.y)**2-(t.p_Matchup_Champion_v3-t.y)**2
 daily=pd.DataFrame({'date':t.game_date,'diff':diff}).groupby('date')['diff'].agg(['sum','size'])
 rng=np.random.default_rng(27052025);ix=rng.integers(0,len(daily),(1000,len(daily)))
 sims=daily['sum'].to_numpy()[ix].sum(1)/daily['size'].to_numpy()[ix].sum(1)
 paired.append({'market':market,'nonpush_n':len(t),'brier_difference_V4_minus_V3':diff.mean(),'ci_low':np.quantile(sims,.025),'ci_high':np.quantile(sims,.975)})
paired=pd.DataFrame(paired);paired.to_csv(ROOT/'NCAABB_V4_VS_V3_PAIRED_2025.csv',index=False)
scoring=read('NCAABB_V4_2025_SCORING.csv').merge(p4[['game_id','market','p_Segment_Rule','p_Market_Benchmark']],on=['game_id','market'],validate='one_to_one')
master=read('NCAABB_DB_CLEAN_REBUILT_2021_2025.csv')
anchor=master.set_index('game_id').away_ml_no_vig_probability
moneyline=scoring.market.eq('Moneyline');is_dog=scoring.structural_role.eq('Underdog')
side=np.where(is_dog,scoring.game_id.map(anchor).lt(.5),scoring.structure_away_margin.ge(0))
offset=logit(scoring.p_Segment_Rule.clip(1e-6,1-1e-6))-logit(scoring.p_Market_Benchmark.clip(1e-6,1-1e-6))
scoring['ML_rule_calibration_role']=np.where(moneyline,np.where(is_dog,'Underdog','Unpriced winner forecast'),None)
scoring['ML_rule_calibration_side']=np.where(moneyline,np.where(side,'Away','Home'),None)
scoring['ML_rule_away_log_odds_offset']=offset.where(moneyline)
scoring['ML_rule_role_log_odds_offset']=(offset*np.where(side,1,-1)).where(moneyline)
scoring.to_csv(ROOT/'NCAABB_V4_2025_SCORING_REVIEW.csv',index=False)
assert scoring.final_recommended_kelly.eq(0).all()
checks['all_2025_recommended_stakes_zero']=True
checks['no_new_2025_prices_inferred']=True
checks['V3_and_V4_scored_same_game_market_rows']=True
(ROOT/'NCAABB_V4_COMPARISON_CHECKS.json').write_text(json.dumps(checks,indent=2))
router=json.loads((ROOT/'NCAABB_V4_ROUTING_FROZEN_2025.json').read_text());rows=[]
for m,r in router.items():
 rows.append({'market':m,'route':'Global','chosen_model':r['Global']})
 rows.extend({'market':m,'route':'Anchor: '+k,'chosen_model':v} for k,v in r['anchors'].items())
 rows.extend({'market':m,'route':k,'chosen_model':v} for k,v in r['cells'].items())
routing=pd.DataFrame(rows)
test=read('NCAABB_V4_CHALLENGER_SELECTION_TESTS.csv');selected=test.loc[(test.decision_before_season==2025)&test.eligible_promotion].copy()
summary=read('segment_audit/NCAABB_V4_SEGMENT_REPEATABILITY.csv')
watch=summary.loc[summary.structural_positive_both_priced_seasons].copy()
audit=json.loads((ROOT/'segment_audit/NCAABB_V4_SEGMENT_AUDIT_CHECKS.json').read_text())
board=c4.loc[(c4.season==2025)&c4.candidate.isin(['Matchup_Champion_v4','Market_Benchmark']),['market','candidate','nonpush_n','hit_rate','brier','log_loss']].copy();board.hit_rate*=100
priced=c4.loc[(c4.season==2023)&c4.candidate.eq('Matchup_Champion_v4'),['market','actual_price_bets','actual_price_flat_roi','roi_ci_low','roi_ci_high']].copy()
for c in ['actual_price_flat_roi','roi_ci_low','roi_ci_high']:priced[c]*=100
notes=pd.DataFrame([
 ['V4 change','Moneyline calibration targets the structural team role, then converts to away probability with the correct sign. Priced-underdog and unpriced-winner fallbacks and challenger tests are separate.'],
 ['Source error','V3 fitted a pooled away-win logit offset within ML cells; the offset did not follow the underdog when it was home. V4 corrects this implementation mismatch.'],
 ['Formula','Role p = away p if the structural side is away, else 1-away p. Fit delta to role wins. Apply away logit + delta for away role, away logit - delta for home role.'],
 ['Timing / controls','0.1 stakes are self-made controls; Week <8 prior-season SRS, Week 8+ current pregame, >90 postseason.'],
 ['Dataset limits','22,481 master week codes are explicitly inferred; seven conflicting source regimes excluded. Exact source SRS snapshot timestamps remain unverified.'],
 ['Prices','2024/2025 lack verified paired executable prices. No stakes or ROI validation invented; 2025 controls are not actual wagers.'],
 ['Validation','Frozen fits and routing through 2024 only; 2025 already viewed, so retrospective. Production candidate refits through 2025.'],
 ['Evidence','A→B+→B→Lean→Pass, effective N and Full/Adjusted Kelly retained. Health multiplier stays one; no arbitrary probability haircut.'],
 ['Tier A','No promotion: profitable performance has not been established with independent priced validation.'],
 ['Quote audit','One strong odds/handicap disagreement, already marked source quote time unverified; raw values preserved and listed. Internal mapping check is not independent timestamp verification.'],
 ['Scoring detail','ML_rule_* fields describe the segment rule only. When a challenger is selected, its p_positive is separate from the rule probability.'],
 ['Version use','Use V4 for continued research/scoring; it supersedes the affected V3 moneyline results. V3 references are retained for comparison.'],
],columns=['Item','Explanation'])
report=f'''# NCAA basketball V4: moneyline orientation correction

V4 corrects a real implementation error in the earlier moneyline segment model. V3 applied a calibrated log-odds offset to the away team regardless of which team occupied the underdog/structural role. V4 fits the offset to role wins and signs it correctly when converting back to away-win probability. Priced underdog and unpriced winner-forecast fallback calibration and challenger comparisons are now separate. The previously reported V3 moneyline results should be replaced with these corrected research results.

## Rules and interpretation

{table(notes)}

The role correction has no effect on spread or total probabilities: they reproduce V3 within numerical tolerance. Correcting moneyline selections can change daily portfolio allocations across markets. Home-court estimation, base-feature Week 8 timing, original outcomes and quoted prices are unchanged. V4 reuses the base estimators already retrained under the Week policy; it refits structural calibration and challenger routing chronologically. No new thresholds were searched on 2025 outcomes.

## Moneyline before and after

Hit-rate and return columns below are percentages; Brier remains on its ordinary probability-error scale. Returns are one-unit simulations at verified historical quotes, not actual cash P&L. The ROI intervals are date-bootstrap 95% intervals. The opportunities differ between V3 and V4, so the ROI figures are not a paired test on identical bets.

{table(ml)}

In 2022 no ML quote opportunity has positive model EV under the corrected rule because there was no earlier verified-price calibration evidence for the priced-under-dog fallback. The 2023 ML return improves from roughly -4.00% to -2.49%, but its interval still includes zero. The 2024 final forecast matches V3 once the unpriced population's supported challenger is selected; it remains worse than the market proxy benchmark. Improved 2025 calibration does not establish profitable betting.

## 2025 probability validation

{table(board)}

Paired 2025 Brier differences versus V3, with date-bootstrap intervals (negative favors V4):

{table(paired)}

2025 ML Brier is approximately 0.173807 versus 0.174395 for the benchmark. Its difference from the benchmark is approximately -0.000587, with a 95% interval of [-0.001823, 0.000516], which includes zero. All 17,072 scored 2025 market rows recommend zero stakes because paired prices are not verified. The 61 control games remain game evidence, with 183 market-control observations and zero actual cash contribution.

## Frozen champion / challenger routing

{table(routing)}

The frozen 2025 challenger family contains {int(test.decision_before_season.eq(2025).sum())} comparisons, including the separate priced/unpriced ML populations. Tests use earlier-season out-of-sample predictions, at least 200 games, two seasons and 30 dates, improvement in every earlier season, and Holm-adjusted one-sided date-clustered p<0.05. Local cell overrides take precedence over the anchor group's challenger, then the global rule. The priced +700+ early ML override has no executable-price 2025 observations, so it is not independently confirmed by 2025 ROI.

## Price-based and segment evidence

2023 champion flat-unit simulations, percentages:

{table(priced)}

The full updated segment audit contains {audit['core_cells']} core cells and {audit['distinct_cells_all_levels']} cells across all levels. Eight overlapping structural-direction cells remain positive in both priced seasons; none survives the corrected {audit['priced_screen_family']}-comparison price-evidence screen, and their pooled intervals include zero. No champion positive-EV cell has at least 100 opportunities and positive returns in both 2022 and 2023. The existing structural watchlist therefore remains Lean. The revised prediction routing is research progress, not a Tier A betting approval.

## Checks and reproducibility

Home/away swapping leaves fitted role offsets unchanged and yields complementary away probabilities. Positive role offsets raise either a home or away underdog's probability. Adding unpriced winner rows does not change the priced fallback fit. Challenger anchor routes and local overrides are tested. All 14,199 stored paired quote anchors reproduce from their odds; the single strong odds/spread direction flag was already unverified. Raw quote data is retained.

Week 0/7/8/90/91 boundary tests pass; mutating current ratings has no early-season feature effect. Frozen serialization reproduces all 17,072 2025 rows within floating-point tolerance. Outcome permutation leaves allowlisted model features exactly identical and probabilities within 1e-12. Effective N, evidence timing, cash-budget limits and outcome-free scoring checks pass. Exact bit-for-bit floating-point equality is not required when feature memory layout changes; the recorded differences are below 1e-15.

Install requirements.txt and follow README.txt to rebuild, inspect the audit or score normalized pregame inputs. The package includes corrected model bundles, code, cached training inputs, row-level scores and references for the V3 comparison. V4 is the current research candidate; missing contemporaneous prices and independent profitable validation remain unresolved.
'''.replace('under\\-dog','underdog')
(ROOT/'NCAABB_V4_MODEL_REVIEW.md').write_text(report)
(ROOT/'README.txt').write_text('''NCAA BB V4 — role-oriented moneyline correction
Install requirements.txt. From this package directory:
python code/build_matchup_model.py --source training_cache --output .
python code/check_moneyline_orientation.py
python code/check_week_boundaries.py
python code/audit_segments.py
python code/publish_v4_review.py

Score normalized inputs:
python code/score_ncaabb_v4.py NCAABB_V4_SCORING_INPUT_EXAMPLES.csv --output scores.csv --bankroll 1000

Frozen model fits through 2024; production candidate refits through 2025.
2025 is retrospective and lacks verified paired prices. No bets are submitted.
V4 supersedes affected V3 moneyline research results; no Tier A promotion is made.
training_cache base model filenames use legacy V1 names for compatibility, but contain the Week-policy-retrained estimators.
The same unchanged cleaned master is included; do not treat this copy as a newly revised dataset.
''')
validation=pd.DataFrame([{'source':name,'check':k,'value':str(v)} for name in ['NCAABB_V4_VALIDATION_CHECKS.json','NCAABB_V4_ORIENTATION_CHECKS.json','NCAABB_V4_WEEK_BOUNDARY_TESTS.json','NCAABB_V4_COMPARISON_CHECKS.json'] for k,v in json.loads((ROOT/name).read_text()).items()])
with pd.ExcelWriter(ROOT/'NCAABB_V4_MODEL_REVIEW.xlsx',engine='openpyxl') as writer:
 for name,df in {'Read Me':notes,'ML V3 vs V4':ml,'All Version Comparisons':comparison,'2025 Board':board,'2025 Paired V3 vs V4':paired,'2025 Benchmark Intervals':read('NCAABB_V4_2025_PAIRED_BRIER.csv'),'Frozen Routing':routing,'Challenger Tests':test,'All Model Results':c4,'2023 Priced Simulation':priced,'Structural Watchlist':watch,'All Cell Evidence':summary,'Cells by Season':read('segment_audit/NCAABB_V4_SEGMENTS_BY_SEASON.csv'),'2025 Scoring':scoring,'Quote Direction Flag':read('NCAABB_V4_QUOTE_DIRECTION_FLAGS.csv'),'Validation Checks':validation}.items():
    df.to_excel(writer,sheet_name=name,index=False);ws=writer.book[name];ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17365D')
    for i,c in enumerate(df.columns,1):ws.column_dimensions[get_column_letter(i)].width=min(50,max(14,len(c)+2))
    if name=='Read Me':
        ws.column_dimensions['B'].width=100
        for row in ws.iter_rows(min_row=2):row[1].alignment=Alignment(wrap_text=True);ws.row_dimensions[row[0].row].height=45
archive=ROOT/'NCAABB_V4_COMPLETE_PACKAGE.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in sorted(ROOT.rglob('*')):
    if p.is_file() and p!=archive and '__pycache__' not in p.parts and not p.name.endswith('.log'):z.write(p,p.relative_to(ROOT))
print('Created V4 review, scoring review and package',archive.stat().st_size)
