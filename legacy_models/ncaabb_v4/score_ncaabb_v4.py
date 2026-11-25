"""Score normalized pregame inputs; never execute a bet."""
from pathlib import Path
import argparse
import sys
import joblib
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ncaabb_models import boolean,num,odds_profit
from ncaabb_matchup import score_bundle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--model",default=str(Path(__file__).resolve().parents[1]/"models/NCAABB_V4_PRODUCTION_CANDIDATE.joblib"))
    parser.add_argument("--output",default="NCAABB_MODEL_SCORES.csv")
    parser.add_argument("--bankroll",type=float,default=None,help="Optional bankroll for the final-stake arithmetic; no bet is submitted.")
    args=parser.parse_args()
    d=pd.read_csv(args.input_csv,low_memory=False,dtype={"game_id":str})
    if d["game_id"].duplicated().any(): raise ValueError("One input row per game is required")
    if args.bankroll is not None and (not np.isfinite(args.bankroll) or args.bankroll<=0): raise ValueError("Bankroll must be positive")
    required=["game_date","away_srs_pregame","home_srs_pregame","d1_vs_d1","pregame_no_future_results","rating_asof_date","rating_max_result_date"]
    required += ["season_week","away_prior_osrs","home_prior_osrs","away_prior_def_allowance","home_prior_def_allowance","away_prior_srs","home_prior_srs","away_games_before","home_games_before","neutral_site","away_osrs_pregame","home_osrs_pregame","prior_scoring_baseline_per_team"]
    missing=[c for c in required if c not in d]
    if missing: raise ValueError(f"Required pregame fields missing: {missing}")
    for c in ["away_prior_osrs","home_prior_osrs","away_prior_def_allowance","home_prior_def_allowance","away_srs_pregame","home_srs_pregame","away_prior_srs","home_prior_srs","away_games_before","home_games_before","away_osrs_pregame","home_osrs_pregame","prior_scoring_baseline_per_team"]:
        if num(d,c).isna().any(): raise ValueError(f"Missing numeric pregame segment input: {c}")
    d['model_week']=pd.to_numeric(d['season_week'],errors='coerce')
    if d['model_week'].isna().any(): raise ValueError('A source or explicitly inferred week code is required')
    d['model_early_season']=d['model_week']<8
    d['model_postseason']=d['model_week']>90
    d['model_week_rule_safe']=True
    game_date=pd.to_datetime(d["game_date"],errors="raise")
    asof=pd.to_datetime(d["rating_asof_date"],errors="coerce")
    results=pd.to_datetime(d["rating_max_result_date"],errors="coerce")
    if ((asof>game_date)|(results>=game_date)|asof.isna()|~boolean(d,"pregame_no_future_results")).any(): raise ValueError("Unsafe or unverified pregame rating timing")
    tip=pd.to_datetime(d.get("start_time_utc",pd.Series(None,index=d.index)),errors="coerce",utc=True)
    for market in ["spread","total","moneyline"]:
        status=d.get(market+"_time_status",pd.Series("Missing",index=d.index))
        snapshot=pd.to_datetime(d.get(market+"_snapshot_utc",pd.Series(None,index=d.index)),errors="coerce",utc=True)
        claimed=status.eq("Verified before scheduled tip")
        if (claimed & (tip.isna()|snapshot.isna()|(snapshot>=tip))).any():
            raise ValueError(f"Verified {market} quotes require a timestamp before scheduled tip")
    # Recompute the price anchor from the supplied pair; never trust a stale cached %.
    away_b=odds_profit(num(d,"away_moneyline"))
    home_b=odds_profit(num(d,"home_moneyline"))
    away_implied=1/(1+away_b)
    home_implied=1/(1+home_b)
    d["away_ml_no_vig_probability"]=away_implied/(away_implied+home_implied)
    model=joblib.load(args.model)
    scores=score_bundle(model,d,args.bankroll)
    scores["model_trained_through_season"]=model["trained_through_season"]
    scores["scoring_role"]=np.where(pd.to_numeric(scores.get("season"),errors="coerce")<=model["trained_through_season"],"Historical example / not independent validation","Future pregame scoring candidate")
    scores.to_csv(args.output,index=False)
    print(f"Scored {len(d)} inputs into {len(scores)} market rows: {args.output}")


if __name__=="__main__": main()
