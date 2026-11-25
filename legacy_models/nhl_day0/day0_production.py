#!/usr/bin/env python3
"""Freeze NHL October-25 Day-0 k=200 research parameters and score a pregame quote slate.

Deliberately makes no wager authorizations. This is the *current* champion router,
not a rewrite of the October-25 frozen historical scripts or their historical rows.
The new pairwise projection is a versioned, unvalidated postprocessor.
"""
import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
K = 200


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def odds_p(x):
    x = float(x)
    if abs(x) < 100:
        raise ValueError(f"Invalid American odds: {x}")
    return 100 / (x + 100) if x > 0 else -x / (100 - x)


def payout(x):
    return x / 100 if x > 0 else 100 / -x


def no_vig(x, y):
    a, b = odds_p(x), odds_p(y)
    return a / (a + b), b / (a + b)


def historical_segments(path):
    groups = defaultdict(list)
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if int(r["year"]) > 2025:
                raise ValueError("Training cannot contain a post-2025 result")
            groups[(r["market"], r["side"], r["segment"])].append(r)
    pars = {}
    for (market, side, segment), rows in sorted(groups.items()):
        resolved = [r for r in rows if not int(r["push"])]
        residual_sum = sum(float(r["outcome"]) - float(r["p_market"]) for r in resolved)
        n = len(resolved)
        key = f"{market}|{side}|{segment}"
        pars[key] = {
            "market": market, "side": side, "segment": segment,
            "training_resolved": n, "training_quotes": len(rows),
            "residual_sum": residual_sum,
            "shrunken_delta": residual_sum / (n + K),
            "push_rate": sum(int(r["push"]) for r in rows) / len(rows) if market == "OU" else 0.0,
        }
    return pars


def parse_official_schedule(path, game_date):
    data = json.loads(Path(path).read_text())
    week = next((w for w in data["gameWeek"] if w["date"] == game_date), None)
    if week is None:
        raise ValueError("Target date absent from official NHL schedule")
    return {
        (g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]): {
            "game_id": str(g["id"]),
            "start_utc": g["startTimeUTC"],
            "away": g["awayTeam"]["abbrev"],
            "home": g["homeTeam"]["abbrev"],
            "status": g.get("gameState", "SCHEDULED"),
        }
        for g in week["games"]
    }


def parse_web_snapshot(path, schedule):
    raw = Path(path).read_text(encoding="utf-8")
    metadata = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line and not line.startswith("L"))
    captured = datetime.fromisoformat(metadata["local_recorded_time"])
    if captured.tzinfo is None:
        raise ValueError("Snapshot record must be timezone aware")
    # The printed bookmaker names are independent observations; mapping is only
    # used for matching exact team orientation against the official schedule.
    names = {
        "Columbus Blue Jackets": "CBJ", "Philadelphia Flyers": "PHI",
        "Boston Bruins": "BOS", "Carolina Hurricanes": "CAR",
        "Florida Panthers": "FLA", "Winnipeg Jets": "WPG",
        "New York Islanders": "NYI", "Nashville Predators": "NSH",
        "New Jersey Devils": "NJD", "Dallas Stars": "DAL",
        "Montreal Canadiens": "MTL", "St. Louis Blues": "STL",
        "Minnesota Wild": "MIN", "Utah Mammoth": "UTA",
        "Ottawa Senators": "OTT", "Vegas Golden Knights": "VGK",
        "Vancouver Canucks": "VAN", "Anaheim Ducks": "ANA",
        "Buffalo Sabres": "BUF", "San Jose Sharks": "SJS",
        "Los Angeles Kings": "LAK", "Chicago Blackhawks": "CHI",
    }
    parsed = []
    current = None
    for raw_line in raw.splitlines():
        mt = re.match(r"^L(\d+):\s*(.*)$", raw_line)
        if not mt or not 497 <= int(mt[1]) <= 743:
            continue
        body = mt[2].strip()
        if body in names:
            if current:
                parsed.append(current)
            current = {"abbr": names[body], "book_name": body}
            continue
        if not current:
            continue
        pl = re.fullmatch(r"([+-])1½\s+([+-]\d+|Ev) Added", body)
        if pl:
            current["pl_line"] = 1.5 if pl[1] == "+" else -1.5
            current["pl_price"] = 100 if pl[2] == "Ev" else int(pl[2])
            continue
        total = re.fullmatch(r"([OU])\s*(\d+)(½)?\s+([+-]\d+|Ev) Added", body)
        if total:
            current["total_side"] = total[1]
            current["total_line"] = float(total[2]) + (0.5 if total[3] else 0)
            current["total_price"] = 100 if total[4] == "Ev" else int(total[4])
            continue
        money = re.fullmatch(r"([+-]\d+|Ev) Added", body)
        if money:
            current["ml_price"] = 100 if money[1] == "Ev" else int(money[1])
    if current:
        parsed.append(current)
    if len(parsed) % 2:
        raise ValueError("Odd number of bookmaker team quote rows")

    out = []
    for i in range(0, len(parsed), 2):
        a, h = parsed[i:i+2]
        ident = (a["abbr"], h["abbr"])
        if ident not in schedule:
            raise ValueError(f"Bookmaker quote not matched to official schedule: {ident}")
        if set(a) != set(h) or not all(k in a for k in ("ml_price", "pl_price", "total_price", "pl_line", "total_line", "total_side")):
            raise ValueError(f"Incomplete paired market quote for {ident}")
        if a["pl_line"] != -h["pl_line"] or a["total_line"] != h["total_line"]:
            raise ValueError(f"Inconsistent exact spreads / totals for {ident}")
        if a["total_side"] != "O" or h["total_side"] != "U":
            raise ValueError(f"Nonmatching Over/Under quote orientation for {ident}")
        kickoff = datetime.fromisoformat(schedule[ident]["start_utc"].replace("Z", "+00:00"))
        if captured.astimezone(timezone.utc) >= kickoff:
            raise ValueError(f"Cannot claim pregame quote after game start: {ident}")
        out.append(dict(**schedule[ident], quote_away=a, quote_home=h))
    if len({q["game_id"] for q in out}) != len(out):
        raise ValueError("Duplicate game quote")
    return out, metadata


def ml_segment(odds):
    if odds < 0:
        return "fav_heavy" if odds <= -200 else "fav_moderate"
    return "dog_large" if odds >= 200 else "dog_moderate"


def pl_segment(line, strength):
    fav = line == -1.5
    if fav:
        return "favorite_-1.5_strong" if strength >= 0.65 else "favorite_-1.5_other"
    return "underdog_+1.5_strongfav" if strength >= 0.65 else "underdog_+1.5_other"


def total_segment(side, line):
    return side + "_" + ("low_le5.5" if line <= 5.5 else "six" if line == 6 else "high_ge6.5")


def evaluate_prob(quote, market, side, segment, q, params):
    key = f"{market}|{side}|{segment}"
    fitted = params.get(key)
    delta = fitted["shrunken_delta"] if fitted else 0.0
    return dict(market=market, segment=segment, side=side, quote=quote,
                no_vig_probability=q,
                fitted_segment_count=fitted["training_resolved"] if fitted else 0,
                training_delta=delta,
                raw_conditional_p=max(0.001, min(0.999, q + delta)),
                p_push=fitted["push_rate"] if fitted else 0.0,
                offset_source="PRIOR_2021_2025" if fitted else "EXPLICIT_MARKET_ONLY_UNTRAINED_SEGMENT")


def enforce_pair(left, right):
    den = left["raw_conditional_p"] + right["raw_conditional_p"]
    left["coherent_conditional_p"] = left["raw_conditional_p"] / den
    right["coherent_conditional_p"] = 1 - left["coherent_conditional_p"]
    left["coherence_adjustment"] = left["coherent_conditional_p"] - left["raw_conditional_p"]
    right["coherence_adjustment"] = right["coherent_conditional_p"] - right["raw_conditional_p"]


def make_contract(model, role, game, market, selection, line, price, p_market, p_win, p_push,
                  note, raw=None, source_label=""):
    p_loss = None if p_win is None else 1 - p_win - p_push
    b = payout(price)
    ev = None if p_win is None else p_win * b - p_loss
    full = None if ev is None else max(0.0, ev / (b * (p_win + p_loss))) if p_win + p_loss > 0 else 0.0
    signal = ("Research candidate" if ev is not None and ev > 0 else "No Bet / Research & Unapproved")
    return {
        "date": "2026-10-27", "game_id": game["game_id"], "start_utc": game["start_utc"],
        "game": game["away"] + " @ " + game["home"], "market": market,
        "selection": selection, "line": line, "american_odds": price,
        "model": model, "model_role": role, "no_vig_p": p_market,
        "model_p_win": p_win, "model_p_loss": p_loss, "model_p_push": p_push if p_win is not None else None,
        "model_ev": ev, "full_kelly_diagnostic": full, "adjusted_kelly": None,
        "tier": "Lean (unapproved research)" if ev is not None and ev > 0 else "Pass / Not scored",
        "health": "Watch", "display_section": signal,
        "research_status": note, "authorized_stake_usd": 0.0,
        "raw_probability_audit": raw, "source_label": source_label,
    }


def score_games(games, params):
    out = []
    audit = []
    for g in games:
        a, h = g["quote_away"], g["quote_home"]
        qm_a, qm_h = no_vig(a["ml_price"], h["ml_price"])
        ml_a = evaluate_prob(a["ml_price"], "ML", "away", ml_segment(a["ml_price"]), qm_a, params)
        ml_h = evaluate_prob(h["ml_price"], "ML", "home", ml_segment(h["ml_price"]), qm_h, params)
        enforce_pair(ml_a, ml_h)
        ml_p = {"away": ml_a["coherent_conditional_p"], "home": ml_h["coherent_conditional_p"]}

        qp_a, qp_h = no_vig(a["pl_price"], h["pl_price"])
        strength = max(qm_a, qm_h)
        pl_a = evaluate_prob(a["pl_price"], "PL", "away", pl_segment(a["pl_line"], strength), qp_a, params)
        pl_h = evaluate_prob(h["pl_price"], "PL", "home", pl_segment(h["pl_line"], strength), qp_h, params)
        enforce_pair(pl_a, pl_h)
        # Exact win-margin/ML coherence is a projection, NOT an independently
        # calibrated PL V1 replacement; record any change for audit.
        if a["pl_line"] == -1.5 and pl_a["coherent_conditional_p"] > ml_p["away"]:
            pl_a["coherent_conditional_p"] = ml_p["away"]
            pl_h["coherent_conditional_p"] = 1 - ml_p["away"]
        if h["pl_line"] == -1.5 and pl_h["coherent_conditional_p"] > ml_p["home"]:
            pl_h["coherent_conditional_p"] = ml_p["home"]
            pl_a["coherent_conditional_p"] = 1 - ml_p["home"]

        qt_o, qt_u = no_vig(a["total_price"], h["total_price"])
        ou_o = evaluate_prob(a["total_price"], "OU", "over", total_segment("over", a["total_line"]), qt_o, params)
        ou_u = evaluate_prob(h["total_price"], "OU", "under", total_segment("under", h["total_line"]), qt_u, params)
        enforce_pair(ou_o, ou_u)
        push = (ou_o["p_push"] + ou_u["p_push"]) / 2 if float(a["total_line"]).is_integer() else 0.0

        for side, rec, book in [("away", ml_a, a), ("home", ml_h, h)]:
            out.append(make_contract("NHL-ML-DAY0-V1-2026-10-25", "CHAMPION", g, "ML", g[side], None, book["ml_price"],rec["no_vig_probability"],rec["coherent_conditional_p"],0.0,"FROZEN_THROUGH_2025__COHERENCE_ROUTER_REV1__UNAPPROVED",rec["raw_conditional_p"],"BetUS direct page"))
            out.append(make_contract("NHL ML V3", "CHALLENGER", g, "ML", g[side], None, book["ml_price"],rec["no_vig_probability"],rec["no_vig_probability"],0.0,"MARKET_ANCHOR_NO_INDEPENDENT_EDGE",source_label="BetUS direct page"))
        for side, rec, book in [("away", pl_a, a), ("home", pl_h, h)]:
            label=f'{g[side]} {book["pl_line"]:+g}'
            out.append(make_contract("NHL-PL-DAY0-V1-2026-10-25", "CHAMPION", g, "PL",label,book["pl_line"],book["pl_price"],rec["no_vig_probability"],rec["coherent_conditional_p"],0.0,"FROZEN_THROUGH_2025__COHERENCE_ROUTER_REV1__UNAPPROVED",rec["raw_conditional_p"],"BetUS direct page"))
            out.append(make_contract("NHL PL V1", "CHALLENGER", g, "PL",label,book["pl_line"],book["pl_price"],rec["no_vig_probability"],None,0.0,"NOT_SCORED_NO_GAME_SPECIFIC_ORIENTED_PL_V1_PROBABILITY",source_label="BetUS direct page"))
        for side, rec, book in [("over", ou_o, a), ("under", ou_u, h)]:
            out.append(make_contract("NHL-OU-DAY0-V1-2026-10-25", "CHAMPION", g, "OU",side.title(),book["total_line"],book["total_price"],rec["no_vig_probability"],rec["coherent_conditional_p"]*(1-push),push,"FROZEN_THROUGH_2025__COHERENCE_ROUTER_REV1__UNAPPROVED",rec["raw_conditional_p"],"BetUS direct page"))
            out.append(make_contract("NHL V15 Conditional Count", "CHALLENGER", g, "OU",side.title(),book["total_line"],book["total_price"],rec["no_vig_probability"],None,0.0,"NOT_SCORED_PENDING_CERTIFIED_2026_27_CURRENT_SEASON_FEATURES",source_label="BetUS direct page"))

        audit.append(dict(game_id=g["game_id"],game=g["away"]+" @ "+g["home"],
                          ml_complement_residual=ml_a["coherent_conditional_p"]+ml_h["coherent_conditional_p"]-1,
                          pl_complement_residual=pl_a["coherent_conditional_p"]+pl_h["coherent_conditional_p"]-1,
                          total_probability_residual=ou_o["coherent_conditional_p"]*(1-push)+ou_u["coherent_conditional_p"]*(1-push)+push-1,
                          favorite_margin_constraint=(pl_a["coherent_conditional_p"]<=ml_p["away"]+1e-12) if a["pl_line"]==-1.5 else (pl_h["coherent_conditional_p"]<=ml_p["home"]+1e-12),
                          max_ml_pair_adjustment=max(abs(ml_a["coherence_adjustment"]),abs(ml_h["coherence_adjustment"])),
                          max_pl_pair_adjustment=max(abs(pl_a["coherent_conditional_p"]-pl_a["raw_conditional_p"]),abs(pl_h["coherent_conditional_p"]-pl_h["raw_conditional_p"])),
                          pl_signed_sides=f'{a["pl_line"]:+g}/{h["pl_line"]:+g}',total_line=a["total_line"],push_probability=push))
    return out, audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controls", required=True)
    ap.add_argument("--schedule", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--game-date", default="2026-10-27")
    args = ap.parse_args()
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    params = historical_segments(args.controls)
    schedule = parse_official_schedule(args.schedule, args.game_date)
    quotes, meta = parse_web_snapshot(args.snapshot, schedule)
    ledger, audit = score_games(quotes, params)
    if not all(abs(x[k]) < 1e-12 for x in audit for k in ("ml_complement_residual", "pl_complement_residual", "total_probability_residual")):
        raise ValueError("Outcome market probability coherence failed")
    if not all(x["favorite_margin_constraint"] for x in audit):
        raise ValueError("Puck-line/moneyline margin coherence failed")
    if any(x["authorized_stake_usd"] != 0 for x in ledger):
        raise ValueError("Research wager authorization unexpectedly enabled")
    prediction_time = datetime.now(timezone.utc).isoformat()
    write_json(outdir/"DAY0_2026_27_FROZEN_SEGMENT_PARAMETERS.json", dict(
        model="NHL_DAY0_THREE_MARKET_K200_PRIOR_THROUGH_2025",
        adjustment_method="n/(n+200) times empirical residual versus no-vig book probabilities",
        max_training_season_end=2025,
        controls_sha256=sha(args.controls),
        implementation_sha256=sha(__file__),
        created_utc=prediction_time,
        conditional_pair_projection="FROZEN_POSTPROCESS_REV1__RESEARCH_UNVALIDATED",
        coefficients=params,
    ))
    write_json(outdir/"2026_10_27_DAY0_PROSPECTIVE_SNAPSHOT.json", dict(
        created_utc=prediction_time,bookmaker="BetUS",bookmaker_page=meta.get("source_url"),
        quote_source="web-open recorded at " + meta["local_recorded_time"],
        quote_quality=meta["odds_time_classification"],
        comparison_status="PROSPECTIVE_RESEARCH__NOT_AUTHORIZED",
        game_count=len(quotes),game_ids=[q["game_id"] for q in quotes],
        missing_game_ids=[g["game_id"] for key,g in schedule.items() if key not in {(q["away"],q["home"]) for q in quotes}],
        models={"ML":"NHL-ML-DAY0-V1-2026-10-25", "PL":"NHL-PL-DAY0-V1-2026-10-25", "OU":"NHL-OU-DAY0-V1-2026-10-25"},
        quote_sha256=sha(args.snapshot),schedule_sha256=sha(args.schedule),
        training_control_sha256=sha(args.controls),
        frozen_coefficients_sha256=sha(outdir/"DAY0_2026_27_FROZEN_SEGMENT_PARAMETERS.json"),
        scorer_sha256=sha(__file__),
        authorization_status="RESEARCH_ONLY_ZERO_STAKES",
    ))
    write_json(outdir/"2026_10_27_DAY0_ALL_MODEL_CONTRACTS.json", ledger)
    write_json(outdir/"2026_10_27_PROBABILITY_COHERENCE_AUDIT.json", audit)
    summary = defaultdict(int)
    for r in ledger:
        summary[(r["market"],r["model_role"])] += 1
    print(json.dumps(dict(games=len(quotes),schedule_games=len(schedule),contracts=len(ledger),
                          positive_ev_champion=sum(r["model_role"]=="CHAMPION" and r["model_ev"] is not None and r["model_ev"]>0 for r in ledger),
                          model_roles={"/".join(k):v for k,v in sorted(summary.items())},
                          max_probability_projection=max(max(a["max_ml_pair_adjustment"],a["max_pl_pair_adjustment"]) for a in audit),
                          output=str(outdir)),indent=2))


if __name__ == "__main__":
    main()
