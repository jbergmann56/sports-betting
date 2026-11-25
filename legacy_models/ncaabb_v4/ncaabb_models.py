"""Time-safe NCAA basketball models and evidence-aware scoring.

Inputs are normalized pregame rows from the companion cleanup pipeline.
No outcome columns are used by feature_table or predict_bundle.
"""
from __future__ import annotations

import math
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, logit
from scipy.stats import norm
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 27052025
BASE_CANDIDATES = ["Logistic", "HistGradientBoosting", "RandomForest", "SRS_Projection", "Market_Benchmark"]
MARKETS = ["Spread", "Moneyline", "Total"]
HEALTH_WEIGHTS = {"Stable": 1.0, "Strengthening": 1.0, "Watch": 0.5, "Degrading": 0.25, "Broken": 0.0}


def market_health_from_validation(records, market, before_season):
    eligible=[r for r in records if r["market"]==market and r["candidate"]=="Segment_Champion_v1" and 2023<=r["season"]<before_season and r.get("actual_price_bets",0)>0]
    if not eligible:
        return {"market_health":"Watch","market_health_reason":"No earlier independent actual-price validation season","market_health_price_season":None}
    r=max(eligible,key=lambda r:r["season"])
    lo,hi=r.get("actual_roi_ci_low",np.nan),r.get("actual_roi_ci_high",np.nan)
    state="Degrading" if np.isfinite(hi) and hi<0 else ("Stable" if np.isfinite(lo) and lo>0 else "Watch")
    return {"market_health":state,"market_health_reason":"Latest independent actual-price flat-unit ROI and date-cluster bootstrap interval","market_health_price_season":int(r["season"]),"market_health_price_roi":r["actual_price_flat_roi"],"market_health_price_roi_ci_low":lo,"market_health_price_roi_ci_high":hi}


def num(d, col, default=np.nan):
    if col not in d:
        return pd.Series(default, index=d.index, dtype=float)
    return pd.to_numeric(d[col], errors="coerce")


def boolean(d, col, default=False):
    if col not in d:
        return pd.Series(default, index=d.index)
    return d[col].astype(str).str.lower().isin(["true", "1", "1.0"])


def verified(d, market):
    col = {"Spread": "spread_time_status", "Moneyline": "moneyline_time_status", "Total": "total_time_status"}[market]
    return d.get(col, pd.Series("Missing", index=d.index)).eq("Verified before scheduled tip")


def week_early(d):
    if 'model_early_season' in d:return boolean(d,'model_early_season')
    return num(d,'model_week' if 'model_week' in d else 'season_week')<8


def rating_input(d,side,component):
    names={'srs':('prior_srs','srs_pregame'),'osrs':('prior_osrs','osrs_pregame'),'allowance':('prior_def_allowance','def_allowance_pregame')}
    prior,current=names[component]
    return num(d,side+'_'+current).where(~week_early(d),num(d,side+'_'+prior))


def feature_table(d, market, projection=False):
    """Explicit pregame allowlist; never infer columns from the input schema."""
    x = pd.DataFrame(index=d.index)
    early=week_early(d)
    x["rating_gap"] = rating_input(d,'away','srs') - rating_input(d,'home','srs')
    x["prior_gap"] = num(d, "away_prior_srs") - num(d, "home_prior_srs")
    x["slope_gap"] = (num(d, "away_srs_slope_28d") - num(d, "home_srs_slope_28d")).where(~early)
    x["offense_gap"] = rating_input(d,'away','osrs') - rating_input(d,'home','osrs')
    x["allowance_gap"] = rating_input(d,'away','allowance') - rating_input(d,'home','allowance')
    x["home_court"] = (~boolean(d, "neutral_site")).astype(float)
    ag, hg = num(d, "away_games_before"), num(d, "home_games_before")
    x["min_games"] = pd.concat([ag, hg], axis=1).min(axis=1).clip(0, 40)
    x["history_imbalance"] = (ag - hg).clip(-30, 30)
    x["early_season"] = early.astype(float)
    x["week"] = num(d, "season_week").clip(1, 30)
    x["postseason"] = (boolean(d,'model_postseason') if 'model_postseason' in d else num(d,'season_week').gt(90)).astype(float)
    x["rating_gap_early"] = x["rating_gap"] * x["early_season"]
    x["offense_sum"] = rating_input(d,'away','osrs') + rating_input(d,'home','osrs')
    x["allowance_sum"] = rating_input(d,'away','allowance') + rating_input(d,'home','allowance')
    x["prior_scoring_total"] = 2 * num(d, "prior_scoring_baseline_per_team")
    if not projection:
        handicap = num(d, "away_spread").where(verified(d, "Spread"))
        if market in ["Spread", "Moneyline"]:
            x["market_handicap"] = handicap
            x["rating_cover_edge"] = x["rating_gap"] + handicap
        if market == "Moneyline":
            anchor = num(d, "away_ml_no_vig_probability").where(verified(d, "Moneyline"))
            x["ml_anchor_logit"] = logit(anchor.clip(1e-6, 1 - 1e-6))
            x["ml_anchor_missing"] = anchor.isna().astype(float)
        if market == "Total":
            line = num(d, "total_line").where(verified(d, "Total"))
            x["market_total"] = line
            x["rating_total_edge"] = x["prior_scoring_total"] + x["offense_sum"] + x["allowance_sum"] - line
    return x.astype(float)


def market_mask(d, market):
    base = boolean(d, "d1_vs_d1") & num(d, "away_srs_pregame").notna() & num(d, "home_srs_pregame").notna()
    if 'model_week_rule_safe' in d:base &= boolean(d,'model_week_rule_safe')
    if market == "Spread":
        base &= num(d, "away_spread").notna() & verified(d, market)
    elif market == "Total":
        base &= num(d, "total_line").notna() & verified(d, market)
    return base


def targets(d, market):
    if market == "Spread":
        margin = num(d, "actual_away_margin") + num(d, "away_spread")
    elif market == "Total":
        margin = num(d, "actual_total") - num(d, "total_line")
    else:
        margin = num(d, "actual_away_margin")
    return (margin > 0).astype(float).where(margin.notna() & margin.ne(0)), margin.eq(0)


def fit_base(d, market, candidate):
    y, _ = targets(d, market)
    valid = y.notna()
    if candidate == "SRS_Projection":
        target = num(d, "actual_total" if market == "Total" else "actual_away_margin")
        reg = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=25.0))
        reg.fit(feature_table(d, market, projection=True), target)
        residual = target.to_numpy() - reg.predict(feature_table(d, market, projection=True))
        return {"estimator": reg, "sigma": float(np.sqrt(np.mean(residual**2))), "candidate": candidate}
    if candidate == "Market_Benchmark":
        if market != "Moneyline":
            return {"candidate": candidate}
        hp = num(d, "away_spread").where(verified(d, "Spread"))
        m = hp.notna() & y.notna()
        reg = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=500, random_state=SEED))
        reg.fit(hp[m].to_numpy().reshape(-1, 1), y[m].astype(int))
        return {"estimator": reg, "candidate": candidate}
    if candidate == "Logistic":
        estimator = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), LogisticRegression(C=1.0, max_iter=1500, random_state=SEED))
    elif candidate == "HistGradientBoosting":
        estimator = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), HistGradientBoostingClassifier(max_iter=160, learning_rate=0.04, max_leaf_nodes=7, min_samples_leaf=80, l2_regularization=5.0, random_state=SEED))
    elif candidate == "RandomForest":
        estimator = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), RandomForestClassifier(n_estimators=160, max_depth=6, min_samples_leaf=80, max_features=0.8, n_jobs=2, random_state=SEED))
    else:
        raise ValueError(candidate)
    estimator.fit(feature_table(d.loc[valid], market), y[valid].astype(int))
    return {"candidate": candidate, "estimator": estimator}


def predict_base(model, d, market):
    c = model["candidate"]
    if c == "SRS_Projection":
        estimate = model["estimator"].predict(feature_table(d, market, projection=True))
        if market == "Spread":
            estimate = estimate + num(d, "away_spread").to_numpy()
        elif market == "Total":
            estimate = estimate - num(d, "total_line").to_numpy()
        return norm.cdf(estimate / max(model["sigma"], 1.0))
    if c == "Market_Benchmark":
        if market != "Moneyline":
            return np.full(len(d), 0.5)
        hp = num(d, "away_spread").where(verified(d, "Spread"))
        p = np.full(len(d), 0.5)
        v = hp.notna()
        p[v.to_numpy()] = model["estimator"].predict_proba(hp[v].to_numpy().reshape(-1, 1))[:, 1]
        anchor = num(d, "away_ml_no_vig_probability").where(verified(d, "Moneyline"))
        p[anchor.notna().to_numpy()] = anchor.dropna().to_numpy()
        return p
    return model["estimator"].predict_proba(feature_table(d, market))[:, 1]


def fit_calibrator(raw, y, candidate):
    valid = np.isfinite(raw) & np.isfinite(y)
    if candidate == "Market_Benchmark" or valid.sum() < 150 or np.unique(y[valid]).size < 2:
        return None
    cal = LogisticRegression(C=10.0, max_iter=500, random_state=SEED)
    cal.fit(logit(np.clip(raw[valid], 1e-6, 1-1e-6)).reshape(-1, 1), y[valid].astype(int))
    return cal


def calibrate(cal, p):
    p = np.clip(np.asarray(p), 1e-6, 1-1e-6)
    return p if cal is None else cal.predict_proba(logit(p).reshape(-1, 1))[:, 1]


def segment_keys(d, market, p):
    """Predeclared segments, assigned using pregame inputs and model signal only."""
    hp = num(d, "away_spread").to_numpy()
    early = week_early(d).to_numpy()
    neutral = boolean(d, "neutral_site").to_numpy()
    positive_side = np.asarray(p) >= 0.5
    if market == "Spread":
        # Signal magnitude in learned probability, not copied football point thresholds.
        strength = np.digitize(np.abs(np.asarray(p)-0.5), [0.025, 0.05, 0.10])
        away_favorite = hp < 0
        role = np.where(hp == 0, "Pickem", np.where(positive_side == away_favorite, "Favorite", "Underdog"))
        regime = np.where(neutral, "Neutral", "Court")
    elif market == "Moneyline":
        strength = np.digitize(np.maximum(np.asarray(p), 1-np.asarray(p)), [0.60, 0.75, 0.90])
        anchor = num(d, "away_ml_no_vig_probability").where(verified(d, "Moneyline")).to_numpy()
        away_favorite = np.where(np.isfinite(anchor), anchor > 0.5, hp < 0)
        role = np.where(positive_side == away_favorite, "Favorite", "Underdog")
        regime = np.where(early, "Early", "Established")
    else:
        strength = np.digitize(np.abs(np.asarray(p)-0.5), [0.025, 0.05, 0.10])
        role = np.where(positive_side, "Over", "Under")
        regime = np.where(early, "Early", "Established")
    return np.array([f"S{s}|{r}|{g}" for s,r,g in zip(strength, role, regime)])


def cluster_stats(y, p, dates):
    """Calendar-day robust uncertainty, capped at the unique-game count."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    n = len(y)
    if n == 0:
        return {"n": 0, "n_eff": 0.0, "se": np.nan, "bias": np.nan, "days": 0}
    residual = y-p
    groups = pd.DataFrame({"d": np.asarray(dates), "r": residual-residual.mean()}).groupby("d")["r"].sum()
    g = len(groups)
    variance = float((groups**2).sum() / n**2 * (g/max(g-1,1)))
    independent_var = float(np.mean(p*(1-p))/n)
    variance = max(variance, independent_var)
    neff = min(float(n), float(np.mean(p*(1-p))/max(variance,1e-12)))
    return {"n": n, "n_eff": neff, "se": float(np.sqrt(variance)), "bias": float(residual.mean()), "days": g}


def fit_segments(d, p, y, market, prior_n):
    keys = segment_keys(d, market, p)
    valid = np.isfinite(y)
    all_y, all_p = y[valid], p[valid]
    overall = cluster_stats(all_y, all_p, d.loc[valid,"game_date"].to_numpy())
    overall["delta"] = 0.0
    overall["health"] = "Stable"
    result = {"prior_n": int(prior_n), "cells": {}, "overall": overall, "market": market}
    _, pushed = targets(d, market)
    line=num(d,"away_spread" if market=="Spread" else "total_line").to_numpy()
    integer_line=np.isfinite(line)&np.isclose(line,np.round(line)) if market!="Moneyline" else np.zeros(len(d),dtype=bool)
    global_push = float(pushed[integer_line].mean()) if integer_line.any() else 0.0
    result["global_push_rate"] = global_push
    for key in sorted(set(keys)):
        m = (keys == key) & valid
        yy, pp = y[m], p[m]
        z = logit(np.clip(pp, 1e-6, 1-1e-6))
        penalty = prior_n*0.25
        objective = lambda delta: float(np.sum(np.logaddexp(0,z+delta) - yy*(z+delta)) + 0.5*penalty*delta**2)
        opt = minimize_scalar(objective, bounds=(-4,4), method="bounded")
        delta = float(opt.x) if len(yy) else 0.0
        stats = cluster_stats(yy, pp, d.loc[m,"game_date"].to_numpy())
        stats.update(delta=delta, key=key, prior_n=int(prior_n))
        all_cell = keys == key
        integer_cell=all_cell&integer_line
        stats["push_rate"] = float((pushed[integer_cell].sum()+prior_n*global_push)/(integer_cell.sum()+prior_n)) if market!="Moneyline" else 0.0
        seasons = num(d.loc[m], "season").to_numpy()
        latest = int(np.max(seasons)) if len(seasons) else 0
        # Health is computed only from calibration observations already available.
        # Signed residual checks whether the model's preferred side is overstated.
        signed_y = np.where(pp >= .5, yy, 1-yy)
        signed_p = np.maximum(pp, 1-pp)
        last = seasons == latest
        old = seasons < latest
        last_stats = cluster_stats(signed_y[last], signed_p[last], d.loc[m,"game_date"].to_numpy()[last])
        old_stats = cluster_stats(signed_y[old], signed_p[old], d.loc[m,"game_date"].to_numpy()[old])
        shift_se = np.sqrt(last_stats["se"]**2+old_stats["se"]**2) if old.any() else np.nan
        shift_z = (last_stats["bias"]-old_stats["bias"])/shift_se if np.isfinite(shift_se) and shift_se>0 else 0.0
        health = "Stable"
        if stats["n_eff"] < 50 or last_stats["n"] < 30:
            health = "Watch"
        elif shift_z <= -3:
            health = "Degrading"
        elif shift_z <= -2:
            health = "Watch"
        elif shift_z >= 2:
            health = "Strengthening"
        # Broken is reserved for scoring failures or a user disabled model.
        stats.update(health=health, latest_evidence_season=latest, health_shift_z=float(shift_z), latest_n=last_stats["n"])
        result["cells"][key] = stats
    return result


def apply_segments(segments, d, p, market):
    keys = segment_keys(d, market, p)
    delta = np.array([segments["cells"].get(k, {}).get("delta", 0.0) for k in keys])
    return expit(logit(np.clip(p,1e-6,1-1e-6))+delta), keys


def odds_profit(odds):
    odds = np.asarray(odds, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        b = np.where(odds>0, odds/100.0, 100.0/np.abs(odds))
    return np.where(np.isfinite(odds) & (np.abs(odds)>=100), b, np.nan)


def odds_columns(market):
    return {"Spread": ("spread_away_odds", "spread_home_odds"), "Moneyline": ("away_moneyline", "home_moneyline"), "Total": ("over_odds", "under_odds")}[market]


def risk_ledger(d, p, market, segments, keys, bankroll=None):
    col1, col0 = odds_columns(market)
    o1, o0 = num(d,col1).to_numpy(), num(d,col0).to_numpy()
    b1,b0 = odds_profit(o1), odds_profit(o0)
    ev1,ev0 = b1*p-(1-p), b0*(1-p)-p
    has_both = np.isfinite(b1) & np.isfinite(b0)
    side1 = np.where(has_both, ev1>=ev0, p>=0.5)
    selected_p = np.where(side1,p,1-p)
    selected_odds = np.where(side1,o1,o0)
    b = np.where(side1,b1,b0)
    breakeven = 1/(b+1)
    cells = [segments["cells"].get(k, {}) for k in keys]
    neff = np.array([c.get("n_eff",0.0) for c in cells])
    n = np.array([c.get("n",0) for c in cells])
    segment_health = np.array([c.get("health","Watch") for c in cells])
    market_health = segments.get("market_health","Stable")
    severity={"Strengthening":0,"Stable":1,"Watch":2,"Degrading":3,"Broken":4}
    health = np.array([market_health if severity[market_health]>severity[h] else h for h in segment_health])
    health_factor = np.array([HEALTH_WEIGHTS[h] for h in health])
    push = np.array([c.get("push_rate",segments["global_push_rate"]) for c in cells])
    if market!="Moneyline":
        line=num(d,"away_spread" if market=="Spread" else "total_line").to_numpy()
        push=np.where(np.isfinite(line)&np.isclose(line,np.round(line)),push,0.0)
    se = np.sqrt(selected_p*(1-selected_p)/np.maximum(neff,1))
    evidence = norm.cdf((selected_p-breakeven)/se)
    power = np.clip(2*(evidence-0.5),0,1)
    conditional_ev = b*selected_p-(1-selected_p)
    full = np.maximum(0, conditional_ev/b)
    tiers = np.where(conditional_ev<=0, "Pass", np.where(evidence>=.975,"A",np.where(evidence>=.90,"B+",np.where(evidence>=.75,"B","Lean"))))
    tiers = np.where(np.isfinite(b), tiers, "Unpriced")
    # Price and input-timing verification gate a stake; probabilities stay unchanged.
    rating_safe = boolean(d,"pregame_no_future_results").to_numpy()
    executable = verified(d,market).to_numpy() & np.isfinite(b) & rating_safe & (neff>0)
    adjusted = np.where(executable, full*power*health_factor,0.0)
    names = {"Spread": ("Away", "Home"), "Moneyline": ("Away", "Home"), "Total": ("Over", "Under")}[market]
    out = pd.DataFrame(index=d.index)
    for c in ["game_id","season","game_date","away_team","home_team","away_spread","total_line"]:
        out[c] = d[c] if c in d else np.nan
    out["market"] = market
    out["p_positive_conditional_nonpush"] = p
    out["selected_side"] = np.where(side1,*names)
    out["model_probability_conditional_nonpush"] = selected_p
    out["estimated_push_probability"] = push
    out["quoted_american_odds"] = selected_odds
    out["breakeven_probability"] = breakeven
    out["expected_unit_net_at_quote"] = (1-push)*conditional_ev
    out["segment"] = keys
    out["evidence_n_unique_games"] = n
    out["effective_n_date_cluster"] = neff
    out["probability_edge_positive"] = evidence
    out["evidence_power"] = power
    out["tier"] = tiers
    out["segment_health"] = segment_health
    out["market_health"] = market_health
    out["model_health"] = health
    out["market_health_price_season"] = segments.get("market_health_price_season",np.nan)
    out["health_stake_multiplier"] = health_factor
    out["full_kelly_fraction_at_quote"] = full
    out["adjusted_kelly_fraction_executable"] = adjusted
    out["quote_verified_before_tip"] = verified(d,market).to_numpy()
    out["stake_eligible"] = executable & (conditional_ev>0)
    out["final_stake_for_user_bankroll"] = adjusted*bankroll if bankroll is not None else np.nan
    out["cash_bet_status"] = "Model simulation / no bet executed"
    for c in ["rating_projection_away_margin","rating_projection_total","rating_projection_edge_to_market"]:
        if c in d: out[c]=d[c]
    y,pushed = targets(d,market)
    chosen_y = np.where(side1,y,1-y)
    out["selected_result"] = np.where(pushed,"Push",np.where(np.isfinite(chosen_y),np.where(chosen_y==1,"Win","Loss"),"Unknown"))
    out["realized_unit_net_at_quote"] = np.where(np.isfinite(b),np.where(pushed,0,np.where(chosen_y==1,b,np.where(chosen_y==0,-1,np.nan))),np.nan)
    if market in ["Spread","Total"]:
        # Clearly separated scenario: this is never substituted for archived odds.
        scenario_side1 = p>=.5
        sp = np.maximum(p,1-p)
        sb = 100/110
        sy = np.where(scenario_side1,y,1-y)
        out["illustrative_minus110_probability"] = sp
        out["illustrative_minus110_ev"] = (1-push)*(sb*sp-(1-sp))
        out["illustrative_minus110_full_kelly"] = np.maximum(0,(sb*sp-(1-sp))/sb)
        out["illustrative_minus110_result"] = np.where(pushed,"Push",np.where(np.isfinite(sy),np.where(sy==1,"Win","Loss"),"Unknown"))
        out["illustrative_minus110_unit_net"] = np.where(pushed,0,np.where(sy==1,sb,np.where(sy==0,-1,np.nan)))
    return out


def predict_bundle(bundle, d, bankroll=None):
    ledgers = []
    for market in MARKETS:
        eligible = market_mask(d, market)
        dm = d.loc[eligible].copy()
        if not len(dm):
            continue
        spec = bundle["markets"][market]
        proj=spec["base_models"]["SRS_Projection"]["estimator"].predict(feature_table(dm,market,projection=True))
        if market=="Total":
            dm["rating_projection_total"]=proj
            dm["rating_projection_edge_to_market"]=proj-num(dm,"total_line").to_numpy()
        else:
            dm["rating_projection_away_margin"]=proj
            dm["rating_projection_edge_to_market"]=proj+num(dm,"away_spread").to_numpy() if market=="Spread" else proj
        p = calibrate(spec["calibrators"]["Logistic"], predict_base(spec["base_models"]["Logistic"],dm,market))
        p,keys = apply_segments(spec["segments"],dm,p,market)
        ledgers.append(risk_ledger(dm,p,market,spec["segments"],keys,bankroll))
    return pd.concat(ledgers,ignore_index=True) if ledgers else pd.DataFrame()
