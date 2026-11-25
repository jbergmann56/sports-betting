"""Versioned, append-only model-input store (MySQL in production, SQLite for CI/offline).

Every source file is kept byte-for-byte (chunked BLOBs keyed by SHA-256), every
parsed dataset is an immutable version with a column catalog, lossless rows and a
content hash, and every reproducible run pins the exact files it used.

Connection URLs (``GAMBLING_MODELDATA_URL``):

* ``sqlite:///absolute/path.sqlite`` or ``sqlite:///:memory:``
* ``mysql://user:password@host:3306/gambling_model_data?ssl_ca=/path/DigiCertGlobalRootCA.crt.pem``
  (Azure Database for MySQL requires TLS; PyMySQL is the driver, ``pip install -e .[mysql]``).

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
from urllib.parse import parse_qs, unquote, urlparse

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"
CHUNK = 1 << 20  # 1 MiB; well under MySQL's default 64 MiB max_allowed_packet
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
                             "in the separate accounts database, not gambling_model_data")
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
    con: Any
    dialect: str  # "mysql" | "sqlite"

    # ------------------------------------------------------------------ plumbing
    @property
    def ph(self) -> str:
        return "%s" if self.dialect == "mysql" else "?"

    def q(self, sql: str) -> str:
        return sql.replace("?", self.ph)

    def execute(self, sql: str, params: Sequence = ()):
        cur = self.con.cursor()
        cur.execute(self.q(sql), tuple(params))
        return cur

    def fetchall(self, sql: str, params: Sequence = ()) -> list[tuple]:
        return list(self.execute(sql, params).fetchall())

    def fetchone(self, sql: str, params: Sequence = ()):
        return self.execute(sql, params).fetchone()

    def commit(self) -> None:
        self.con.commit()

    # ------------------------------------------------------------------ schema
    def preflight_mysql(self) -> None:
        """Fail before any DDL if append-only triggers cannot be created (MySQL DDL is not transactional)."""
        log_bin, trust = self.fetchone("SELECT @@log_bin, @@log_bin_trust_function_creators")
        if int(log_bin or 0) and not int(trust or 0):
            grants = " ".join(r[0] for r in self.fetchall("SHOW GRANTS FOR CURRENT_USER()"))
            if "SUPER" not in grants and "SET_USER_ID" not in grants:
                raise ModelDataError(
                    "binary logging is on and log_bin_trust_function_creators is OFF: the append-only triggers "
                    "cannot be created by this user. On Azure Database for MySQL set the server parameter "
                    "log_bin_trust_function_creators=ON (docs/model-data/README.md), then rerun migrate.")

    def migrate(self) -> list[str]:
        applied = []
        if self.dialect == "mysql":
            self.preflight_mysql()
        existing = {}
        try:
            existing = {r[0]: r[1] for r in self.fetchall("SELECT version, sha256 FROM schema_versions")}
        except Exception:  # table absent: fresh database
            if self.dialect == "mysql":
                self.con.rollback()
        for path in sorted((SCHEMA_DIR / self.dialect).glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(path.name.split("_", 1)[0])
            text = path.read_text(encoding="utf-8")
            digest = sha256_bytes(text.encode("utf-8"))
            if version in existing:
                if existing[version] != digest:
                    raise ModelDataError(f"schema {path.name} changed after it was applied; add a new migration")
                continue
            for stmt in text.split("\n-- ;;\n"):
                if any(line.strip() and not line.strip().startswith("--") for line in stmt.splitlines()):
                    self.con.cursor().execute(stmt)
            self.execute("INSERT INTO schema_versions VALUES (?, ?, ?, ?)", (version, path.name, digest, utcnow()))
            self.commit()
            applied.append(path.name)
        return applied

    # ------------------------------------------------------------------ source evidence
    def register_source(self, data: bytes, original_name: str, sensitivity: str, provenance: str,
                        actor: str, parent_sha256: Optional[str] = None,
                        parent_member_path: Optional[str] = None) -> str:
        if sensitivity not in SENSITIVITIES:
            raise ModelDataError(f"sensitivity must be one of {SENSITIVITIES}")
        digest = sha256_bytes(data)
        if self.fetchone("SELECT sha256 FROM source_files WHERE sha256 = ?", (digest,)):
            return digest  # identical bytes already preserved; content-addressed, nothing to change
        chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
        self.execute("INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (digest, len(data), original_name, media_type_for(original_name), sensitivity, provenance,
                      parent_sha256, parent_member_path, len(chunks), utcnow(), actor))
        for i, chunk in enumerate(chunks):
            self.execute("INSERT INTO source_file_chunks VALUES (?, ?, ?)", (digest, i, chunk))
        self.commit()
        return digest

    def read_source(self, digest: str) -> bytes:
        rows = self.fetchall("SELECT data FROM source_file_chunks WHERE sha256 = ? ORDER BY chunk_no", (digest,))
        meta = self.fetchone("SELECT bytes, chunk_count FROM source_files WHERE sha256 = ?", (digest,))
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
        if not self.fetchone("SELECT dataset_id FROM datasets WHERE dataset_id = ?", (dataset_id,)):
            self.execute("INSERT INTO datasets VALUES (?, ?, ?, ?, ?)", (dataset_id, domain, sport, description,
                                                                         utcnow()))
            self.commit()

    def import_version(self, dataset_id: str, version_label: str, source_sha256: str, parser: str,
                       actor: str, available_from_utc: Optional[str] = None, time_column: Optional[str] = None,
                       parent_version_id: Optional[int] = None, notes: Optional[str] = None,
                       reviewed_columns: Optional[dict[str, str]] = None) -> int:
        existing = self.fetchone("SELECT version_id, source_sha256 FROM dataset_versions WHERE dataset_id = ? AND "
                                 "version_label = ?", (dataset_id, version_label))
        if existing:
            if existing[1] != source_sha256:
                raise ModelDataError(f"{dataset_id}@{version_label} already exists with different source bytes")
            return int(existing[0])
        sensitivity = self.fetchone("SELECT sensitivity FROM source_files WHERE sha256 = ?", (source_sha256,))[0]
        columns, dtypes, rows = parse_table(self.read_source(source_sha256), parser)
        flags = guard_columns(columns, sensitivity, reviewed_columns)
        t_idx = columns.index(time_column) if time_column else None
        if time_column and t_idx is None:
            raise ModelDataError(f"time_column {time_column!r} not in columns")
        row_hashes = []
        payload = []
        for n, values in enumerate(rows):
            js = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
            h = sha256_bytes(js.encode("utf-8"))
            row_hashes.append(h)
            payload.append((n, values[t_idx] if t_idx is not None and t_idx < len(values) else None, h, js))
        content = sha256_bytes("".join(row_hashes).encode("ascii"))
        cur = self.execute("INSERT INTO dataset_versions (dataset_id, version_label, source_sha256, parser, "
                           "available_from_utc, time_column, row_count, column_count, content_sha256, "
                           "parent_version_id, import_tool, created_utc, notes) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (dataset_id, version_label, source_sha256, parser, available_from_utc, time_column,
                            len(rows), len(columns), content, parent_version_id, IMPORT_TOOL, utcnow(), notes))
        version_id = int(cur.lastrowid)
        if columns:
            self.con.cursor().executemany(self.q("INSERT INTO dataset_columns VALUES (?, ?, ?, ?, ?)"),
                                          [(version_id, i, c, d, f) for i, (c, d, f) in
                                           enumerate(zip(columns, dtypes, flags))])
        batch = 2000
        for i in range(0, len(payload), batch):
            self.con.cursor().executemany(self.q("INSERT INTO dataset_rows VALUES (?, ?, ?, ?, ?)"),
                                          [(version_id, *p) for p in payload[i:i + batch]])
        self.execute("INSERT INTO dataset_version_events (version_id, status, reason, event_utc, actor) "
                     "VALUES (?, 'STAGED', ?, ?, ?)", (version_id, "imported", utcnow(), actor))
        self.commit()
        return version_id

    def set_status(self, version_id: int, status: str, reason: str, actor: str) -> None:
        self.execute("INSERT INTO dataset_version_events (version_id, status, reason, event_utc, actor) "
                     "VALUES (?, ?, ?, ?, ?)", (version_id, status, reason, utcnow(), actor))
        self.commit()

    def status(self, version_id: int) -> Optional[str]:
        r = self.fetchone("SELECT status FROM dataset_version_status WHERE version_id = ?", (version_id,))
        return r[0] if r else None

    def columns(self, version_id: int) -> list[str]:
        return [r[0] for r in self.fetchall("SELECT name FROM dataset_columns WHERE version_id = ? ORDER BY ordinal",
                                            (version_id,))]

    def rows(self, version_id: int, as_of_utc: Optional[str] = None,
             include_untimed: bool = False) -> list[dict]:
        """Rows in source order. With ``as_of_utc`` only rows whose time column is <= the cutoff
        (rows without a time value are excluded unless ``include_untimed``)."""
        cols = self.columns(version_id)
        out = []
        for row_time, js in self.fetchall("SELECT row_time_utc, row_json FROM dataset_rows WHERE version_id = ? "
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
                "SELECT version_id, available_from_utc, status FROM dataset_version_status WHERE dataset_id = ?",
                (dataset_id,)):
            if status != "PUBLISHED" or available is None or _ts(available) > _ts(cutoff_utc):
                continue
            if best is None or (_ts(available), version_id) > best[0]:
                best = ((_ts(available), version_id), version_id)
        return best[1] if best else None

    def verify_version(self, version_id: int) -> dict:
        """Re-parse the preserved source bytes and compare every row hash with the stored rows."""
        source, parser, content = self.fetchone("SELECT source_sha256, parser, content_sha256 FROM dataset_versions "
                                                "WHERE version_id = ?", (version_id,))
        columns, _, rows = parse_table(self.read_source(source), parser)
        hashes = [sha256_bytes(json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                  for v in rows]
        stored = [r[0] for r in self.fetchall("SELECT row_sha256 FROM dataset_rows WHERE version_id = ? ORDER BY "
                                              "row_no", (version_id,))]
        ok = hashes == stored and columns == self.columns(version_id) and \
            sha256_bytes("".join(hashes).encode("ascii")) == content
        return {"version_id": version_id, "rows": len(stored), "lossless": ok}

    # ------------------------------------------------------------------ runs
    def register_run(self, run_id: str, kind: str, release_ids: Sequence[str], environment: dict, scorer: Any,
                     input_cutoff_utc: Optional[str] = None, notes: Optional[str] = None) -> None:
        if self.fetchone("SELECT run_id FROM model_runs WHERE run_id = ?", (run_id,)):
            return
        self.execute("INSERT INTO model_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (run_id, kind, json.dumps(list(release_ids)), input_cutoff_utc, json.dumps(environment),
                      json.dumps(scorer), utcnow(), notes))
        self.commit()

    def pin_input(self, run_id: str, stage_path: str, role: str, source_sha256: str,
                  version_id: Optional[int] = None) -> None:
        r = self.fetchone("SELECT source_sha256 FROM run_inputs WHERE run_id = ? AND stage_path = ?",
                          (run_id, stage_path))
        if r:
            if r[0] != source_sha256:
                raise ModelDataError(f"{run_id}:{stage_path} already pinned to different bytes")
            return
        self.execute("INSERT INTO run_inputs VALUES (?, ?, ?, ?, ?)", (run_id, stage_path, role, version_id,
                                                                       source_sha256))
        self.commit()

    def run_inputs(self, run_id: str) -> list[tuple[str, str, str, Optional[int]]]:
        return [tuple(r) for r in self.fetchall("SELECT stage_path, role, source_sha256, version_id FROM run_inputs "
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
        self.execute("INSERT INTO run_results (run_id, executed_utc, input_source, status, report_json) "
                     "VALUES (?, ?, ?, ?, ?)", (run_id, utcnow(), input_source, status, json.dumps(report)))
        self.commit()


def _ts(value: str) -> datetime:
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def connect(url: str) -> Store:
    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else parsed.path
        con = sqlite3.connect(path or ":memory:")
        con.execute("PRAGMA foreign_keys = ON")
        return Store(con, "sqlite")
    if parsed.scheme == "mysql":
        try:
            import pymysql
        except ImportError as exc:
            raise ModelDataError("MySQL backend needs PyMySQL: pip install -e .[mysql]") from exc
        opts = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        ssl = {"ca": opts["ssl_ca"]} if "ssl_ca" in opts else None
        con = pymysql.connect(host=parsed.hostname, port=parsed.port or 3306, user=unquote(parsed.username or ""),
                              password=unquote(parsed.password or ""), database=parsed.path.lstrip("/"),
                              charset="utf8mb4", ssl=ssl, autocommit=False)
        return Store(con, "mysql")
    raise ModelDataError(f"unsupported URL scheme {parsed.scheme!r}")
