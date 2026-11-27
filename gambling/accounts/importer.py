"""Import Bovada exports (and the frozen P&L baseline) into the SEPARATE accounts database.

Raw layer only (migration ``accounts/migrations/0001_raw_exports.sql``). The exporter output is
stored as received:

* every file of every run, as verbatim bytes plus SHA-256;
* every line of ``_pages.jsonl``;
* every distinct version of every transaction, keyed by (id, content hash), with every sighting
  (run, line, position) recorded;
* coverage windows (``covers=1`` only for complete runs; failed attempts are kept with ``covers=0``).

Nothing is cleansed here. DQ-01..DQ-12 run later against these rows and log their
transformations separately.

Safety:

* **Profile gate.** The import refuses unless the read-only profile is import-ready, and the
  profile is stored with the import.
* **Separate database.** It refuses to write into the model scoring database (``gambling.sqlite``).
* **Idempotent.** Re-importing the same files adds nothing. An already imported run whose files
  have changed is a conflict, because exports are immutable once imported.
* **Baseline.** The P&L baseline is copied table by table, verbatim, as ``pnl_baseline_<table>``,
  with append-only triggers. Only one baseline file is accepted; a different one is a conflict.
* **Atomic.** The whole import is one transaction.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gambling.accounts.exports import _get, discover, profile_exports, to_utc
from gambling.db.migrate import apply_migrations, connect

MIGRATIONS = Path(__file__).parent / "migrations"
TOOL = "gambling.accounts.importer/1"


class ImportRefused(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_accounts_db(path: Path, scoring_db: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(path)
    if scoring_db is not None and path.resolve() == Path(scoring_db).resolve():
        raise ImportRefused("account data must not go into the model scoring database")
    if path.name == "gambling.sqlite":
        raise ImportRefused("refusing to use a file named gambling.sqlite for account data")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path)
    apply_migrations(con, MIGRATIONS)
    return con


def _canon(item) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _import_run(con, rf, rep: dict, import_id: int, counts: dict) -> None:
    files = {role: getattr(rf, role) for role in ("pages", "run", "json", "csv") if getattr(rf, role)}
    hashes = {role: _sha(p.read_bytes()) for role, p in files.items()}
    stored = dict(con.execute("SELECT role, sha256 FROM export_files WHERE stem = ?", (rf.stem,)).fetchall())
    if stored:
        if stored != hashes:
            raise ImportRefused(f"{rf.stem}: files differ from the imported ones {sorted(set(stored.items()) ^ set(hashes.items()))}; "
                                "imported exports are immutable")
        counts["runs_already_imported"] += 1
        return
    con.execute("INSERT INTO export_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rf.stem, rep.get("created_at_from"), rep.get("started_at_utc"), rep.get("finished_at_utc"),
                 rep.get("stopped_because"), rep["status"], rep.get("pages"), rep.get("raw_items"),
                 rep.get("unique_ids"), json.dumps(rep.get("issues", [])), import_id))
    for role, p in files.items():
        data = p.read_bytes()
        con.execute("INSERT INTO export_files VALUES (?, ?, ?, ?, ?, ?)", (rf.stem, role, p.name, hashes[role],
                                                                            len(data), data))
    start, end = to_utc(rep.get("created_at_from")), to_utc(rep.get("finished_at_utc"))
    con.execute("INSERT INTO coverage_windows VALUES (?, ?, ?, ?, ?)",
                (rf.stem, start.isoformat() if start else None, end.isoformat() if end else None,
                 int(rep["status"] == "COMPLETE"), rep["status"]))
    counts["runs_imported"] += 1
    if "pages" not in files:
        return
    for line_no, line in enumerate(files["pages"].read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        page = json.loads(line)
        items = (page.get("data") or {}).get("items") or []
        con.execute("INSERT INTO raw_pages VALUES (?, ?, ?, ?, ?, ?)",
                    (rf.stem, line_no, page.get("page"), len(items), _sha(line.encode("utf-8")), line))
        counts["pages"] += 1
        for pos, it in enumerate(items):
            if not isinstance(it, dict) or it.get("id") in (None, ""):
                raise ImportRefused(f"{rf.stem} line {line_no} item {pos}: no transaction id")
            canon = _canon(it)
            version = _sha(canon.encode("utf-8"))
            ts = to_utc(it.get("timestamp"))
            cur = con.execute("INSERT OR IGNORE INTO raw_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (str(it["id"]), version, canon, None if it.get("timestamp") is None else str(it["timestamp"]),
                               ts.isoformat() if ts else None, _get(it, "aggregate.wallet.category"),
                               _get(it, "aggregate.wallet.currency"),
                               _str(_get(it, "aggregate.wallet.delta.total")),
                               _str(_get(it, "aggregate.wallet.balance.total")),
                               _str(it.get("productGroupId")), rf.stem))
            counts["new_transaction_versions"] += cur.rowcount
            con.execute("INSERT INTO transaction_sightings VALUES (?, ?, ?, ?, ?)",
                        (str(it["id"]), version, rf.stem, line_no, pos))
            counts["sightings"] += 1


def _str(v) -> Optional[str]:
    return None if v is None else str(v)


def _import_baseline(con, baseline: Path, import_id: int, counts: dict) -> None:
    data = Path(baseline).read_bytes()
    sha = _sha(data)
    existing = con.execute("SELECT baseline_sha256 FROM pnl_baseline_imports").fetchall()
    if existing:
        if existing[0][0] != sha:
            raise ImportRefused(f"a different P&L baseline is already imported ({existing[0][0][:12]}…)")
        counts["baseline"] = "already imported"
        return
    src = sqlite3.connect(f"file:{baseline}?mode=ro", uri=True)
    try:
        tables = {}
        for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                                "ORDER BY name"):
            cols = src.execute(f'PRAGMA table_info("{t}")').fetchall()
            name = f"pnl_baseline_{t}"
            con.execute(f'CREATE TABLE "{name}" (' + ", ".join(f'"{c[1]}" {c[2] or ""}'.rstrip() for c in cols) + ")")
            rows = src.execute(f'SELECT * FROM "{t}"').fetchall()
            con.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(cols))})', rows)
            for op in ("UPDATE", "DELETE"):
                con.execute(f'CREATE TRIGGER "{name}_no_{op.lower()}" BEFORE {op} ON "{name}" '
                            "BEGIN SELECT RAISE(ABORT, 'append-only'); END")
            tables[t] = len(rows)
    finally:
        src.close()
    con.execute("INSERT INTO pnl_baseline_imports VALUES (?, ?, ?, ?, ?)",
                (sha, Path(baseline).name, len(data), json.dumps(tables), import_id))
    counts["baseline"] = {"sha256": sha, "tables": tables}


def import_exports(db: Path, folder: Path, baseline: Optional[Path] = None, scoring_db: Optional[Path] = None,
                   since: Optional[str] = None) -> dict:
    report = profile_exports(Path(folder), Path(baseline) if baseline else None, since)
    if not report["import_ready"]:
        raise ImportRefused("the export profile is not import-ready; run `accounts profile` and resolve it first")
    con = open_accounts_db(db, scoring_db)
    counts = {"runs_imported": 0, "runs_already_imported": 0, "pages": 0, "sightings": 0,
              "new_transaction_versions": 0}
    try:
        con.execute("BEGIN IMMEDIATE")
        # The import_runs row is written last, complete; foreign keys are checked at commit.
        con.execute("PRAGMA defer_foreign_keys = ON")
        import_id = con.execute("SELECT COALESCE(MAX(import_id), 0) + 1 FROM import_runs").fetchone()[0]
        reps = {r["stem"]: r for r in report["runs"]}
        for rf in discover(Path(folder)):
            _import_run(con, rf, reps[rf.stem], import_id, counts)
        if baseline:
            _import_baseline(con, Path(baseline), import_id, counts)
        # conservation: every unique transaction of the profile is in the database
        stored_ids = {r[0] for r in con.execute("SELECT DISTINCT transaction_id FROM raw_transactions")}
        if len(stored_ids) < report["counts"]["unique_transactions"]:
            raise ImportRefused(f"stored {len(stored_ids)} transaction ids, profile has "
                                f"{report['counts']['unique_transactions']}")
        counts["transactions_in_database"] = len(stored_ids)
        con.execute("INSERT INTO import_runs VALUES (?, ?, ?, ?, ?, ?)",
                    (import_id, datetime.now(timezone.utc).isoformat(), TOOL, str(folder),
                     json.dumps(report, default=str), json.dumps(counts, default=str)))
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return {"import_id": import_id, **counts, "coverage": report["coverage"]}


__all__ = ["ImportRefused", "import_exports", "open_accounts_db"]
