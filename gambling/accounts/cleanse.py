"""DQ-01..DQ-12 cleanse of the accounts database (raw layer -> canonical tables).

Input is the raw layer only: the imported P&L baseline copy (``pnl_baseline_*``) and the raw Bovada
transactions (``latest_transactions``). The raw rows are never changed. Each run:

1. builds canonical rows in memory, logging every rule hit (including automatic fixes) as a
   ``dq_issues`` row with the raw value, the cleansed value, the action and the evidence;
2. checks the hard gates (published totals to the cent, row conservation, ticket arithmetic, unique
   keys, open tickets outside realized P&L, zero P&L for cash movements);
3. writes ``dq_runs`` + ``dq_issues`` always, and the canonical ``c_*`` rows only if every gate
   passed. A failed run publishes nothing; reports read the views over the latest PASSED run.

Re-running on the same raw layer produces the same canonical rows (deterministic; see
``fingerprint`` in the run summary). Raw-transaction matching needs no API field names: a
reference is found by scanning every scalar value of the raw items. Only wallet delta and timestamp
are used by name (the exporter's lead columns). Rules that would need an undocumented API field log
that the field is unavailable instead of guessing.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from gambling.accounts.exports import _get, to_utc
from gambling.accounts.importer import open_accounts_db
from gambling.accounts.ledger import after_baseline_summary, build_tickets
from gambling.accounts.nonsports import build_non_sports

TOOL = "gambling.accounts.cleanse/1"
MODEL_MARKETS = {"Moneyline", "Spread", "Total"}
MARKET_MAP = {"Puck line": "Spread", "Grand Salami side": "GRAND_SALAMI_SIDE",
              "Grand Salami total": "GRAND_SALAMI_TOTAL", "Parlay": "PARLAY", "Prop": "PROP"}
RESULT_MAP = {"Win": "WIN", "Loss": "LOSS", "Push": "PUSH"}
CASH_CATEGORIES = {"Deposits and withdrawals", "Internal transfer / zero-P&L"}
SUMMARY_CATEGORY = {"Casino": "casino_pnl_cents", "Poker": "poker_pnl_cents",
                    "Bonuses and rewards": "bonuses_rewards_cents"}
EXCLUDED_DUPLICATE_REASON = "Duplicate NHL ticket: second copy excluded from settled totals upstream (baseline)"
VOID_WORDS = re.compile(r"\b(void(ed)?|cancel(l?ed)?|refund(ed)?)\b", re.I)
RANK = re.compile(r"\s*\(#\d+\)")
CHICAGO = ZoneInfo("America/Chicago")


class Issues:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, rule, severity, table, row_ref, action, field=None, raw=None, cleansed=None, evidence=None):
        self.rows.append(dict(rule_id=rule, severity=severity, table_name=table, row_ref=row_ref, field=field,
                              raw_value=None if raw is None else str(raw),
                              cleansed_value=None if cleansed is None else str(cleansed), action=action,
                              evidence=evidence))


# ---------------------------------------------------------------------- helpers
def _ts(raw) -> tuple[Optional[str], str]:
    """DQ-05: UTC ISO string and precision; '.999' spreadsheet artifacts move to the next minute."""
    if raw in (None, "", "None"):
        return None, "NONE"
    dt = to_utc(raw)
    if dt.microsecond == 999000:
        dt = dt + timedelta(milliseconds=1)
        return dt.isoformat(), "MINUTE"
    if dt.second == 0 and dt.microsecond == 0:
        return dt.isoformat(), "MINUTE"
    return dt.replace(microsecond=0).isoformat() if dt.microsecond == 0 else dt.isoformat(), "SECOND"


def payout_cents(stake_cents: int, american: float) -> float:
    return stake_cents * american / 100 if american > 0 else stake_cents * 100 / -american


def _american_from_raw(item) -> Optional[float]:
    v = _get(item, "aggregate.sports.price")
    if isinstance(v, dict):
        v = v.get("american", v.get("americanOdds"))
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in ("EVEN", "EV"):
        return 100.0
    try:
        x = float(s)
    except ValueError:
        return None
    return x if abs(x) >= 100 else None


def _scalars(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _scalars(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _scalars(v, out)
    elif obj is not None:
        out.add(str(obj))


def _split_matchup(matchup: Optional[str]):
    if not matchup or " @ " not in matchup:
        return None, None
    a, h = matchup.split(" @ ", 1)
    return RANK.sub("", a).strip(), RANK.sub("", h).strip()


def _verify_time(iss, table, ref, field, raw_t, rec_utc, prec):
    """DQ-05: check a recorded time against the authoritative raw transaction time.

    If the recorded time equals the Chicago local time of the raw transaction labelled as UTC, it is corrected
    and logged; any other disagreement is flagged, not changed. Returns (utc, precision, basis).
    """
    if rec_utc is None:
        return None, "NONE", "NONE"
    if raw_t is None:
        return rec_utc, prec, "BASELINE_UNVERIFIED"
    rec = datetime.fromisoformat(rec_utc)
    diff = (rec - raw_t).total_seconds()
    local_as_utc = raw_t.astimezone(CHICAGO).replace(tzinfo=timezone.utc)
    if abs(diff) <= 60 or (prec == "MINUTE" and abs(diff) < 120):
        return rec_utc, prec, "RAW_API_CONFIRMED"
    if abs((rec - local_as_utc).total_seconds()) <= 120:
        iss.add("DQ-05", "HIGH", table, ref, "TIMEZONE_MISLABEL_CORRECTED_FROM_RAW", field, rec_utc, raw_t.isoformat(),
                f"recorded time equals the Chicago local time of the raw transaction labelled as UTC ({diff / 3600:+.1f} h)")
        return raw_t.isoformat(), "SECOND", "RAW_API_CORRECTED"
    iss.add("DQ-05", "HIGH", table, ref, f"{field.split('_')[0].upper()}_TIME_DISAGREES_WITH_RAW_KEPT", field, rec_utc,
            raw_t.isoformat(), f"difference {diff:+.0f} s is not the Chicago offset; not changed")
    return rec_utc, prec, "BASELINE_DISAGREES_WITH_RAW"


def _raw_placement(matched, by_id, stake_cents):
    """Time of the raw placement debit (wallet delta = -stake)."""
    stake_dollars = -Decimal(stake_cents) / 100
    ts = sorted(to_utc(by_id[t].get("timestamp")) for t in matched
                if _get(by_id[t], "aggregate.wallet.delta.total") is not None
                and Decimal(str(_get(by_id[t], "aggregate.wallet.delta.total"))) == stake_dollars
                and by_id[t].get("timestamp") is not None)
    return ts[0] if ts else None


def _raw_settlement(matched, by_id):
    """Time of the final raw settlement or void (sportsbook ST/VD)."""
    ts = sorted(to_utc(by_id[t].get("timestamp")) for t in matched
                if (_get(by_id[t], "aggregate.wallet.category") or "")[-3:] in ("-ST", "-VD")
                and by_id[t].get("timestamp") is not None)
    return ts[-1] if ts else None


def _verify_placed(iss, table, ref, matched, by_id, stake_cents, placed_utc, placed_prec):
    return _verify_time(iss, table, ref, "placed_utc", _raw_placement(matched, by_id, stake_cents), placed_utc,
                        placed_prec)


def _meta(con) -> dict:
    return {k: json.loads(v) for k, v in con.execute("SELECT key, json_value FROM pnl_baseline_export_metadata")}


# ---------------------------------------------------------------------- the cleanse
def build(con: sqlite3.Connection, scoring_db: Optional[Path] = None) -> dict:
    """Compute canonical rows, issues and gates (no writes)."""
    iss = Issues()
    meta = _meta(con)
    rows = [dict(zip([d[0] for d in cur.description], r)) for cur in [con.execute(
        "SELECT * FROM pnl_baseline_sportsbook_wagers ORDER BY wager_id")] for r in cur.fetchall()]
    raw = [json.loads(r[0]) | {"__id": r[1]} for r in con.execute(
        "SELECT item_json, transaction_id FROM latest_transactions ORDER BY transaction_id")]
    index = defaultdict(set)  # scalar value -> raw transaction ids
    for it in raw:
        vals = set()
        _scalars({k: v for k, v in it.items() if k != "__id"}, vals)
        for v in vals:
            index[v].add(it["__id"])
    by_id = {it["__id"]: it for it in raw}

    wagers, adjustments, exclusions = {}, [], []
    derived_refs = {}
    used_raw: set = set()
    for r in rows:
        ref = r["wager_id"]
        # DQ-01 aggregate-only settlements
        if r["result"].startswith("Settled"):
            adjustments.append(dict(adjustment_id=f"AGG-{ref}", kind="AGGREGATE_SETTLEMENT", sport=r["sport"],
                                    stake_cents=r["stake_cents"], recognized_pnl_cents=r["net_pnl_cents"],
                                    date_chicago=r["placed_date_chicago"], description=r["selection"],
                                    source_row_ref=f"pnl_baseline_sportsbook_wagers:{ref}"))
            iss.add("DQ-01", "HIGH", "sportsbook_wagers", ref, "MOVED_TO_ACCOUNTING_ADJUSTMENTS", "result", r["result"],
                    "AGGREGATE_SETTLEMENT", "rolled-up amount without odds or settlement date; kept in account totals, "
                                            "excluded from ticket counts and per-ticket ROI")
            continue
        # DQ-04 identifiers
        bref = r["bovada_reference"]
        matched = sorted(index.get(bref, set()) | index.get(str(r["source_transaction_id"] or "\0"), set())) if bref or r["source_transaction_id"] else []
        placed_utc, placed_prec = _ts(r["placed_timestamp_source"])
        if matched and not bref:
            refs = {str(x) for t in matched for x in (_get(by_id[t], "aggregate.wallet.references") or [])}
            if len(refs) == 1:
                bref_derived = refs.pop()
                matched = sorted(set(matched) | index.get(bref_derived, set()))
                iss.add("DQ-04", "MEDIUM", "sportsbook_wagers", ref, "REFERENCE_DERIVED_FROM_RAW_TRANSACTION",
                        "bovada_reference", None, bref_derived,
                        f"baseline source_transaction_id {r['source_transaction_id']} is a raw transaction of that bet")
                derived_refs[ref] = bref_derived
        if matched:
            method, key = "REFERENCE", bref or derived_refs.get(ref) or f"BTX-{matched[0]}"
        elif bref:
            method, key = "REFERENCE_NOT_IN_RAW", bref
            iss.add("DQ-04", "LOW", "sportsbook_wagers", ref, "KEY_FROM_BASELINE_REFERENCE", "bovada_reference", bref,
                    bref, "reference not found in the raw exports (outside covered time or not exported)")
        else:
            cands = []
            if placed_utc:
                p = datetime.fromisoformat(placed_utc)
                stake = -Decimal(r["stake_cents"]) / 100
                for it in raw:
                    d, t = _get(it, "aggregate.wallet.delta.total"), to_utc(it.get("timestamp"))
                    if d is not None and t is not None and Decimal(str(d)) == stake and abs((t - p).total_seconds()) <= 60 \
                            and it["__id"] not in used_raw:
                        cands.append(it["__id"])
            if len(cands) == 1:
                method, key, matched = "TIME_RISK", f"BTX-{cands[0]}", cands
                iss.add("DQ-04", "MEDIUM", "sportsbook_wagers", ref, "MATCHED_BY_TIME_AND_RISK", None, None, key,
                        "placement time within 60 s and wallet delta = -stake; unique candidate")
            else:
                method, key = "UNMATCHED", "WB-" + hashlib.sha256(ref.encode()).hexdigest()[:16]
                iss.add("DQ-04", "HIGH", "sportsbook_wagers", ref, "SYNTHETIC_KEY", "bovada_reference", None, key,
                        f"no reference; {len(cands)} time/risk candidates")
        used_raw.update(matched)
        placed_utc, placed_prec, basis = _verify_placed(iss, "sportsbook_wagers", ref, matched, by_id,
                                                        r["stake_cents"], placed_utc, placed_prec)
        if key in wagers:
            iss.add("DQ-04", "GATE", "sportsbook_wagers", ref, "DUPLICATE_CANONICAL_KEY", None, None, key)
            key = f"{key}#DUP-{ref}"
        dq = "CLEAN"
        # DQ-02 result vocabulary
        result = RESULT_MAP.get(r["result"])
        if r["result"] == "Push/Void":
            texts = set()
            for t in matched:
                _scalars({k: v for k, v in by_id[t].items() if k != "__id"}, texts)
            hit = sorted(t for t in texts if VOID_WORDS.search(t))
            result = "VOID" if hit else "PUSH"
            iss.add("DQ-02", "MEDIUM", "sportsbook_wagers", ref, "RESOLVED", "result", r["result"], result,
                    f"void/cancel/refund text in matched raw transactions: {hit[:3]}" if hit else
                    ("no void/cancel/refund text in matched raw transactions" if matched else
                     "no raw transaction matched; default PUSH per DQ-02"))
            dq = "FIXED"
        elif result is None:
            iss.add("DQ-02", "HIGH", "sportsbook_wagers", ref, "UNMAPPED_RESULT", "result", r["result"])
            result = "UNKNOWN"
            dq = "FLAGGED"
        # DQ-03 odds
        odds, odds_status = r["odds_american"], "RECORDED"
        if odds is None:
            api = [a for a in (_american_from_raw(by_id[t]) for t in matched) if a is not None]
            if api:
                odds, odds_status = api[0], "RAW_API"
                iss.add("DQ-03", "MEDIUM", "sportsbook_wagers", ref, "ODDS_FROM_RAW_API", "odds_american", None, odds)
            elif result == "WIN" and r["stake_cents"] > 0 and r["net_pnl_cents"] > 0:
                ratio = r["net_pnl_cents"] / r["stake_cents"]
                cand = round(100 * ratio) if ratio >= 1 else round(-100 / ratio)
                if abs(payout_cents(r["stake_cents"], cand) - r["net_pnl_cents"]) <= 1:
                    odds, odds_status = float(cand), "BACKSOLVED"
                    iss.add("DQ-03", "MEDIUM", "sportsbook_wagers", ref, "ODDS_BACKSOLVED_FROM_WIN", "odds_american",
                            None, cand, f"stake {r['stake_cents']} -> P&L {r['net_pnl_cents']} cents reproduced")
                else:
                    odds_status = "UNRECOVERABLE"
                    iss.add("DQ-03", "HIGH", "sportsbook_wagers", ref, "ODDS_UNRECOVERABLE", "odds_american", None, None,
                            "no integer American price reproduces the win to the cent")
            else:
                odds_status = "UNRECOVERABLE"
                iss.add("DQ-03", "HIGH", "sportsbook_wagers", ref, "ODDS_UNRECOVERABLE", "odds_american", None, None,
                        "no raw price; odds are never imputed for losses/pushes")
            dq = "FIXED" if odds is not None else "FLAGGED"
        # DQ-05 timestamps
        settled_utc, settled_prec = _ts(r["settled_timestamp_source"])
        settled_utc, settled_prec, s_basis = _verify_time(iss, "sportsbook_wagers", ref, "settled_utc",
                                                          _raw_settlement(matched, by_id), settled_utc, settled_prec)
        for fld, rawv, prec in (("placed", r["placed_timestamp_source"], placed_prec),
                                ("settled", r["settled_timestamp_source"], settled_prec)):
            if rawv and str(rawv).endswith(".999Z"):
                iss.add("DQ-05", "LOW", "sportsbook_wagers", ref, "STRIPPED_999_ARTIFACT", f"{fld}_utc", rawv,
                        placed_utc if fld == "placed" else settled_utc)
            elif prec == "NONE":
                iss.add("DQ-05", "MEDIUM", "sportsbook_wagers", ref, "TIMESTAMP_MISSING_KEPT_NULL", f"{fld}_utc")
        # DQ-06 market / direction
        market = MARKET_MAP.get(r["market"], r["market"])
        scope = "MODEL_MARKET" if market in MODEL_MARKETS else "OUT_OF_MODEL_SCOPE"
        if market != r["market"]:
            iss.add("DQ-06", "LOW", "sportsbook_wagers", ref, "MARKET_MAPPED", "market", r["market"], market)
        if scope != "MODEL_MARKET":
            iss.add("DQ-06", "INFO", "sportsbook_wagers", ref, "OUT_OF_MODEL_SCOPE", "market", r["market"], market)
        away, home = _split_matchup(r["matchup"])
        direction, dmethod = r["direction"], "RECORDED" if r["direction"] else None
        if not direction:
            sel = RANK.sub("", r["selection"] or "")
            if re.match(r"^(Over|Under)\b", sel):
                direction, dmethod = sel.split()[0], "SELECTION_OVER_UNDER"
            elif away and (sel == away or sel.startswith(away + " ")):
                direction, dmethod = "Away", "SELECTION_TEAM_MATCHUP"
            elif home and (sel == home or sel.startswith(home + " ")):
                direction, dmethod = "Home", "SELECTION_TEAM_MATCHUP"
            if direction:
                iss.add("DQ-06", "LOW", "sportsbook_wagers", ref, "DIRECTION_DERIVED", "direction", None, direction,
                        dmethod)
            else:
                iss.add("DQ-06", "MEDIUM", "sportsbook_wagers", ref, "DIRECTION_UNRESOLVED_KEPT_NULL", "direction",
                        None, None, r["selection"])
        wagers[key] = dict(
            wager_key=key, baseline_wager_id=ref, bovada_reference=bref, id_match_method=method,
            raw_transaction_ids=json.dumps(matched) if matched else None, sport=r["sport"], market_raw=r["market"],
            market=market, market_scope=scope, matchup=r["matchup"], away=away, home=home, selection=r["selection"],
            direction_raw=r["direction"], direction=direction, direction_method=dmethod, odds_raw=r["odds_raw"],
            odds_american=odds, odds_status=odds_status, stake_cents=r["stake_cents"],
            net_pnl_cents=r["net_pnl_cents"], result_raw=r["result"], result=result,
            placed_raw=r["placed_timestamp_source"], placed_utc=placed_utc, placed_precision=placed_prec,
            placed_time_basis=basis, settled_time_basis=s_basis,
            settled_raw=r["settled_timestamp_source"], settled_utc=settled_utc, settled_precision=settled_prec,
            original_frozen_tier=r["original_frozen_tier"], prebet_evidence_category=r["prebet_evidence_category"],
            retrospective_champion_tier=r["champion_tier_current"],
            retrospective_champion_model=r["champion_model_current"], source="PNL_EXPORT_20261110",
            source_row_ref=f"pnl_baseline_sportsbook_wagers:{ref}", dq_status=dq)
    # DQ-07 teams / events (crosswalk to game_key not built yet)
    for sport, n in sorted(Counter(w["sport"] for w in wagers.values()).items()):
        iss.add("DQ-07", "MEDIUM", "sportsbook_wagers", sport, "GAME_KEY_CROSSWALK_PENDING", "matchup", None, None,
                f"{n} wagers keep parsed away/home names; game_key needs the Phase 2 team crosswalk")
    # DQ-12 exclusions / prior adjustment
    dup = meta.get("excluded_duplicate_bovada_reference")
    if dup:
        present = [w for w in wagers.values() if w["bovada_reference"] == dup]
        exclusions.append(dict(exclusion_id=f"EXCL-{dup}", bovada_reference=dup, reason=EXCLUDED_DUPLICATE_REASON,
                               present_in_baseline=0, source="pnl_baseline_export_metadata"))
        iss.add("DQ-12", "INFO", "sportsbook_wagers", dup, "EXCLUSION_RECORDED", None, None, None,
                f"one copy remains as {present[0]['baseline_wager_id']} and counts; the excluded copy is not in the "
                f"baseline rows" if present else "no copy in the baseline rows")
    for a in con.execute("SELECT adjustment_id, sport, category, description, recognized_pnl_cents, date_chicago "
                         "FROM pnl_baseline_accounting_adjustments"):
        adjustments.append(dict(adjustment_id=a[0], kind="PRIOR_UNALLOCATED", sport=a[1], stake_cents=0,
                                recognized_pnl_cents=a[4], date_chicago=a[5], description=a[3],
                                source_row_ref=f"pnl_baseline_accounting_adjustments:{a[0]}"))
        if a[5] is None:
            iss.add("DQ-12", "INFO", "accounting_adjustments", a[0], "KEPT_UNDATED", "date_chicago")
    # open tickets
    opens = []
    for o in con.execute("SELECT wager_id, bovada_reference, sport, market, matchup, selection, odds_american, risk_cents, "
                         "placed_timestamp_source FROM pnl_baseline_sportsbook_open_wagers ORDER BY wager_id"):
        matched = sorted(index.get(o[1], set())) if o[1] else []
        p_utc, p_prec = _ts(o[8])
        p_utc, _, basis = _verify_placed(iss, "sportsbook_open_wagers", o[0], matched, by_id, o[7], p_utc, p_prec)
        opens.append(dict(wager_key=o[1] or "WB-" + hashlib.sha256(o[0].encode()).hexdigest()[:16],
                          bovada_reference=o[1], sport=o[2], market=o[3], matchup=o[4], selection=o[5],
                          odds_american=o[6], risk_cents=o[7], placed_utc=p_utc, placed_time_basis=basis,
                          realized_pnl_cents=0, source_row_ref=f"pnl_baseline_sportsbook_open_wagers:{o[0]}"))
    # DQ-08 non-sports keys
    ledger, collisions = {}, []
    ns_cols = [d[1] for d in con.execute("PRAGMA table_info(pnl_baseline_non_sports_transactions)")]
    for n in con.execute("SELECT * FROM pnl_baseline_non_sports_transactions ORDER BY transaction_row_id"):
        n = dict(zip(ns_cols, n))
        ts, prec = _ts(n["timestamp_utc"])
        if n["bovada_transaction_id"]:
            key, kmethod = f"BTX-{n['bovada_transaction_id']}", "BOVADA_ID"
        else:
            comp = f"{ts}|{n['category']}|{n['wallet_delta_cents']}|{n['source_period']}"
            key, kmethod = "NS-" + hashlib.sha256(comp.encode()).hexdigest()[:16], "COMPOSITE"
            iss.add("DQ-08", "LOW", "non_sports_transactions", n["transaction_row_id"], "COMPOSITE_KEY", None, None, key,
                    comp)
        if key in ledger:
            collisions.append(key)
            iss.add("DQ-08", "GATE", "non_sports_transactions", n["transaction_row_id"], "KEY_COLLISION", None, None, key,
                    f"collides with {ledger[key]['source_row_ref']}")
            continue
        ledger[key] = dict(ledger_key=key, key_method=kmethod, timestamp_utc=ts, timestamp_precision=prec,
                           category=n["category"], activity=n["activity"], wallet_delta_cents=n["wallet_delta_cents"],
                           recognized_pnl_cents=n["recognized_pnl_cents"],
                           accounting_treatment=n["accounting_treatment"],
                           bovada_transaction_id=n["bovada_transaction_id"], source_period=n["source_period"],
                           source_row_ref=f"pnl_baseline_non_sports_transactions:{n['transaction_row_id']}")
    # DQ-09 evidence links
    by_ref = {w["bovada_reference"]: w for w in wagers.values() if w["bovada_reference"]}
    by_ref.update({o["bovada_reference"]: o for o in opens if o["bovada_reference"] and o["bovada_reference"] not in by_ref})
    links = {}
    gap_h = Counter()
    mcols = [d[1] for d in con.execute("PRAGMA table_info(pnl_baseline_score_to_wager_evidence_matches)")]
    for n, m in enumerate(con.execute("SELECT * FROM pnl_baseline_score_to_wager_evidence_matches")):
        m = dict(zip(mcols, m))
        w = by_ref.get(str(m["wager_key"]))
        ref = f"pnl_baseline_score_to_wager_evidence_matches:{n}"
        if w is None:
            iss.add("DQ-09", "HIGH", "score_to_wager_evidence_matches", ref, "DROPPED_UNRESOLVED_WAGER", "wager_key",
                    m["wager_key"], None, "wager key not among canonical settled or open wagers")
            continue
        if m["scored_seconds_before_bet"] not in (None, "") and m["scored_utc"] and w.get("placed_utc"):
            implied = to_utc(m["scored_utc"]) + timedelta(seconds=float(m["scored_seconds_before_bet"]))
            gap_h[(w.get("placed_time_basis", "OPEN_TICKET"), round((implied - datetime.fromisoformat(w["placed_utc"]))
                                                                     .total_seconds() / 3600, 2))] += 1
        q = to_utc(m["quote_utc"]) if m["quote_utc"] else None
        p = datetime.fromisoformat(w["placed_utc"]) if w["placed_utc"] else None
        if q is None or p is None or p < q:
            unverified = w.get("placed_time_basis") in ("BASELINE_UNVERIFIED", "BASELINE_DISAGREES_WITH_RAW")
            iss.add("DQ-09", "MEDIUM", "score_to_wager_evidence_matches", ref,
                    "DROPPED_PLACED_BEFORE_QUOTE_TIME_UNVERIFIED" if unverified else "DROPPED_PLACED_BEFORE_QUOTE",
                    "quote_utc", m["quote_utc"], None, f"placed {w['placed_utc']}; grade {m['match_grade']}")
            continue
        lk = (w["wager_key"], str(m["score_id"]), m["score_role"])
        links[lk] = dict(wager_key=w["wager_key"], score_id=str(m["score_id"]), score_role=m["score_role"],
                         match_grade=m["match_grade"], quote_utc=q.isoformat(), placed_utc=w["placed_utc"],
                         source_row_ref=ref)
    off = {f"{b}:{h:+.2f}h": c for (b, h), c in sorted(gap_h.items())}
    shifted = sum(c for (b, h), c in gap_h.items() if abs(h) >= 1)
    iss.add("DQ-05", "HIGH" if shifted else "INFO", "score_to_wager_evidence_matches", None,
            "PLACEMENT_TIME_CROSSCHECK", "placed_utc", None, None,
            f"scored_utc + scored_seconds_before_bet vs canonical placed_utc, by time basis: {off}; "
            f"{shifted} links imply a placement at least 1 h away from the canonical time")
    # DQ-10 score reconciliation (scoring database stays authoritative)
    export_scores = {str(r[0]) for r in con.execute("SELECT score_id FROM pnl_baseline_model_scoring_history")}
    if scoring_db:
        s = sqlite3.connect(f"file:{scoring_db}?mode=ro", uri=True)
        try:
            db_scores = {str(r[0]) for r in s.execute("SELECT score_id FROM model_scores")}
        finally:
            s.close()
        iss.add("DQ-10", "MEDIUM", "model_scoring_history", None, "RECONCILED_BY_SCORE_ID", None,
                len(export_scores), len(db_scores),
                f"export-only {len(export_scores - db_scores)}, database-only {len(db_scores - export_scores)}; "
                "gambling.sqlite stays authoritative; export-only scores not imported (no release attribution check yet)")
    else:
        iss.add("DQ-10", "INFO", "model_scoring_history", None, "NOT_RUN", None, len(export_scores), None,
                "pass --scoring-db to reconcile against model_scores")
    # DQ-11 retrospective vs pre-bet
    iss.add("DQ-11", "INFO", "sportsbook_wagers", None, "COLUMNS_SEPARATED", "champion_tier_current", None,
            "retrospective_champion_tier", "authorization evidence = original_frozen_tier + prebet_evidence_category")

    # DQ-13 raw ticket ledger, cross-checked against the baseline
    b_settled = {(r["bovada_reference"] or derived_refs.get(r["wager_id"])): r for r in rows
                 if (r["bovada_reference"] or derived_refs.get(r["wager_id"])) and not r["result"].startswith("Settled")}
    b_open = {o["bovada_reference"]: o for o in opens if o["bovada_reference"]}
    through = meta.get("data_through_date")
    tickets, t_gates, compared = build_tickets(raw, b_settled, b_open,
                                               date.fromisoformat(through) if through else None, iss)
    gates = _gates(meta, rows, wagers, adjustments, exclusions, ledger, opens, links, collisions)
    gates.update({k: {"actual": a, "expected": e, "pass": a == e} for k, (a, e) in t_gates.items()})
    gates["_raw_vs_baseline_compared"] = compared
    # DQ-14 raw non-sports ledger, treatment learned from the baseline
    ns_rows = [dict(zip(ns_cols, n)) for n in con.execute("SELECT * FROM pnl_baseline_non_sports_transactions")]
    raw_ns, ns_gates, ns_summary = build_non_sports(raw, ns_rows, iss)
    gates.update({k: {"actual": a, "expected": e, "pass": a == e} for k, (a, e) in ns_gates.items()})
    return dict(raw_ns=raw_ns, ns_summary=ns_summary, tickets=tickets, wagers=wagers, adjustments=adjustments, exclusions=exclusions, ledger=ledger, opens=opens,
                links=links, issues=iss.rows, gates=gates, raw_transactions=len(raw))


def _gates(meta, rows, wagers, adjustments, exclusions, ledger, opens, links, collisions) -> dict:
    g = {}
    agg = [a for a in adjustments if a["kind"] == "AGGREGATE_SETTLEMENT"]
    prior = sum(a["recognized_pnl_cents"] for a in adjustments if a["kind"] == "PRIOR_UNALLOCATED")
    stake = sum(w["stake_cents"] for w in wagers.values()) + sum(a["stake_cents"] for a in agg)
    itemized = sum(w["net_pnl_cents"] for w in wagers.values()) + sum(a["recognized_pnl_cents"] for a in agg)
    g["stake_total"] = (stake, meta["sportsbook_stakes_cents"])
    g["itemized_pnl"] = (itemized, meta["sportsbook_itemized_pnl_cents"])
    g["prior_adjustment"] = (prior, meta["sportsbook_prior_adjustment_cents"])
    g["sportsbook_account_pnl"] = (itemized + prior, meta["sportsbook_account_pnl_cents"])
    cat = defaultdict(int)
    for l in ledger.values():
        cat[l["category"]] += l["recognized_pnl_cents"]
    for c, k in SUMMARY_CATEGORY.items():
        g[k] = (cat.get(c, 0), meta[k])
    g["all_gambling_pnl"] = (itemized + prior + sum(cat.values()), meta["all_gambling_net_pnl_cents"])
    g["settled_ticket_rows_conserved"] = (len(wagers) + len(agg) + sum(e["present_in_baseline"] for e in exclusions),
                                          len(rows))
    bad_math = []
    for w in wagers.values():
        r, s, p = w["result"], w["stake_cents"], w["net_pnl_cents"]
        if r == "LOSS" and p != -s or r in ("PUSH", "VOID") and p != 0:
            bad_math.append(w["wager_key"])
        elif r == "WIN" and w["odds_american"] is not None and abs(payout_cents(s, w["odds_american"]) - p) > 1:
            bad_math.append(w["wager_key"])
    g["ticket_arithmetic_failures"] = (len(bad_math), 0)
    g["duplicate_canonical_keys"] = (sum("#DUP-" in k for k in wagers), 0)
    g["non_sports_key_collisions"] = (len(collisions), 0)
    g["cash_movements_nonzero_pnl"] = (sum(l["recognized_pnl_cents"] != 0 for l in ledger.values()
                                           if l["category"] in CASH_CATEGORIES), 0)
    settled_refs = {w["bovada_reference"] for w in wagers.values() if w["bovada_reference"]}
    g["open_tickets_also_settled"] = (sum(o["bovada_reference"] in settled_refs for o in opens if o["bovada_reference"]), 0)
    known = set(wagers) | {o["wager_key"] for o in opens}
    g["links_unresolved"] = (sum(l["wager_key"] not in known for l in links.values()), 0)
    out = {k: {"actual": a, "expected": e, "pass": a == e} for k, (a, e) in g.items()}
    out["_failed_examples"] = {"ticket_arithmetic": bad_math[:10]}
    return out


def fingerprint(result: dict) -> str:
    payload = {k: (sorted(v.values(), key=lambda x: json.dumps(x, sort_keys=True, default=str))
                   if isinstance(v, dict) else v) for k, v in result.items()
               if k in ("wagers", "adjustments", "exclusions", "ledger", "opens", "links", "tickets", "raw_ns")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def run_cleanse(db: Path, scoring_db: Optional[Path] = None) -> dict:
    con = open_accounts_db(db, scoring_db)
    try:
        if not con.execute("SELECT 1 FROM pnl_baseline_imports").fetchone():
            raise RuntimeError("no P&L baseline imported; run `accounts import --baseline ...` first")
        baseline_sha = con.execute("SELECT baseline_sha256 FROM pnl_baseline_imports").fetchone()[0]
        res = build(con, scoring_db)
        passed = all(v["pass"] for k, v in res["gates"].items() if not k.startswith("_"))
        fp = fingerprint(res)
        summary = {"fingerprint": fp, "wagers": len(res["wagers"]), "open_wagers": len(res["opens"]),
                   "adjustments": len(res["adjustments"]), "exclusions": len(res["exclusions"]),
                   "non_sports": len(res["ledger"]), "links": len(res["links"]),
                   "raw_tickets": len(res["tickets"]), "after_baseline": after_baseline_summary(res["tickets"]),
                   "raw_non_sports": len(res["raw_ns"]), "non_sports_raw": res["ns_summary"],
                   "issues_by_rule": dict(sorted(Counter(i["rule_id"] for i in res["issues"]).items())),
                   "issues_by_severity": dict(Counter(i["severity"] for i in res["issues"]))}
        con.execute("BEGIN IMMEDIATE")
        run_id = con.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM dq_runs").fetchone()[0]
        con.execute("INSERT INTO dq_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, datetime.now(timezone.utc).isoformat(), TOOL, baseline_sha, res["raw_transactions"],
                     "PASSED" if passed else "FAILED", json.dumps(res["gates"]), json.dumps(summary)))
        con.executemany("INSERT INTO dq_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(run_id, n, i["rule_id"], i["severity"], i["table_name"], i["row_ref"], i["field"],
                          i["raw_value"], i["cleansed_value"], i["action"], i["evidence"])
                         for n, i in enumerate(res["issues"], 1)])
        if passed:
            for table, items in (("c_wagers", res["wagers"].values()), ("c_open_wagers", res["opens"]),
                                 ("c_accounting_adjustments", res["adjustments"]),
                                 ("c_accounting_exclusions", res["exclusions"]),
                                 ("c_non_sports_ledger", res["ledger"].values()), ("c_wager_links", res["links"].values()),
                                 ("c_raw_tickets", res["tickets"].values()),
                                 ("c_raw_non_sports", res["raw_ns"].values())):
                for it in items:
                    cols = ["run_id", *it]
                    con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                (run_id, *it.values()))
        con.execute("COMMIT")
        return {"run_id": run_id, "status": "PASSED" if passed else "FAILED", **summary,
                "gates": {k: v for k, v in res["gates"].items()}}
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


__all__ = ["build", "fingerprint", "payout_cents", "run_cleanse"]
