"""Command line for the model-input database.

    python -m gambling.modeldata migrate
    python -m gambling.modeldata import FILE --dataset ID --domain odds --label v1 --sensitivity PUBLIC_MARKET \\
        --provenance "Bovada capture 20261112T134056Z_68f7ec" [--sport NBA] [--available-from UTC] \\
        [--time-column snapshot_as_of_utc] [--review-column NAME=justification ...] [--publish]
    python -m gambling.modeldata status DATASET
    python -m gambling.modeldata publish VERSION_ID --reason TEXT
    python -m gambling.modeldata retract VERSION_ID --reason TEXT
    python -m gambling.modeldata materialize-source SHA256 DEST
    python -m gambling.modeldata materialize-run RUN_ID DEST_DIR
    python -m gambling.modeldata verify [VERSION_ID ...]
    python -m gambling.modeldata append FILE --dataset ID       # add new/changed records to a growing master
    python -m gambling.modeldata master DATASET DEST.csv      # write the cumulative master
    python -m gambling.modeldata snapshot DEST.sqlite         # consistent copy + .sha256 for sharing/backup
    python -m gambling.modeldata golden [--external DIR]      # import golden fixtures + prove replay

The database is the rolling history SQLite file: --db, else $GAMBLING_DB, else data/gambling.sqlite.
The md_* tables are created by migration 0006 through the same migrator as the rest of the file.
Imports never overwrite: identical bytes are deduplicated by SHA-256; a reused label with
different bytes is refused.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from gambling.modeldata.golden import main as golden_main
from gambling.config import PACKAGE_ROOT
from gambling.modeldata.store import open_store, parser_for


DEFAULT_DB = PACKAGE_ROOT / "data" / "gambling.sqlite"


def _db(args) -> Path:
    return Path(args.db or os.environ.get("GAMBLING_DB") or DEFAULT_DB)


def _store(args):
    db = _db(args)
    if not db.exists():
        sys.exit(f"{db} does not exist; run `python -m gambling db init` first")
    return open_store(db, migrate=args.cmd == "migrate")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gambling.modeldata", description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="SQLite file (default $GAMBLING_DB or data/gambling.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    imp = sub.add_parser("import")
    imp.add_argument("file")
    imp.add_argument("--dataset", required=True)
    imp.add_argument("--domain", required=True)
    imp.add_argument("--label", required=True)
    imp.add_argument("--sensitivity", required=True,
                     choices=["PUBLIC_MARKET", "MODEL_INTERNAL", "CONTAINS_USER_OBSERVATION_FLAGS"])
    imp.add_argument("--provenance", required=True)
    imp.add_argument("--sport")
    imp.add_argument("--description", default="")
    imp.add_argument("--parser", help="override: csv | csv.gz | parquet | json | blob")
    imp.add_argument("--available-from")
    imp.add_argument("--time-column")
    imp.add_argument("--game-key-column", help="column holding the existing events.game_key")
    imp.add_argument("--review-column", action="append", default=[], metavar="NAME=JUSTIFICATION")
    imp.add_argument("--key-column", action="append", default=[],
                     help="record key for a growing master (repeatable); later appends supersede by key")
    imp.add_argument("--publish", action="store_true")
    ag = sub.add_parser("append")
    ag.add_argument("file", help="new records, or a full re-export (only records not already present are stored)")
    ag.add_argument("--dataset", required=True)
    ag.add_argument("--provenance", required=True)
    ag.add_argument("--run-id")
    ag.add_argument("--available-from")
    ag.add_argument("--label")
    mm = sub.add_parser("master")
    mm.add_argument("dataset")
    mm.add_argument("dest")
    mm.add_argument("--as-of")
    st = sub.add_parser("status")
    st.add_argument("dataset")
    for name in ("publish", "retract"):
        p = sub.add_parser(name)
        p.add_argument("version_id", type=int)
        p.add_argument("--reason", required=True)
    ms = sub.add_parser("materialize-source")
    ms.add_argument("sha256")
    ms.add_argument("dest")
    mr = sub.add_parser("materialize-run")
    mr.add_argument("run_id")
    mr.add_argument("dest")
    ve = sub.add_parser("verify")
    ve.add_argument("version_ids", nargs="*", type=int)
    sn = sub.add_parser("snapshot")
    sn.add_argument("dest")
    go = sub.add_parser("golden")
    go.add_argument("--external", default=os.environ.get("GOLDEN_EXTERNAL_DIR"))
    args = ap.parse_args(argv)
    actor = os.environ.get("GAMBLING_MODELDATA_ACTOR") or getpass.getuser()

    if args.cmd == "golden":
        return golden_main(["--db", str(_db(args))] + (["--external", args.external] if args.external else []))
    s = _store(args)
    if args.cmd == "migrate":
        print(json.dumps({"applied": s.migrate()}))
    elif args.cmd == "import":
        path = Path(args.file)
        reviewed = dict(item.split("=", 1) for item in args.review_column)
        sha = s.register_source(path.read_bytes(), path.name, args.sensitivity, args.provenance, actor)
        s.ensure_dataset(args.dataset, args.domain, args.sport, args.description or args.dataset)
        vid = s.import_version(args.dataset, args.label, sha, args.parser or parser_for(path.name), actor,
                               available_from_utc=args.available_from, time_column=args.time_column,
                               reviewed_columns=reviewed, game_key_column=args.game_key_column,
                               key_columns=args.key_column or None)
        if args.publish:
            s.set_status(vid, "PUBLISHED", "published at import", actor)
        print(json.dumps({"source_sha256": sha, "version_id": vid, "status": s.status(vid),
                          **s.verify_version(vid)}))
    elif args.cmd == "append":
        path = Path(args.file)
        vid = s.append_file(args.dataset, path.read_bytes(), path.name, actor, args.provenance,
                            run_id=args.run_id, available_from_utc=args.available_from, label=args.label)
        chain = s.chain(args.dataset)
        print(json.dumps({"version_id": vid, "appended": 0 if vid is None else s.fetchone(
            "SELECT row_count FROM md_dataset_versions WHERE version_id = ?", (vid,))[0],
            "chain_length": len(chain), "master_records": len(s.master_rows(args.dataset))}))
    elif args.cmd == "master":
        print(s.materialize_master(args.dataset, Path(args.dest), args.as_of))
    elif args.cmd == "status":
        print(json.dumps([dict(zip(("version_id", "label", "available_from_utc", "status"), r)) for r in s.fetchall(
            "SELECT version_id, version_label, available_from_utc, status FROM md_dataset_version_status "
            "WHERE dataset_id = ? ORDER BY version_id", (args.dataset,))], indent=2))
    elif args.cmd in ("publish", "retract"):
        s.set_status(args.version_id, "PUBLISHED" if args.cmd == "publish" else "RETRACTED", args.reason, actor)
        print(json.dumps({"version_id": args.version_id, "status": s.status(args.version_id)}))
    elif args.cmd == "materialize-source":
        print(s.materialize_source(args.sha256, Path(args.dest)))
    elif args.cmd == "materialize-run":
        for p in s.materialize_run(args.run_id, Path(args.dest)):
            print(p)
    elif args.cmd == "snapshot":
        print(json.dumps(s.snapshot(Path(args.dest)), indent=2))
    elif args.cmd == "verify":
        ids = args.version_ids or [r[0] for r in s.fetchall("SELECT version_id FROM md_dataset_versions")]
        results = [s.verify_version(i) for i in ids]
        print(json.dumps({"versions": len(results), "lossless": sum(r["lossless"] for r in results)}))
        return 0 if all(r["lossless"] for r in results) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
