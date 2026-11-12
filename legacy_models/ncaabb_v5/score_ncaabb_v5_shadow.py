#!/usr/bin/env python3
"""
NCAABB V5 prospective shadow wrapper.

- Calls the authoritative V4 scorer unchanged.
- Creates V5 shadow probabilities and frozen segment flags.
- Does NOT execute wagers.
- Does NOT implement V5 Adjusted Kelly. Full Kelly is reported; joint portfolio Kelly
  must be implemented and separately validated before that field is populated.
"""
from pathlib import Path
import argparse, subprocess, sys, tempfile, json, math
from datetime import datetime, timezone
import numpy as np
import pandas as pd

FREEZE = json.loads((Path(__file__).resolve().parent/"NCAABB_V5_FREEZE_PARAMETERS.json").read_text())

def num(x):
    return pd.to_numeric(x, errors="coerce")

def american_profit(o):
    o=float(o)
    if not math.isfinite(o) or o==0: return math.nan
    return o/100.0 if o>0 else 100.0/abs(o)

def decimal_odds(o):
    b=american_profit(o)
    return 1+b if math.isfinite(b) else math.nan

def no_vig(away, home):
    try:
        ba=american_profit(away); bh=american_profit(home)
        if not (math.isfinite(ba) and math.isfinite(bh)): return math.nan
        qa=1/(1+ba); qh=1/(1+bh)
        return qa/(qa+qh)
    except Exception:
        return math.nan

def logit(p):
    p=min(max(float(p),1e-8),1-1e-8)
    return math.log(p/(1-p))

def logistic(x):
    return 1/(1+math.exp(-x))

def kelly(p, american):
    b=american_profit(american)
    if not (math.isfinite(b) and math.isfinite(p)): return math.nan
    ce=b*p-(1-p)
    return max(0.0, ce/b)

def ev(p, american):
    b=american_profit(american)
    if not (math.isfinite(b) and math.isfinite(p)): return math.nan
    return b*p-(1-p)

def model_srs(row, side):
    early=float(row["season_week"]) < 8
    if side=="Away":
        return float(row["away_prior_srs"] if early else row["away_srs_pregame"])
    return float(row["home_prior_srs"] if early else row["home_srs_pregame"])

def dog_srs(row):
    sp=float(row["away_spread"])
    if sp>0: return model_srs(row,"Away")
    if sp<0: return model_srs(row,"Home")
    return math.nan

def market_fields(row, market):
    if market=="Spread":
        return float(row["away_spread"]), row.get("spread_snapshot_utc"), row.get("spread_away_odds"), row.get("spread_home_odds")
    if market=="Total":
        return float(row["total_line"]), row.get("total_snapshot_utc"), row.get("over_odds"), row.get("under_odds")
    return math.nan, row.get("moneyline_snapshot_utc"), row.get("away_moneyline"), row.get("home_moneyline")

def matched_segments(inp, score):
    market=score["market"]; ids=[]; anti=[]; side_map={}
    week=float(score.get("model_week", inp.get("season_week", math.nan)))
    if market=="Spread":
        ds=dog_srs(inp)
        sp=abs(float(inp["away_spread"]))
        edge=float(score.get("structure_cover_edge", math.nan))
        structural_side="Away" if edge>0 else ("Home" if edge<0 else None)
        if week<8 and math.isfinite(ds) and ds>=10:
            ids.append("SP-HOME-01"); side_map["SP-HOME-01"]="Home"
        if 10<=sp<15 and math.isfinite(ds) and -10<=ds<-5 and structural_side:
            anti.append("SP-ANTI-01"); side_map["SP-ANTI-01"]="Home" if structural_side=="Away" else "Away"
        if week<8 and math.isfinite(edge) and abs(edge)>=10 and str(score.get("structural_role",""))=="Underdog" and structural_side:
            ids.append("SP-EDGE-10"); side_map["SP-EDGE-10"]=structural_side
    elif market=="Moneyline":
        pa=no_vig(inp.get("away_moneyline"), inp.get("home_moneyline"))
        if math.isfinite(pa):
            dog_side="Away" if pa<0.5 else "Home"
            fav_side="Home" if dog_side=="Away" else "Away"
            dog_odds=float(inp["away_moneyline"] if dog_side=="Away" else inp["home_moneyline"])
            dog_p=min(pa,1-pa)
            if 250<=dog_odds<=400:
                ids.append("ML-SEG-01"); side_map["ML-SEG-01"]=fav_side
            if 0.20<=dog_p<0.25:
                ids.append("ML-SEG-02"); side_map["ML-SEG-02"]=fav_side
            fav_odds=float(inp["home_moneyline"] if fav_side=="Home" else inp["away_moneyline"])
            if week<8 and fav_odds<=-2000:
                anti.append("ML-TAIL-01"); side_map["ML-TAIL-01"]=fav_side
    elif market=="Total":
        total=float(inp["total_line"]); sp=abs(float(inp["away_spread"]))
        ste=float(score.get("structure_total_edge", math.nan))
        if total<131 and sp<5:
            ids.append("TOT-LTC-01"); side_map["TOT-LTC-01"]="Over"
        if math.isfinite(ste) and ste<-12 and 135<=total<145:
            anti.append("TOT-ANTI-01"); side_map["TOT-ANTI-01"]="Over"
    return ids, anti, side_map

def shadow_prob(inp, score):
    market=score["market"]
    v4p=float(score["p_positive"])
    if market=="Spread":
        anchor=0.5
        ids,_,_=matched_segments(inp,score)
        if "SP-HOME-01" in ids:
            hp=FREEZE["spread"]["SP-HOME-01"]["historical_exact_v4_scoring_population_2022_2025"]["posterior_home_cover_probability"]
            primary=1-float(hp)  # p_positive = Away
            primary_model="SP-SHADOW-01 (SP-HOME-01 local override)"
        else:
            primary=0.5; primary_model="SP-SHADOW-01 (SP-NULL-01)"
        return anchor, primary, math.nan, "SP-NULL-01", primary_model, ""
    if market=="Moneyline":
        p=no_vig(inp.get("away_moneyline"), inp.get("home_moneyline"))
        if not math.isfinite(p):
            return math.nan, math.nan, math.nan, "ML-RAW-01 unavailable", "ML-CAL-01 unavailable", "ML-CAL-02 unavailable"
        pars=FREEZE["moneyline"]["ML-CAL-01"]
        p1=logistic(pars["intercept"]+pars["logit_market_slope"]*logit(p))
        pars2=FREEZE["moneyline"]["ML-CAL-02"]
        tot=float(inp["total_line"])
        p2=logistic(pars2["intercept"]+pars2["logit_market_slope"]*logit(p)+pars2["total_coefficient"]*((tot-pars2["total_mean"])/pars2["total_sd"])) if math.isfinite(tot) else math.nan
        return p,p1,p2,"ML-RAW-01","ML-CAL-01","ML-CAL-02"
    # Total: authoritative V4 HGB is the V5 anchor; no frozen successor probability.
    return v4p,v4p,math.nan,"TOT-V4-HGB","TOT-V4-HGB (anchor retained)",""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input_csv")
    ap.add_argument("--v4-root", required=True, help="Extracted authoritative NCAABB V4 package root")
    ap.add_argument("--prediction-output", default="NCAABB_V5_SHADOW_PREDICTIONS.csv")
    ap.add_argument("--opportunity-output", default="NCAABB_V5_SHADOW_OPPORTUNITIES.csv")
    ap.add_argument("--bankroll", type=float, default=None)
    ap.add_argument("--snapshot-id", default=None)
    args=ap.parse_args()

    inp=pd.read_csv(args.input_csv, low_memory=False, dtype={"game_id":str})
    if inp["game_id"].duplicated().any():
        raise ValueError("One input row per game is required")
    snap=args.snapshot_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scored_at=datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory() as td:
        v4out=Path(td)/"v4_scores.csv"
        cmd=[sys.executable, str(Path(args.v4_root)/"code"/"score_ncaabb_v4.py"), args.input_csv,
             "--model", str(Path(args.v4_root)/"models"/"NCAABB_V4_PRODUCTION_CANDIDATE.joblib"),
             "--output", str(v4out)]
        if args.bankroll is not None:
            cmd += ["--bankroll", str(args.bankroll)]
        subprocess.run(cmd, check=True)
        v4=pd.read_csv(v4out, low_memory=False, dtype={"game_id":str})

    byid=inp.set_index("game_id", drop=False)
    pred=[]; opp=[]
    for _,s in v4.iterrows():
        i=byid.loc[str(s.game_id)]
        market=s.market
        line,quote_ts,o_pos,o_neg=market_fields(i,market)
        anchor,shadow,secondary,anchor_model,shadow_model,secondary_model=shadow_prob(i,s)
        segs,antis,side_map=matched_segments(i,s)
        vals=[x for x in [float(s.p_positive),anchor,shadow,secondary] if isinstance(x,(int,float)) and math.isfinite(x)]
        dispersion=float(np.std(vals, ddof=0)) if len(vals)>=2 else math.nan

        pred.append({
            "snapshot_id":snap,"game_id":str(s.game_id),"season":s.season,"game_date":s.game_date,
            "start_time_utc":i.get("start_time_utc"),"away_team":s.away_team,"home_team":s.home_team,
            "market":market,"quote_timestamp_utc":quote_ts,"scored_timestamp_utc":scored_at,
            "data_cutoff_timestamp_utc":scored_at,"market_line":line,
            "away_or_over_odds":o_pos,"home_or_under_odds":o_neg,
            "authoritative_model":"NCAABB V4","authoritative_version":"V4_PRODUCTION_CANDIDATE",
            "authoritative_p_positive":s.p_positive,"anchor_model":anchor_model,"anchor_p_positive":anchor,
            "primary_shadow_model":shadow_model,"primary_shadow_p_positive":shadow,
            "secondary_shadow_model":secondary_model,"secondary_shadow_p_positive":secondary,
            "shadow_delta_vs_anchor":shadow-anchor if math.isfinite(shadow) and math.isfinite(anchor) else math.nan,
            "model_dispersion":dispersion,"matched_segment_ids":";".join(segs),
            "matched_anti_regime_ids":";".join(antis),
            "evidence_alignment":"Research only; no manual probability stacking",
            "v4_selected_model":s.selected_model,"v4_selected_side":s.selected_side,
            "v4_selected_probability":s.selected_probability,"v4_tier":s.tier,"v4_health":s.health,
            "v4_pricing_status":s.pricing_status,"v4_stake_eligible":s.stake_eligible,
            "v4_full_kelly":s.full_kelly,"v4_legacy_adjusted_kelly":s.final_recommended_kelly,
            "v5_adjusted_kelly_status":"Pending joint-portfolio implementation",
            "freeze_name":FREEZE["freeze_name"],"settlement_status":"Pregame frozen"
        })

        sides=("Away","Home") if market in ("Spread","Moneyline") else ("Over","Under")
        for idx,side in enumerate(sides):
            odds=o_pos if idx==0 else o_neg
            if pd.isna(odds): continue
            ap=float(s.p_positive) if idx==0 else 1-float(s.p_positive)
            an=anchor if idx==0 else (1-anchor if math.isfinite(anchor) else math.nan)
            sh=shadow if idx==0 else (1-shadow if math.isfinite(shadow) else math.nan)
            deo=decimal_odds(odds)
            be=1/deo if math.isfinite(deo) else math.nan
            aev=ev(ap,odds); sev=ev(sh,odds) if math.isfinite(sh) else math.nan
            side_segments=[k for k,v in side_map.items() if v==side and k in segs+antis]
            # Research opportunity tier is deliberately conservative.
            if not math.isfinite(sev) or sev<=0:
                rtier="Pass"
            elif side_segments:
                rtier="Lean"
            elif market=="Moneyline" and shadow_model=="ML-CAL-01":
                rtier="Lean"
            else:
                rtier="Pass"
            sk=kelly(sh,odds) if math.isfinite(sh) else math.nan
            prod_stake=float(s.get("recommended_stake",0.0)) if (str(s.selected_side)==side and "recommended_stake" in s and pd.notna(s.get("recommended_stake"))) else 0.0
            opp.append({
                "snapshot_id":snap,"game_id":str(s.game_id),"season":s.season,"game_date":s.game_date,
                "market":market,"side":side,"offered_odds":odds,"decimal_odds":deo,"break_even_p":be,
                "authoritative_p":ap,"anchor_p":an,"shadow_p":sh,
                "authoritative_ev":aev,"shadow_ev":sev,"shadow_probability_edge":sh-be if math.isfinite(sh) and math.isfinite(be) else math.nan,
                "matched_side_segment_ids":";".join(side_segments),"shadow_research_tier":rtier,
                "authoritative_full_kelly":kelly(ap,odds),"shadow_full_kelly":sk,
                "shadow_adjusted_kelly":math.nan,
                "shadow_adjusted_kelly_status":"Pending posterior-aware joint portfolio Kelly",
                "production_stake_eligible":bool(s.stake_eligible) and str(s.selected_side)==side,
                "shadow_stake_eligible":False,
                "production_recommended_stake":prod_stake,"shadow_recommended_stake":0.0,"actual_stake":0.0,
                "result":"","return_per_unit":"","production_units":"","shadow_units":"","actual_cash_pnl":"",
                "closing_line":"","closing_odds":"","clv":"","settlement_status":"Pregame frozen"
            })

    pd.DataFrame(pred).to_csv(args.prediction_output,index=False)
    pd.DataFrame(opp).to_csv(args.opportunity_output,index=False)
    print(f"Wrote {len(pred)} market predictions and {len(opp)} side opportunities.")

if __name__=="__main__":
    main()
