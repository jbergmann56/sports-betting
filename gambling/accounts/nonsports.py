"""DQ-14: raw non-sports ledger with treatment rules learned from the P&L baseline.

The baseline gives each non-sports row a category and a recognized P&L. Rows that carry the raw transaction
id are the evidence: for each (raw category, zero/non-zero delta) the baseline's category and treatment are
learned (RECOGNIZED: recognized = delta; NON_PNL: recognized = 0 with a non-zero delta; ZERO: delta = 0).
Gates: the learned rules must be unambiguous, and applying them must reproduce every matched baseline row
to the cent. Rows after the baseline get the learned rule. A category without evidence falls back to a
family analogy (flagged, ``ANALOGY``) or stays ``UNCLASSIFIED`` with NULL P&L -- never zero.

Poker follows the baseline's deferral: a buy-in whose tournament has no cash-out in the covered raw data is
an ``OPEN_POKER_STAKE`` (recognized 0, shown separately) instead of a loss.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Optional

from gambling.accounts.exports import _get, to_utc

# Family fallbacks for raw categories the baseline has no example of. Bonus/points credits are not
# guessed: their recognition differs by type (credit, forfeit, release), so they stay UNCLASSIFIED.
ANALOGY = (("CA-", "Casino", "RECOGNIZED"), ("PK-", "Poker", "RECOGNIZED"),
           ("FN-", "Deposits and withdrawals", "NON_PNL"), ("TR-", "Deposits and withdrawals", "NON_PNL"))
ZERO_CATEGORY = "Internal transfer / zero-P&L"


def _cents(x) -> int:
    return int((Decimal(str(x or 0)) * 100).to_integral_value())


def _treatment(delta: int, recognized: int) -> Optional[str]:
    if delta == 0 and recognized == 0:
        return "ZERO"
    if recognized == delta:
        return "RECOGNIZED"
    if recognized == 0:
        return "NON_PNL"
    return None


def build_non_sports(raw: list[dict], baseline_rows: list[dict], iss) -> tuple[dict, dict, dict]:
    """Return (rows by transaction id, gate tuples, summary)."""
    items = {it["__id"]: it for it in raw
             if not (_get(it, "aggregate.wallet.category") or "").startswith("BGS-SB")
             and _get(it, "aggregate.wallet.category")}
    by_bid = {str(r["bovada_transaction_id"]): r for r in baseline_rows if r["bovada_transaction_id"]}
    # 1) learn rules from matched baseline rows
    learned = defaultdict(Counter)
    for tid, it in items.items():
        b = by_bid.get(tid)
        if b is None:
            continue
        d = _cents(_get(it, "aggregate.wallet.delta.total"))
        t = _treatment(d, b["recognized_pnl_cents"])
        learned[(_get(it, "aggregate.wallet.category"), d == 0)][(b["category"], t)] += 1
    rules, conflicts = {}, 0
    for key, outcomes in sorted(learned.items()):
        if len(outcomes) == 1:
            rules[key] = next(iter(outcomes))
        else:
            # A conflict is only real if the treatments differ; the baseline's own labels vary for poker buy-ins.
            treatments = {t for _, t in outcomes}
            if len(treatments) == 1 and len({c for c, _ in outcomes}) == 1:
                rules[key] = next(iter(outcomes))
            else:
                conflicts += 1
                iss.add("DQ-14", "GATE", "raw_transactions", f"{key[0]}:{'zero' if key[1] else 'nonzero'}",
                        "CONFLICTING_BASELINE_TREATMENT", None, None, None, json.dumps(
                            {f"{c}/{t}": n for (c, t), n in outcomes.items()}))
    for (cat, zero), (c, t) in sorted(rules.items()):
        iss.add("DQ-14", "INFO", "raw_transactions", f"{cat}:{'zero' if zero else 'nonzero'}", "RULE_LEARNED",
                None, None, f"{c} / {t}", f"{sum(learned[(cat, zero)].values())} baseline rows")
    # 2) poker tournaments with a cash-out in the covered raw data
    cashed = {str(r) for it in items.values() if (_get(it, "aggregate.wallet.category") or "").startswith("PK-CC")
              for r in (_get(it, "aggregate.wallet.references") or [])}
    # Cut-off from the raw times of the matched rows (the baseline's own UTC labels are not trusted; DQ-05).
    last_baseline = max((to_utc(it.get("timestamp")) for tid, it in items.items() if tid in by_bid), default=None)
    out, mismatches = {}, 0
    for tid, it in sorted(items.items(), key=lambda kv: (to_utc(kv[1].get("timestamp")), kv[0])):
        cat = _get(it, "aggregate.wallet.category")
        d = _cents(_get(it, "aggregate.wallet.delta.total"))
        ts = to_utc(it.get("timestamp"))
        refs = _get(it, "aggregate.wallet.references") or []
        poker_ref = str(refs[0]) if cat.startswith("PK-") and refs else None
        b = by_bid.get(tid)
        rule = rules.get((cat, d == 0))
        if rule:
            ledger_cat, treat = rule
            prov = "BASELINE_RULE"
        elif d == 0:
            ledger_cat, treat, prov = ZERO_CATEGORY, "ZERO", "ANALOGY"
        else:
            fam = next(((c, t) for p, c, t in ANALOGY if cat.startswith(p)), None)
            ledger_cat, treat = fam if fam else (None, "UNCLASSIFIED")
            prov = "ANALOGY" if fam else "NONE"
        if cat.startswith("PK-PC") and d != 0 and poker_ref not in cashed and treat == "RECOGNIZED":
            treat = "OPEN_POKER_STAKE"
        recognized = {"RECOGNIZED": d, "NON_PNL": 0, "ZERO": 0, "OPEN_POKER_STAKE": 0}.get(treat)
        if b is not None:
            period, prov = "BASELINE_MATCHED", "BASELINE_ROW"
            if (ledger_cat, recognized) != (b["category"], b["recognized_pnl_cents"]):
                mismatches += 1
                iss.add("DQ-14", "GATE", "raw_transactions", tid, "RULE_DOES_NOT_REPRODUCE_BASELINE_ROW", None,
                        f"{b['category']} {b['recognized_pnl_cents']}", f"{ledger_cat} {recognized}",
                        b["transaction_row_id"])
            ledger_cat, recognized, treat = b["category"], b["recognized_pnl_cents"], treat
        elif last_baseline is not None and ts <= last_baseline:
            period = "BASELINE_PERIOD_UNMATCHED"
        else:
            period = "AFTER_BASELINE"
        if period == "AFTER_BASELINE" and prov in ("ANALOGY", "NONE") and d != 0:
            iss.add("DQ-14", "HIGH" if treat == "UNCLASSIFIED" else "MEDIUM", "raw_transactions", tid,
                    "UNCLASSIFIED_NO_BASELINE_EVIDENCE" if treat == "UNCLASSIFIED" else "TREATMENT_BY_ANALOGY",
                    "raw_category", cat, ledger_cat, f"delta {d} cents")
        if treat == "OPEN_POKER_STAKE" and period == "AFTER_BASELINE":
            iss.add("DQ-14", "INFO", "raw_transactions", tid, "POKER_BUYIN_OPEN", "poker_reference", None, poker_ref,
                    "no cash-out for this tournament in the covered raw data; not recognized yet")
        out[tid] = dict(transaction_id=tid, timestamp_utc=ts.isoformat(), raw_category=cat, delta_cents=d,
                        funds_json=json.dumps({k: v.get("total") for k, v in
                                               (_get(it, "aggregate.wallet.delta.byType") or {}).items()},
                                              sort_keys=True),
                        poker_reference=poker_ref, baseline_row_ref=b["transaction_row_id"] if b else None,
                        ledger_category=ledger_cat, treatment=treat, recognized_pnl_cents=recognized,
                        rule_provenance=prov, period=period)
    after = defaultdict(lambda: {"rows": 0, "recognized_pnl_cents": 0, "delta_cents": 0})
    for r in out.values():
        if r["period"] != "AFTER_BASELINE":
            continue
        k = r["ledger_category"] or "UNCLASSIFIED"
        if r["treatment"] == "OPEN_POKER_STAKE":
            k = "Poker (open buy-ins)"
        a = after[k]
        a["rows"] += 1
        a["delta_cents"] += r["delta_cents"]
        a["recognized_pnl_cents"] += r["recognized_pnl_cents"] or 0
    if any(r["treatment"] == "UNCLASSIFIED" for r in out.values() if r["period"] == "AFTER_BASELINE"):
        after["UNCLASSIFIED"]["recognized_pnl_cents"] = None
    gates = {"non_sports_rule_conflicts": (conflicts, 0), "non_sports_baseline_rows_not_reproduced": (mismatches, 0)}
    summary = {"matched_baseline_rows": sum(r["period"] == "BASELINE_MATCHED" for r in out.values()),
               "after_baseline": {k: dict(v) for k, v in sorted(after.items())}}
    return out, gates, summary
