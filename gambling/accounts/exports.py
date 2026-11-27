"""Pre-import profile of Bovada account exports (read-only).

Reads the folder written by ``bovada_transactions/bovada_transactions.py``. Every run there
produces four files sharing a stem ``bovada_transactions_<from>_to_<to>``:

* ``<stem>_pages.jsonl``: **the original source**, one raw API page per line as it arrived.
* ``<stem>_run.json``: the run log (``created_at_from``, start/finish, per-page counts,
  ``stopped_because``).
* ``<stem>.json`` / ``<stem>.csv``: derived from the pages (first copy of each id wins).

``profile_exports`` reports, before anything is imported:

* **Coverage per run.** The requested window starts at ``created_at_from`` and ends at the finish
  time. A run is complete only if it ``reached the last page``. The API serves at most 31 days back,
  so an older start is clipped by the exporter.
* **Union coverage and missing periods.** Only complete runs count as covered. Every gap between
  covered windows, and everything before the earliest one, is reported as ``NOT_COVERED``. Missing
  periods are never read as zero activity.
* **Counts.** Raw items, unique ids, items per page against the run log, and derived-file consistency
  (the ``.json``/``.csv`` must equal the pages).
* **Duplicates.** The same id on several pages or in several runs: identical copies or differing
  versions (the changed fields are named).
* **Balance chain.** Per wallet category and currency, in time order, each
  ``aggregate.wallet.balance.total`` should equal the previous balance plus
  ``aggregate.wallet.delta.total``. A break means transactions are missing (or the order is
  ambiguous) even inside a covered window.
* **Baseline reconciliation (optional).** Wagers in the P&L baseline (``gambling_pnl_*.sqlite``)
  whose ``bovada_reference`` / ``source_transaction_id`` appear anywhere in the raw items, split by
  whether the wager falls inside covered time.

No account values beyond ids, timestamps, counts and money totals are written to the report, and
nothing is imported. Run it on the machine that holds the exports. The exports stay out of the
repository.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional

STEM_RE = re.compile(r"^(bovada_transactions_\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2})(_pages\.jsonl|_run\.json|\.json|\.csv)$")
COMPLETE = "reached the last page"


@dataclass
class RunFiles:
    stem: str
    pages: Optional[Path] = None
    run: Optional[Path] = None
    json: Optional[Path] = None
    csv: Optional[Path] = None
    issues: list = field(default_factory=list)


def discover(folder: Path) -> list[RunFiles]:
    runs: dict[str, RunFiles] = {}
    for p in sorted(Path(folder).iterdir()):
        m = STEM_RE.match(p.name)
        if not m:
            continue
        rf = runs.setdefault(m.group(1), RunFiles(m.group(1)))
        setattr(rf, {"_pages.jsonl": "pages", "_run.json": "run", ".json": "json", ".csv": "csv"}[m.group(2)], p)
    return list(runs.values())


def to_utc(v) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _get(d: dict, path: str):
    for part in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def _dec(v) -> Optional[Decimal]:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _canon(item) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)


def _diff_keys(a, b, prefix="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += _diff_keys(a.get(k), b.get(k), f"{prefix}{k}.")
        return out
    return [] if a == b else [prefix.rstrip(".")]


def _scalars(obj, out: set) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _scalars(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _scalars(v, out)
    elif obj is not None:
        out.add(str(obj))


def load_run(rf: RunFiles) -> dict:
    """Parse one run from its original pages; check the run log and derived files against them."""
    rep: dict = {"stem": rf.stem, "files": {k: getattr(rf, k).name if getattr(rf, k) else None
                                            for k in ("pages", "run", "json", "csv")}, "issues": []}
    log = json.loads(rf.run.read_text(encoding="utf-8")) if rf.run else {}
    if not rf.run:
        rep["issues"].append("RUN_LOG_MISSING")
    if not rf.pages:
        stopped = log.get("stopped_because")
        if rf.run and not log.get("pages") and stopped and stopped != COMPLETE:
            # The exporter failed before receiving any page (session expired, browser closed, HTTP error).
            # Nothing was fetched, so there is no missing source; the attempt covers nothing.
            rep["issues"].append(f"FAILED_ATTEMPT_NO_DATA: {stopped}")
            rep.update({"created_at_from": log.get("created_at_from"), "started_at_utc": log.get("started_at_utc"),
                        "finished_at_utc": log.get("finished_at_utc"), "stopped_because": stopped,
                        "complete": False, "pages": 0, "raw_items": 0, "unique_ids": 0, "items_without_id": 0,
                        "status": "FAILED_NO_DATA"})
            return rep | {"items": []}
        rep["issues"].append("PAGES_MISSING: no original source; derived files are not used as a substitute")
        rep["status"] = "NOT_USABLE"
        return rep | {"items": []}
    pages = []
    for n, line in enumerate(rf.pages.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            rep["issues"].append(f"PAGES_LINE_{n}_NOT_JSON (truncated write?)")
            continue
        pages.append(rec)
    numbers = [p.get("page") for p in pages]
    if numbers != list(range(1, len(pages) + 1)):
        rep["issues"].append(f"PAGE_SEQUENCE_BROKEN: {numbers[:10]}")
    items = []
    for p in pages:
        for it in (p.get("data") or {}).get("items") or []:
            if isinstance(it, dict):
                items.append((p.get("page"), it))
    logged = [x.get("items") for x in log.get("pages", [])]
    actual = [len((p.get("data") or {}).get("items") or []) for p in pages]
    if log and logged != actual:
        rep["issues"].append(f"RUN_LOG_PAGE_COUNTS_DIFFER: log {logged[:10]} vs pages {actual[:10]}")
    last_next = log.get("pages", [{}])[-1].get("has_next") if log.get("pages") else None
    stopped = log.get("stopped_because")
    complete = stopped == COMPLETE and last_next in (False, None)
    if stopped and stopped != COMPLETE:
        rep["issues"].append(f"INCOMPLETE_RUN: {stopped}")

    ids = Counter(it.get("id") for _, it in items)
    no_id = ids.pop(None, 0)
    within_dupes = {i: c for i, c in ids.items() if c > 1}
    first: dict = {}
    for _, it in items:
        first.setdefault(it.get("id"), it)
    stamps = [to_utc(it.get("timestamp")) for it in first.values() if it.get("timestamp") is not None]
    # derived files must equal the pages (exporter: first copy of each id wins)
    if rf.json:
        d = json.loads(rf.json.read_text(encoding="utf-8"))
        tx = d.get("transactions") or []
        if {t.get("id") for t in tx} != set(first) - {None} or d.get("transaction_count") != len(tx):
            rep["issues"].append("DERIVED_JSON_DIFFERS_FROM_PAGES")
        elif any(_canon(t) != _canon(first[t.get("id")]) for t in tx):
            rep["issues"].append("DERIVED_JSON_CONTENT_DIFFERS_FROM_PAGES")
    if rf.csv:
        with open(rf.csv, newline="", encoding="utf-8-sig") as f:
            csv_ids = [r.get("id") for r in csv.DictReader(f)]
        if len(csv_ids) != len(first) or set(csv_ids) != {str(i) for i in first if i is not None}:
            rep["issues"].append("DERIVED_CSV_DIFFERS_FROM_PAGES")
    rep.update({
        "created_at_from": log.get("created_at_from"),
        "started_at_utc": log.get("started_at_utc"),
        "finished_at_utc": log.get("finished_at_utc"),
        "stopped_because": stopped,
        "complete": complete,
        "pages": len(pages),
        "raw_items": len(items),
        "unique_ids": len(first) - (1 if None in first else 0),
        "items_without_id": no_id,
        "duplicate_ids_within_run": len(within_dupes),
        "duplicate_id_conflicts_within_run": sum(
            1 for i in within_dupes if len({_canon(it) for _, it in items if it.get("id") == i}) > 1),
        "oldest_item_utc": min(stamps).isoformat() if stamps else None,
        "newest_item_utc": max(stamps).isoformat() if stamps else None,
        "status": "COMPLETE" if complete else "PARTIAL",
    })
    rep["items"] = [it for i, it in first.items() if i is not None]
    return rep


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def balance_chain(items: Iterable[dict], by_category: bool = True) -> dict:
    """Check balance[i] == balance[i-1] + delta[i] in time order, per currency (one shared balance) or per
    wallet category and currency. Which grouping Bovada uses is not documented; both are reported."""
    groups = defaultdict(list)
    for it in items:
        bal, delta = _dec(_get(it, "aggregate.wallet.balance.total")), _dec(_get(it, "aggregate.wallet.delta.total"))
        ts = to_utc(it.get("timestamp"))
        if bal is None or delta is None or ts is None:
            continue
        key = (_get(it, "aggregate.wallet.category") or "?" if by_category else "ALL",
               _get(it, "aggregate.wallet.currency") or "?")
        groups[key].append((ts, str(it.get("id")), bal, delta))
    out = {}
    for key, rows in groups.items():
        rows.sort()
        breaks = []
        for prev, cur in zip(rows, rows[1:]):
            if prev[2] + cur[3] != cur[2]:
                # same-timestamp ordering can be ambiguous; report it separately
                breaks.append({"after_id": prev[1], "id": cur[1], "at_utc": cur[0].isoformat(),
                               "gap_amount": str(cur[2] - cur[3] - prev[2]),
                               "same_timestamp": prev[0] == cur[0]})
        out[f"{key[0]}|{key[1]}"] = {"transactions": len(rows), "first_utc": rows[0][0].isoformat(),
                                     "last_utc": rows[-1][0].isoformat(), "breaks": len(breaks),
                                     "breaks_not_same_timestamp": sum(not b["same_timestamp"] for b in breaks),
                                     "break_details": breaks[:50]}
    return out


def baseline_reconciliation(baseline: Path, all_scalars: set, covered: list) -> dict:
    con = sqlite3.connect(f"file:{baseline}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT wager_id, bovada_reference, source_transaction_id, placed_at_utc, settled_at_utc, "
                           "net_pnl_cents FROM sportsbook_wagers").fetchall()
    finally:
        con.close()
    res = Counter()
    unmatched_in_window = []
    for wid, ref, src, placed, settled, pnl in rows:
        keys = [str(k) for k in (ref, src) if k not in (None, "")]
        when = to_utc(settled or placed) if (settled or placed) else None
        inside = when is not None and any(a <= when <= b for a, b in covered)
        hit = any(k in all_scalars for k in keys)
        res[("matched" if hit else "unmatched") + ("_in_covered_time" if inside else "_outside_covered_time")] += 1
        if not keys:
            res["no_reference_or_transaction_id"] += 1
        if inside and not hit:
            unmatched_in_window.append({"wager_id": wid, "bovada_reference": ref, "placed_at_utc": placed,
                                        "settled_at_utc": settled})
    return {"baseline_wagers": len(rows), **dict(res), "unmatched_in_covered_time_examples": unmatched_in_window[:25]}


def profile_exports(folder: Path, baseline: Optional[Path] = None, since: Optional[str] = None) -> dict:
    runs = [load_run(rf) for rf in discover(folder)]
    covered = _merge([(to_utc(r["created_at_from"]), to_utc(r["finished_at_utc"])) for r in runs
                      if r.get("status") == "COMPLETE" and r.get("created_at_from") and r.get("finished_at_utc")])
    start = to_utc(since) if since else (covered[0][0] if covered else None)
    end = covered[-1][1] if covered else None
    gaps = []
    if covered and start and start < covered[0][0]:
        gaps.append((start, covered[0][0]))
    gaps += [(a[1], b[0]) for a, b in zip(covered, covered[1:])]
    # union of items: across-run duplicates
    by_id: dict = defaultdict(list)
    for r in runs:
        for it in r["items"]:
            by_id[it["id"]].append((r["stem"], it))
    cross = {i: v for i, v in by_id.items() if len({s for s, _ in v}) > 1}
    conflicts = {}
    for i, v in cross.items():
        versions = {_canon(it) for _, it in v}
        if len(versions) > 1:
            conflicts[i] = sorted({k for (_, a), (_, b) in zip(v, v[1:]) for k in _diff_keys(a, b)})
    latest = {i: max(v, key=lambda x: x[0])[1] for i, v in by_id.items()}  # stems sort by window
    all_scalars: set = set()
    for it in latest.values():
        _scalars(it, all_scalars)
    categories = Counter(_get(it, "aggregate.wallet.category") for it in latest.values())
    deltas = defaultdict(Decimal)
    for it in latest.values():
        d = _dec(_get(it, "aggregate.wallet.delta.total"))
        if d is not None:
            deltas[f"{_get(it, 'aggregate.wallet.category')}|{_get(it, 'aggregate.wallet.currency')}"] += d
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "folder": str(folder),
        "runs": [{k: v for k, v in r.items() if k != "items"} for r in runs],
        "coverage": {
            "complete_runs": sum(r.get("status") == "COMPLETE" for r in runs),
            "partial_or_unusable_runs": [r["stem"] for r in runs if r.get("status") not in ("COMPLETE", "FAILED_NO_DATA")],
            "failed_attempts_no_data": [r["stem"] for r in runs if r.get("status") == "FAILED_NO_DATA"],
            "covered_utc": [[a.isoformat(), b.isoformat()] for a, b in covered],
            "not_covered_utc": [[a.isoformat(), b.isoformat(), str(b - a)] for a, b in gaps if b > a],
            "assessed_from_utc": start.isoformat() if start else None,
            "assessed_to_utc": end.isoformat() if end else None,
            "rule": "Only complete runs count as covered. NOT_COVERED periods have unknown activity, not zero.",
        },
        "counts": {
            "raw_items": sum(r.get("raw_items", 0) for r in runs),
            "unique_transactions": len(latest),
            "items_without_id": sum(r.get("items_without_id", 0) for r in runs),
            "ids_in_several_runs": len(cross),
            "ids_with_differing_versions_across_runs": len(conflicts),
            "differing_fields": dict(Counter(k for ks in conflicts.values() for k in ks).most_common(20)),
            "wallet_categories": {str(k): v for k, v in categories.most_common()},
            "delta_totals_by_category_currency": {k: str(v) for k, v in deltas.items()},
        },
        "balance_chain": {"per_currency": balance_chain(latest.values(), by_category=False),
                          "per_category_and_currency": balance_chain(latest.values(), by_category=True)},
        "field_inventory": dict(Counter(k for it in list(latest.values())[:2000] for k in _flat_keys(it)).most_common(60)),
    }
    if baseline:
        report["baseline_reconciliation"] = baseline_reconciliation(Path(baseline), all_scalars, covered)
    unexplained = {g: sum(c["breaks_not_same_timestamp"] for c in chains.values())
                   for g, chains in report["balance_chain"].items()}
    report["balance_chain"]["grouping_that_holds"] = [g for g, b in unexplained.items() if b == 0] or None
    report["import_ready"] = (not report["coverage"]["partial_or_unusable_runs"]
                              and not report["counts"]["items_without_id"]
                              and report["balance_chain"]["grouping_that_holds"] is not None)
    return report


def _flat_keys(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flat_keys(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}"


def markdown(report: dict) -> str:
    c, n = report["coverage"], report["counts"]
    lines = ["# Bovada export profile (pre-import)", "", f"Generated {report['generated_utc']} from `{report['folder']}`.", "",
             "## Runs", "", "| Run | Status | Window from | Finished | Pages | Raw items | Unique | Dupes in run | Oldest item | Newest item | Issues |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in report["runs"]:
        lines.append(f"| {r['stem']} | {r.get('status')} | {r.get('created_at_from')} | {r.get('finished_at_utc')} | "
                     f"{r.get('pages')} | {r.get('raw_items')} | {r.get('unique_ids')} | {r.get('duplicate_ids_within_run')} | "
                     f"{r.get('oldest_item_utc')} | {r.get('newest_item_utc')} | {'; '.join(r['issues']) or '—'} |")
    lines += ["", "## Coverage (complete runs only)", ""]
    lines += [f"- covered: {a} → {b}" for a, b in c["covered_utc"]] or ["- none"]
    lines += [f"- **NOT COVERED** (activity unknown, not zero): {a} → {b} ({d})" for a, b, d in c["not_covered_utc"]] or ["- no gaps between covered windows"]
    lines += [f"- failed attempt, no data received (covers nothing; does not block import): {s}"
              for s in c.get("failed_attempts_no_data", [])]
    lines += ["", "## Counts", ""] + [f"- {k}: {v}" for k, v in n.items()]
    lines += ["", "## Balance chain", ""]
    for grouping in ("per_currency", "per_category_and_currency"):
        lines.append(f"- {grouping}:")
        for k, v in report["balance_chain"][grouping].items():
            lines.append(f"  - {k}: {v['transactions']} tx, {v['first_utc']} → {v['last_utc']}, breaks {v['breaks']} "
                         f"({v['breaks_not_same_timestamp']} not explained by equal timestamps)")
    lines.append(f"- grouping with no unexplained breaks: {report['balance_chain']['grouping_that_holds']}")
    if "baseline_reconciliation" in report:
        lines += ["", "## P&L baseline reconciliation", ""] + [
            f"- {k}: {v}" for k, v in report["baseline_reconciliation"].items() if not k.endswith("examples")]
    lines += ["", f"**Import ready:** {report['import_ready']}"]
    return "\n".join(lines) + "\n"


__all__ = ["balance_chain", "discover", "load_run", "markdown", "profile_exports"]
