"""Versioned, append-only model-input store inside the rolling history SQLite database.

The tables are created by ``gambling/db/migrations/0006_model_data.sql`` and applied by
the same migrator as the rest of ``data/gambling.sqlite``. They build on the existing
data model: runs reference ``model_releases`` (no second registry), can point at the
``capture_batches`` / ``quote_cohorts`` they scored and the ``model_scores`` they
reproduce, and dataset rows can carry the existing ``game_key``.

Every source file is kept byte-for-byte (chunked BLOBs keyed by SHA-256), every parsed
dataset is an immutable version with a column catalog, lossless rows and a content hash,
and every reproducible run pins the exact files it used.

This store never holds sportsbook wagers, tickets, balances or account data:
``guard_columns`` rejects account/wager exports outright and requires an explicit
sensitivity classification for files that merely carry user-observation flags.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from contextlib import contextmanager

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
CHUNK = 1 << 20  # 1 MiB
SENSITIVITIES = ("PUBLIC_MARKET", "MODEL_INTERNAL", "CONTAINS_USER_OBSERVATION_FLAGS")
IMPORT_TOOL = "gambling.modeldata.store/1"

# Columns that mark a file as an account / wager export: never stored here.
ACCOUNT_EXPORT = re.compile(r"(^|[._])(wallet|balance|ticket|wager_id|bovada_reference|transaction_id|"
                            r"deposit|withdraw|payout|bonus)([._]|$)", re.I)
# Columns that indicate user-observation flags (allowed only with explicit classification).
USER_FLAG = re.compile(r"((^|[_ .])(bet|bets|stake|wager)([_ .$]|$)|^my[_ ]|net \$|bankroll)", re.I)


class ModelDataError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guard_columns(columns: Sequence[str], sensitivity: str,
                  reviewed: Optional[dict[str, str]] = None) -> list[Optional[str]]:
    """Return per-column flags; raise if the file is an account/wager export or unclassified.

    ``reviewed`` maps column names to a written justification that the column is a
    model-generated field (e.g. a model's own sizing flag), not user/account data.
    Such columns are recorded as REVIEWED_MODEL_FIELD. Account-export columns are
    never accepted, reviewed or not.
    """
    reviewed = reviewed or {}
    account = [c for c in columns if ACCOUNT_EXPORT.search(c)]
    if account:
        raise ModelDataError(f"columns {account[:5]} indicate a sportsbook account/wager export; such data belongs "
                             "in the separate accounts database, not the model-input store")
    flags: list[Optional[str]] = []
    for c in columns:
        if not USER_FLAG.search(c):
            flags.append(None)
        elif c in reviewed and reviewed[c].strip():
            flags.append("REVIEWED_MODEL_FIELD")
        else:
            flags.append("USER_OBSERVATION_FLAG")
    unreviewed = [c for c, f in zip(columns, flags) if f == "USER_OBSERVATION_FLAG"]
    if unreviewed and sensitivity != "CONTAINS_USER_OBSERVATION_FLAGS":
        raise ModelDataError(f"columns {unreviewed[:5]} look like user observation flags; review them as model "
                             "fields or register the source with sensitivity=CONTAINS_USER_OBSERVATION_FLAGS")
    return flags


def parse_table(data: bytes, parser: str) -> tuple[list[str], list[str], list[list[Optional[str]]]]:
    """Parse source bytes into (columns, source dtypes, rows of text values). Lossless for CSV text."""
    if parser in ("csv", "csv.gz"):
        raw = gzip.decompress(data) if parser == "csv.gz" else data
        reader = csv.reader(io.StringIO(raw.decode("utf-8"), newline=""))
        rows = list(reader)
        if not rows:
            return [], [], []
        return rows[0], ["text"] * len(rows[0]), [list(r) for r in rows[1:]]
    if parser == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ModelDataError("parquet import needs pyarrow") from exc
        table = pq.read_table(io.BytesIO(data))
        cols = table.column_names
        dtypes = [str(f.type) for f in table.schema]
        cols_py = [table.column(c).to_pylist() for c in cols]
        rows = [[None if v is None else str(v) for v in values] for values in zip(*cols_py)]
        return cols, dtypes, rows
    if parser == "json":
        obj = json.loads(data.decode("utf-8"))
        if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
            cols: list[str] = []
            for x in obj:
                cols += [k for k in x if k not in cols]
            return cols, ["json"] * len(cols), [[None if x.get(c) is None else json.dumps(x.get(c)) for c in cols]
                                                for x in obj]
        return [], [], []  # non-tabular JSON: stored as blob only
    if parser == "blob":
        return [], [], []
    raise ModelDataError(f"unknown parser {parser!r}")


def parser_for(name: str) -> str:
    n = name.lower()
    if n.endswith(".csv.gz"):
        return "csv.gz"
    if n.endswith(".csv"):
        return "csv"
    if n.endswith(".parquet"):
        return "parquet"
    if n.endswith(".json"):
        return "json"
    return "blob"


def media_type_for(name: str) -> str:
    return {"csv": "text/csv", "csv.gz": "application/gzip", "parquet": "application/vnd.apache.parquet",
            "json": "application/json"}.get(parser_for(name), "application/octet-stream")


@dataclass
class Store:
    """Model-input store over a connection from :func:`gambling.db.migrate.connect`."""
    con: sqlite3.Connection

    def execute(self, sql: str, params: Sequence = ()):
        return self.con.execute(sql, tuple(params))

    def fetchall(self, sql: str, params: Sequence = ()) -> list[tuple]:
        return [tuple(r) for r in self.con.execute(sql, tuple(params)).fetchall()]

    def fetchone(self, sql: str, params: Sequence = ()):
        r = self.con.execute(sql, tuple(params)).fetchone()
        return None if r is None else tuple(r)

    @contextmanager
    def tx(self):
        """One atomic write. Nested use joins the outer transaction."""
        if self.con.in_transaction:
            yield
            return
        self.con.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.con.execute("COMMIT")
        except BaseException:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise

    def migrate(self) -> list[str]:
        from gambling.db.migrate import apply_migrations
        return apply_migrations(self.con)

    def snapshot(self, dest: Path) -> dict:
        """Consistent point-in-time copy (SQLite online backup) plus its SHA-256, for sharing or offline backup."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise ModelDataError(f"{dest} exists; snapshots are never overwritten")
        target = sqlite3.connect(str(dest))
        try:
            self.con.backup(target)
        finally:
            target.close()
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        Path(str(dest) + ".sha256").write_text(f"{digest}  {dest.name}\n", encoding="utf-8")
        return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": digest,
                "migrations": [r[0] for r in self.fetchall("SELECT version FROM schema_migrations ORDER BY version")]}

    # ------------------------------------------------------------------ source evidence
    def register_source(self, data: bytes, original_name: str, sensitivity: str, provenance: str,
                        actor: str, parent_sha256: Optional[str] = None,
                        parent_member_path: Optional[str] = None) -> str:
        if sensitivity not in SENSITIVITIES:
            raise ModelDataError(f"sensitivity must be one of {SENSITIVITIES}")
        digest = sha256_bytes(data)
        if self.fetchone("SELECT sha256 FROM md_source_files WHERE sha256 = ?", (digest,)):
            return digest  # identical bytes already preserved; content-addressed, nothing to change
        chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
        with self.tx():
            self.execute("INSERT INTO md_source_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (digest, len(data), original_name, media_type_for(original_name), sensitivity, provenance,
                          parent_sha256, parent_member_path, len(chunks), utcnow(), actor))
            for i, chunk in enumerate(chunks):
                self.execute("INSERT INTO md_source_file_chunks VALUES (?, ?, ?)", (digest, i, chunk))
        return digest

    def read_source(self, digest: str) -> bytes:
        rows = self.fetchall("SELECT data FROM md_source_file_chunks WHERE sha256 = ? ORDER BY chunk_no", (digest,))
        meta = self.fetchone("SELECT bytes, chunk_count FROM md_source_files WHERE sha256 = ?", (digest,))
        if meta is None:
            raise ModelDataError(f"unknown source {digest}")
        data = b"".join(bytes(r[0]) for r in rows)
        if len(rows) != meta[1] or len(data) != meta[0] or sha256_bytes(data) != digest:
            raise ModelDataError(f"source {digest} failed integrity verification")
        return data

    def materialize_source(self, digest: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.read_source(digest))
        return dest

    # ------------------------------------------------------------------ datasets
    def ensure_dataset(self, dataset_id: str, domain: str, sport: Optional[str], description: str) -> None:
        if not self.fetchone("SELECT dataset_id FROM md_datasets WHERE dataset_id = ?", (dataset_id,)):
            self.execute("INSERT INTO md_datasets VALUES (?, ?, ?, ?, ?)", (dataset_id, domain, sport, description,
                                                                         utcnow()))

    def import_version(self, dataset_id: str, version_label: str, source_sha256: str, parser: str,
                       actor: str, available_from_utc: Optional[str] = None, time_column: Optional[str] = None,
                       parent_version_id: Optional[int] = None, notes: Optional[str] = None,
                       reviewed_columns: Optional[dict[str, str]] = None,
                       game_key_column: Optional[str] = None, key_columns: Optional[Sequence[str]] = None,
                       version_kind: str = "FULL", produced_by_run: Optional[str] = None) -> int:
        existing = self.fetchone("SELECT version_id, source_sha256 FROM md_dataset_versions WHERE dataset_id = ? AND "
                                 "version_label = ?", (dataset_id, version_label))
        if existing:
            if existing[1] != source_sha256:
                raise ModelDataError(f"{dataset_id}@{version_label} already exists with different source bytes")
            return int(existing[0])
        sensitivity = self.fetchone("SELECT sensitivity FROM md_source_files WHERE sha256 = ?", (source_sha256,))[0]
        columns, dtypes, rows = parse_table(self.read_source(source_sha256), parser)
        flags = guard_columns(columns, sensitivity, reviewed_columns)
        if time_column and time_column not in columns:
            raise ModelDataError(f"time_column {time_column!r} not in columns")
        t_idx = columns.index(time_column) if time_column else None
        if game_key_column and game_key_column not in columns:
            raise ModelDataError(f"game_key_column {game_key_column!r} not in columns")
        g_idx = columns.index(game_key_column) if game_key_column else None
        missing_keys = [k for k in (key_columns or []) if k not in columns]
        if missing_keys:
            raise ModelDataError(f"key_columns {missing_keys} not in columns")
        if version_kind == "APPEND" and parent_version_id is None:
            raise ModelDataError("an APPEND version needs its parent version")
        row_hashes = []
        payload = []
        for n, values in enumerate(rows):
            js = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
            h = sha256_bytes(js.encode("utf-8"))
            row_hashes.append(h)
            payload.append((n, _at(values, t_idx), _at(values, g_idx) or None, h, js))
        content = sha256_bytes("".join(row_hashes).encode("ascii"))
        with self.tx():
            cur = self.execute("INSERT INTO md_dataset_versions (dataset_id, version_label, source_sha256, parser, "
                               "available_from_utc, time_column, game_key_column, row_count, column_count, content_sha256, "
                               "parent_version_id, version_kind, key_columns, produced_by_run, import_tool, created_utc, "
                               "notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (dataset_id, version_label, source_sha256, parser, available_from_utc, time_column, game_key_column,
                                len(rows), len(columns), content, parent_version_id, version_kind,
                                json.dumps(list(key_columns)) if key_columns else None, produced_by_run,
                                IMPORT_TOOL, utcnow(), notes))
            version_id = int(cur.lastrowid)
            if columns:
                self.con.executemany(("INSERT INTO md_dataset_columns VALUES (?, ?, ?, ?, ?)"),
                                              [(version_id, i, c, d, f) for i, (c, d, f) in
                                               enumerate(zip(columns, dtypes, flags))])
            batch = 2000
            for i in range(0, len(payload), batch):
                self.con.executemany(("INSERT INTO md_dataset_rows VALUES (?, ?, ?, ?, ?, ?)"),
                                              [(version_id, *p) for p in payload[i:i + batch]])
            self.execute("INSERT INTO md_dataset_version_events (version_id, status, reason, event_utc, actor) "
                         "VALUES (?, 'STAGED', ?, ?, ?)", (version_id, "imported", utcnow(), actor))
        return version_id

    # ------------------------------------------------------------------ growing masters (append chains)
    def chain(self, dataset_id: str) -> list[int]:
        """Versions of the current master, base FULL version first, then APPEND versions in order.

        The base is the latest non-retracted FULL version; an APPEND whose ancestry is retracted
        ends the chain there.
        """
        versions = self.fetchall("SELECT version_id, parent_version_id, version_kind FROM md_dataset_versions "
                                 "WHERE dataset_id = ? ORDER BY version_id", (dataset_id,))
        live = [v for v in versions if self.status(v[0]) != "RETRACTED"]
        bases = [v[0] for v in live if v[2] == "FULL"]
        if not bases:
            return []
        out = [bases[-1]]
        children = {v[1]: v[0] for v in live if v[2] == "APPEND"}
        while out[-1] in children:
            out.append(children[out[-1]])
        return out

    def _version_meta(self, version_id: int) -> dict:
        r = self.fetchone("SELECT v.dataset_id, v.parser, v.time_column, v.game_key_column, v.key_columns, "
                          "v.available_from_utc, s.sensitivity, v.version_label FROM md_dataset_versions v "
                          "JOIN md_source_files s ON s.sha256 = v.source_sha256 WHERE v.version_id = ?", (version_id,))
        keys = ["dataset_id", "parser", "time_column", "game_key_column", "key_columns", "available_from_utc",
                "sensitivity", "version_label"]
        meta = dict(zip(keys, r))
        meta["key_columns"] = json.loads(meta["key_columns"]) if meta["key_columns"] else None
        meta["reviewed"] = {n: "reviewed in base version" for (n,) in self.fetchall(
            "SELECT name FROM md_dataset_columns WHERE version_id = ? AND flagged = 'REVIEWED_MODEL_FIELD'",
            (version_id,))}
        return meta

    def master_rows(self, dataset_id: str, as_of_utc: Optional[str] = None,
                    latest_by_key: bool = True) -> list[dict]:
        """The cumulative master: every record of the chain, later records superseding earlier ones by key.

        ``as_of_utc`` limits the chain to versions created at or before the cutoff, so a historical run
        sees the master as it stood then.
        """
        chain = self.chain(dataset_id)
        if as_of_utc:
            cut = _ts(as_of_utc)
            created = dict(self.fetchall("SELECT version_id, created_utc FROM md_dataset_versions WHERE dataset_id = ?",
                                         (dataset_id,)))
            chain = [v for v in chain if _ts(created[v]) <= cut]
        if not chain:
            return []
        keys = self._version_meta(chain[0])["key_columns"] if latest_by_key else None
        merged: dict = {}
        for n, vid in enumerate(chain):
            for i, row in enumerate(self.rows(vid)):
                k = tuple(row[c] for c in keys) if keys else (n, i)
                merged.pop(k, None)  # a superseding record moves to the end, in the order it arrived
                merged[k] = row
        return list(merged.values())

    def append_records(self, dataset_id: str, records: Sequence[dict], actor: str, provenance: str,
                       run_id: Optional[str] = None, available_from_utc: Optional[str] = None,
                       label: Optional[str] = None, notes: Optional[str] = None) -> Optional[int]:
        """Append new or changed records to a growing master as one APPEND version.

        Records must carry exactly the master's columns (a schema change needs a new FULL version).
        Records identical to one already in the chain are skipped; if nothing is new, nothing is
        written and None is returned. The delta is stored as its own CSV source, so each append is
        evidence in its own right and the 50 MB base is never copied again.
        """
        chain = self.chain(dataset_id)
        if not chain:
            raise ModelDataError(f"{dataset_id} has no FULL base version to append to")
        if run_id and not self.fetchone("SELECT run_id FROM md_model_runs WHERE run_id = ?", (run_id,)):
            raise ModelDataError(f"run {run_id!r} is not registered; register_run before appending its records")
        head, base = chain[-1], self._version_meta(chain[0])
        columns = self.columns(chain[0])
        for n, rec in enumerate(records):
            extra, missing = set(rec) - set(columns), set(columns) - set(rec)
            if extra or missing:
                raise ModelDataError(f"record {n} does not match the {dataset_id} columns "
                                     f"(extra {sorted(extra)}, missing {sorted(missing)}); "
                                     "a schema change needs a new FULL version")
        seen = {h for vid in chain for (h,) in
                self.fetchall("SELECT row_sha256 FROM md_dataset_rows WHERE version_id = ?", (vid,))}
        new, batch_hashes = [], set()
        for rec in records:
            values = ["" if rec[c] is None else str(rec[c]) for c in columns]
            h = sha256_bytes(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if h not in seen and h not in batch_hashes:
                batch_hashes.add(h)
                new.append(values)
        if not new:
            return None
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(columns)
        w.writerows(new)
        data = buf.getvalue().encode("utf-8")
        label = label or f"append-{utcnow()}-{sha256_bytes(data)[:12]}"
        with self.tx():
            sha = self.register_source(data, f"{dataset_id.replace('/', '_')}_{label}.csv", base["sensitivity"],
                                       provenance, actor)
            vid = self.import_version(dataset_id, label, sha, "csv", actor,
                                      available_from_utc=available_from_utc, time_column=base["time_column"],
                                      parent_version_id=head, notes=notes, reviewed_columns=base["reviewed"],
                                      game_key_column=base["game_key_column"], key_columns=base["key_columns"],
                                      version_kind="APPEND", produced_by_run=run_id)
            if self.status(head) == "PUBLISHED":
                self.set_status(vid, "PUBLISHED", "append to published master", actor)
        return vid

    def append_file(self, dataset_id: str, data: bytes, original_name: str, actor: str, provenance: str,
                    run_id: Optional[str] = None, available_from_utc: Optional[str] = None,
                    label: Optional[str] = None) -> Optional[int]:
        """Append the records of a full re-export that are not already in the master.

        The re-export's SHA-256 is recorded in the delta's provenance; only the delta is stored.
        """
        columns, _, rows = parse_table(data, parser_for(original_name))
        master_cols = self.columns(self.chain(dataset_id)[0]) if self.chain(dataset_id) else None
        if master_cols is not None and columns != master_cols:
            raise ModelDataError(f"{original_name} columns differ from the {dataset_id} master; "
                                 "a schema change needs a new FULL version")
        records = [dict(zip(columns, ["" if v is None else v for v in r])) for r in rows]
        return self.append_records(dataset_id, records, actor,
                                   f"{provenance}; delta of {original_name} sha256={sha256_bytes(data)}",
                                   run_id=run_id, available_from_utc=available_from_utc, label=label)

    def materialize_master(self, dataset_id: str, dest: Path, as_of_utc: Optional[str] = None) -> Path:
        """Write the cumulative master as CSV (values exact; formatting is csv-module, not the original file)."""
        chain = self.chain(dataset_id)
        if not chain:
            raise ModelDataError(f"{dataset_id} has no versions")
        columns = self.columns(chain[0])
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(columns)
            for row in self.master_rows(dataset_id, as_of_utc):
                w.writerow(["" if row[c] is None else row[c] for c in columns])
        return dest

    def set_status(self, version_id: int, status: str, reason: str, actor: str) -> None:
        self.execute("INSERT INTO md_dataset_version_events (version_id, status, reason, event_utc, actor) "
                     "VALUES (?, ?, ?, ?, ?)", (version_id, status, reason, utcnow(), actor))

    def status(self, version_id: int) -> Optional[str]:
        r = self.fetchone("SELECT status FROM md_dataset_version_status WHERE version_id = ?", (version_id,))
        return r[0] if r else None

    def columns(self, version_id: int) -> list[str]:
        return [r[0] for r in self.fetchall("SELECT name FROM md_dataset_columns WHERE version_id = ? ORDER BY ordinal",
                                            (version_id,))]

    def rows(self, version_id: int, as_of_utc: Optional[str] = None,
             include_untimed: bool = False) -> list[dict]:
        """Rows in source order. With ``as_of_utc`` only rows whose time column is <= the cutoff
        (rows without a time value are excluded unless ``include_untimed``)."""
        cols = self.columns(version_id)
        out = []
        for row_time, js in self.fetchall("SELECT row_time_utc, row_json FROM md_dataset_rows WHERE version_id = ? "
                                          "ORDER BY row_no", (version_id,)):
            if as_of_utc is not None:
                if row_time in (None, ""):
                    if not include_untimed:
                        continue
                elif _ts(row_time) > _ts(as_of_utc):
                    continue
            values = json.loads(js)
            out.append(dict(zip(cols, values)))
        return out

    def version_as_of(self, dataset_id: str, cutoff_utc: str) -> Optional[int]:
        """Latest PUBLISHED version whose content was knowable at the cutoff."""
        best = None
        for version_id, available, status in self.fetchall(
                "SELECT version_id, available_from_utc, status FROM md_dataset_version_status WHERE dataset_id = ?",
                (dataset_id,)):
            if status != "PUBLISHED" or available is None or _ts(available) > _ts(cutoff_utc):
                continue
            if best is None or (_ts(available), version_id) > best[0]:
                best = ((_ts(available), version_id), version_id)
        return best[1] if best else None

    def verify_version(self, version_id: int) -> dict:
        """Re-parse the preserved source bytes and compare every row hash with the stored rows."""
        source, parser, content = self.fetchone("SELECT source_sha256, parser, content_sha256 FROM md_dataset_versions "
                                                "WHERE version_id = ?", (version_id,))
        columns, _, rows = parse_table(self.read_source(source), parser)
        hashes = [sha256_bytes(json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                  for v in rows]
        stored = [r[0] for r in self.fetchall("SELECT row_sha256 FROM md_dataset_rows WHERE version_id = ? ORDER BY "
                                              "row_no", (version_id,))]
        ok = hashes == stored and columns == self.columns(version_id) and \
            sha256_bytes("".join(hashes).encode("ascii")) == content
        return {"version_id": version_id, "rows": len(stored), "lossless": ok}

    # ------------------------------------------------------------------ runs
    def register_run(self, run_id: str, kind: str, release_ids: Sequence[str], environment: dict, scorer: Any,
                     input_cutoff_utc: Optional[str] = None, notes: Optional[str] = None,
                     sport: Optional[str] = None, batch_id: Optional[str] = None,
                     quote_cohort_id: Optional[str] = None) -> None:
        """Register a run against releases already in ``model_releases``; never creates a release."""
        if self.fetchone("SELECT run_id FROM md_model_runs WHERE run_id = ?", (run_id,)):
            return
        known = {r[0] for r in self.fetchall("SELECT release_id FROM model_releases")}
        missing = [r for r in release_ids if r not in known]
        if missing:
            raise ModelDataError(f"releases {missing} are not registered in model_releases; register them through "
                                 "a reviewed registry migration first")
        with self.tx():
            self.execute("INSERT INTO md_model_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (run_id, kind, sport, batch_id, quote_cohort_id, input_cutoff_utc, json.dumps(environment),
                          json.dumps(scorer), utcnow(), notes))
            self.con.executemany("INSERT INTO md_run_releases VALUES (?, ?)",
                                 [(run_id, r) for r in dict.fromkeys(release_ids)])

    def run_releases(self, run_id: str) -> list[str]:
        return [r[0] for r in self.fetchall("SELECT release_id FROM md_run_releases WHERE run_id = ? "
                                            "ORDER BY release_id", (run_id,))]

    def link_scores(self, run_id: str, score_ids: Iterable[str], basis: str) -> int:
        """Record which existing ``model_scores`` rows this run reproduces."""
        rows = [(run_id, str(s), basis, utcnow()) for s in score_ids]
        with self.tx():
            self.con.executemany("INSERT OR IGNORE INTO md_run_score_links VALUES (?, ?, ?, ?)", rows)
        return len(rows)

    def pin_input(self, run_id: str, stage_path: str, role: str, source_sha256: str,
                  version_id: Optional[int] = None) -> None:
        r = self.fetchone("SELECT source_sha256 FROM md_run_inputs WHERE run_id = ? AND stage_path = ?",
                          (run_id, stage_path))
        if r:
            if r[0] != source_sha256:
                raise ModelDataError(f"{run_id}:{stage_path} already pinned to different bytes")
            return
        self.execute("INSERT INTO md_run_inputs VALUES (?, ?, ?, ?, ?)", (run_id, stage_path, role, version_id,
                                                                       source_sha256))

    def run_inputs(self, run_id: str) -> list[tuple[str, str, str, Optional[int]]]:
        return [tuple(r) for r in self.fetchall("SELECT stage_path, role, source_sha256, version_id FROM md_run_inputs "
                                                "WHERE run_id = ? ORDER BY stage_path", (run_id,))]

    def materialize_run(self, run_id: str, dest: Path, roles: Iterable[str] = ("INPUT", "EXPECTED_OUTPUT",
                                                                               "ARCHIVE", "MANIFEST")) -> list[Path]:
        roles = set(roles)
        out = []
        for stage_path, role, digest, _ in self.run_inputs(run_id):
            if role in roles:
                out.append(self.materialize_source(digest, Path(dest) / stage_path))
        return out

    def record_result(self, run_id: str, input_source: str, status: str, report: dict) -> None:
        self.execute("INSERT INTO md_run_results (run_id, executed_utc, input_source, status, report_json) "
                     "VALUES (?, ?, ?, ?, ?)", (run_id, utcnow(), input_source, status, json.dumps(report)))


def _ts(value: str) -> datetime:
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _at(values: Sequence, idx: Optional[int]) -> Optional[str]:
    return values[idx] if idx is not None and idx < len(values) else None


def open_store(path: Path | str, migrate: bool = True) -> Store:
    """Open the rolling history database (``data/gambling.sqlite``) as a model-input store."""
    from gambling.db.migrate import apply_migrations, connect as db_connect
    store = Store(db_connect(Path(path)))
    if migrate:
        apply_migrations(store.con)
    return store
