"""DQ-13: raw sportsbook ticket ledger, built from the raw Bovada transactions only.

Every BGS-SB-* raw transaction carries the bet reference (``aggregate.wallet.references``). A ticket's
lifecycle is PL (placed: debit of the risk), ST (settled: credit of the payout, 0 for a loss), US
(unsettled: a correction, followed by a new ST) and VD (void: refund). The ticket's net P&L is the sum of
the wallet deltas of its lifecycle, across fund types (bonus funds included, as in the P&L baseline).

The ledger is checked against the P&L baseline: for each ticket in both, raw net P&L and stake must equal
the baseline to the cent (gates). Tickets not in the baseline, and baseline-open tickets that have
settled since, are what the baseline does not contain yet. A ticket whose placement falls before the
covered raw time is ``PLACEMENT_NOT_COVERED``; its P&L is derived from the settlement and the risk field
and marked as such, never assumed zero.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from gambling.accounts.exports import _get, to_utc

CHICAGO = ZoneInfo("America/Chicago")
TAG = re.compile(r"/\*.*?\*/")
SEED = re.compile(r"^\(\d+\)\s*")
SPORT = {"Hockey - NHL": "NHL", "Basketball - NBA": "NBA", "Basketball - NCAA Men": "NCAABB",
         "American Football - NFL": "NFL", "American Football - College Football": "NCAAFB"}
MARKET = {"Head To Head": "Moneyline", "Moneyline": "Moneyline", "Main Dynamic Asian Handicap": "Spread",
          "Main Dynamic Asian Puck Line": "Spread", "Handicap - Asian": "Spread", "Point Spread": "Spread",
          "Puck Line": "Spread", "Main Dynamic Over/Under": "Total", "Total": "Total"}
MODEL_SPORTS = set(SPORT.values())


def clean(text: Optional[str]) -> Optional[str]:
    return None if text is None else TAG.sub("", text).strip().rstrip(" -").strip()


def cents(x) -> int:
    return int((Decimal(str(x)) * 100).to_integral_value())


def american(p) -> Optional[float]:
    if p is None:
        return None
    s = str(p).strip().upper()
    if s in ("EVEN", "EV"):
        return 100.0
    try:
        return float(s)
    except ValueError:
        return None


def _teams(event_desc: Optional[str]):
    d = clean(event_desc) or ""
    if " @ " not in d:
        return None, None
    a, h = d.split(" @ ", 1)
    return SEED.sub("", a.strip()), SEED.sub("", h.strip())


def _leg(sel: dict) -> dict:
    away, home = _teams(_get(sel, "event.description"))
    path = clean(_get(sel, "event.path"))
    raw_market = _get(sel, "market.description")
    desc = clean(sel.get("description"))
    if re.match(r"^(Over|Under)\b", desc or ""):
        direction = desc.split()[0]
    elif away and desc and (desc == away or desc.startswith(away + " ")):
        direction = "Away"
    elif home and desc and (desc == home or desc.startswith(home + " ")):
        direction = "Home"
    else:
        direction = None
    return dict(sport=SPORT.get(path, path), path=path, market=MARKET.get(raw_market, raw_market),
                market_raw=raw_market, selection=desc, direction=direction, price_american=american(sel.get("price")),
                period=sel.get("period"), event_id=_get(sel, "event.id"), away=away, home=home,
                event_date=_get(sel, "event.date"))


def build_tickets(raw: list[dict], baseline_settled: dict, baseline_open: dict, data_through: Optional[date],
                  iss) -> tuple[dict, dict]:
    """Return (tickets by reference, gate tuples). ``iss`` is the cleanse Issues log."""
    groups = defaultdict(list)
    for it in raw:
        cat = _get(it, "aggregate.wallet.category") or ""
        if not cat.startswith("BGS-SB"):
            continue
        refs = _get(it, "aggregate.wallet.references") or []
        if len(refs) != 1:
            iss.add("DQ-13", "GATE", "raw_transactions", it["__id"], "SPORTSBOOK_ITEM_WITHOUT_SINGLE_REFERENCE",
                    "references", json.dumps(refs))
            continue
        groups[str(refs[0])].append(it)
    tickets = {}
    for ref, items in sorted(groups.items()):
        items.sort(key=lambda x: (to_utc(x.get("timestamp")), x["__id"]))
        cats = [(_get(x, "aggregate.wallet.category") or "")[-2:] for x in items]
        deltas = [Decimal(str(_get(x, "aggregate.wallet.delta.total") or 0)) for x in items]
        placed = next((x for x in items if cats[items.index(x)] == "PL"), None)
        info = placed or items[0]
        sports = _get(info, "aggregate.sports") or {}
        legs = [_leg(s) for s in sports.get("selections") or []]
        risk = cents(sports.get("risk") or 0)
        # final state: the last ST/VD that is not followed by an unsettlement
        state = "OPEN"
        for c in cats:
            if c in ("ST", "VD"):
                state = "VOID" if c == "VD" else "SETTLED"
            elif c == "US":
                state = "OPEN"
        settled_at = next((to_utc(items[i].get("timestamp")) for i in range(len(items) - 1, -1, -1)
                           if cats[i] in ("ST", "VD")), None) if state != "OPEN" else None
        if placed is not None:
            net = cents(sum(deltas)) if state != "OPEN" else None
            basis = "RAW_LIFECYCLE" if net is not None else "NONE"
            status = state
        else:
            net = cents(sum(deltas)) - risk if state != "OPEN" else None
            basis = "SETTLEMENT_MINUS_RISK" if net is not None else "NONE"
            status = "PLACEMENT_NOT_COVERED"
            iss.add("DQ-13", "MEDIUM", "raw_transactions", ref, "PLACEMENT_NOT_IN_COVERED_RAW", "placed_utc", None,
                    None, f"lifecycle {cats}; P&L = settlement credits - risk field" if net is not None else
                    f"lifecycle {cats}")
        if state == "VOID":
            result = "VOID"
        elif state == "OPEN":
            result = "OPEN"
        else:
            payout = net + risk
            result = ("LOSS" if payout == 0 else "PUSH" if payout == risk else
                      "WIN" if payout > risk else "OTHER")
        if "US" in cats:
            iss.add("DQ-13", "LOW", "raw_transactions", ref, "RESETTLED", "lifecycle", json.dumps(cats), result,
                    "unsettlement followed by a new settlement; final settlement used")
        if result == "OTHER":
            iss.add("DQ-13", "HIGH", "raw_transactions", ref, "PARTIAL_PAYOUT", "net_pnl_cents", None, net,
                    "payout between 0 and the risk (cash-out or partial); not classified")
        p_utc = to_utc(placed.get("timestamp")) if placed else None
        p_date = p_utc.astimezone(CHICAGO).date() if p_utc else None
        live = any("Live" in (l["period"] or "") for l in legs)
        single = legs[0] if len(legs) == 1 else None
        market = single["market"] if single else "MULTI"
        scope = ("MODEL_MARKET" if single and market in ("Moneyline", "Spread", "Total")
                 and single["sport"] in MODEL_SPORTS and not live else "OUT_OF_MODEL_SCOPE")
        b_status = ("BASELINE_SETTLED" if ref in baseline_settled else
                    "BASELINE_OPEN" if ref in baseline_open else "NOT_IN_BASELINE")
        period = ("UNKNOWN" if p_date is None or data_through is None else
                  "THROUGH_BASELINE" if p_date <= data_through else "AFTER_BASELINE")
        funds = _get(placed, "aggregate.wallet.delta.byType") if placed else None
        tickets[ref] = dict(
            bovada_reference=ref, ticket_status=status, lifecycle=json.dumps(cats),
            raw_transaction_ids=json.dumps([x["__id"] for x in items]),
            placed_utc=p_utc.isoformat() if p_utc else None, placed_date_chicago=p_date.isoformat() if p_date else None,
            settled_utc=settled_at.isoformat() if settled_at else None, bet_type=sports.get("betDescription"),
            legs=len(legs), legs_json=json.dumps(legs, sort_keys=True),
            sport=single["sport"] if single else "MULTI", market=market, market_scope=scope, is_live=int(live),
            matchup=f"{single['away']} @ {single['home']}" if single and single["away"] else None,
            away=single["away"] if single else None, home=single["home"] if single else None,
            selection=single["selection"] if single else " | ".join(l["selection"] or "" for l in legs),
            direction=single["direction"] if single else None, price_american=american(sports.get("price")),
            risk_cents=risk, to_win_cents=cents(sports["win"]) if sports.get("win") is not None else None,
            funds_json=json.dumps({k: v.get("total") for k, v in funds.items()}, sort_keys=True)
            if isinstance(funds, dict) else None,
            result=result, net_pnl_cents=net, net_pnl_basis=basis, baseline_status=b_status, period=period)
        if b_status == "NOT_IN_BASELINE" and period == "THROUGH_BASELINE":
            iss.add("DQ-13", "MEDIUM", "raw_transactions", ref, "TICKET_ON_OR_BEFORE_CUTOFF_NOT_IN_BASELINE",
                    "placed_date_chicago", None, p_date.isoformat(),
                    "placed on or before the baseline's data-through date but not in the baseline; "
                    "counted with the tickets after the baseline")
    # cross-check against the baseline
    pnl_bad, stake_bad, compared = [], [], 0
    for ref, t in tickets.items():
        b = baseline_settled.get(ref)
        if b is None or t["net_pnl_cents"] is None:
            continue
        compared += 1
        if t["net_pnl_cents"] != b["net_pnl_cents"]:
            pnl_bad.append(ref)
            iss.add("DQ-13", "GATE", "raw_transactions", ref, "RAW_PNL_DIFFERS_FROM_BASELINE", "net_pnl_cents",
                    b["net_pnl_cents"], t["net_pnl_cents"])
        if t["risk_cents"] != b["stake_cents"]:
            stake_bad.append(ref)
            iss.add("DQ-13", "GATE", "raw_transactions", ref, "RAW_STAKE_DIFFERS_FROM_BASELINE", "stake_cents",
                    b["stake_cents"], t["risk_cents"])
    for ref, b in baseline_open.items():
        t = tickets.get(ref)
        if t is not None and t["ticket_status"] != "OPEN":
            iss.add("DQ-13", "INFO", "raw_transactions", ref, "BASELINE_OPEN_NOW_SETTLED", "result", "OPEN",
                    t["result"], f"net {t['net_pnl_cents']} cents; settled {t['settled_utc']}")
    counts = Counter((t["baseline_status"], t["ticket_status"]) for t in tickets.values())
    iss.add("DQ-13", "INFO", "raw_transactions", None, "LEDGER_SUMMARY", None, None, None,
            json.dumps({f"{a}/{b}": n for (a, b), n in sorted(counts.items())}))
    gates = {"raw_vs_baseline_pnl_mismatches": (len(pnl_bad), 0),
             "raw_vs_baseline_stake_mismatches": (len(stake_bad), 0),
             "sportsbook_items_without_reference": (sum(1 for i in iss.rows if i["action"] ==
                                                        "SPORTSBOOK_ITEM_WITHOUT_SINGLE_REFERENCE"), 0)}
    return tickets, gates, compared


def after_baseline_summary(tickets: dict) -> dict:
    """P&L the baseline does not contain yet (settled tickets only; open tickets have none)."""
    out = defaultdict(lambda: {"tickets": 0, "stake_cents": 0, "net_pnl_cents": 0})
    for t in tickets.values():
        new = t["baseline_status"] == "NOT_IN_BASELINE" or (t["baseline_status"] == "BASELINE_OPEN"
                                                             and t["ticket_status"] != "OPEN")
        if not new or t["net_pnl_cents"] is None:
            continue
        k = t["baseline_status"]
        out[k]["tickets"] += 1
        out[k]["stake_cents"] += t["risk_cents"]
        out[k]["net_pnl_cents"] += t["net_pnl_cents"]
    return dict(out)
