"""Command line: frozen-evidence audit, Bovada odds capture, rolling SQLite history.

`fetch` only reads Bovada's public odds feed and writes capture files.
`ingest` loads those capture JSON files into the rolling database. Nothing here
authenticates to a sportsbook, submits stakes, or approximates a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Paths, default_paths
from .history import frozen

EXIT_OK, EXIT_CHECK_FAILED, EXIT_FETCH_INCOMPLETE = 0, 1, 2


def _emit(result: Any) -> None:
    print(json.dumps(result, indent=2, default=str))


# -- frozen evidence ---------------------------------------------------------

def cmd_init(args, paths: Paths) -> int:
    print(f"Initialized local history: {frozen.extract_frozen(paths, force=args.force)}")
    return EXIT_OK


def cmd_audit(args, paths: Paths) -> int:
    with frozen.connect_frozen(paths) as con:
        result = frozen.audit(con)
    _emit(result)
    return EXIT_CHECK_FAILED if result["integrity"] != "ok" or result["foreign_key_errors"] else EXIT_OK


def cmd_scores(args, paths: Paths) -> int:
    with frozen.connect_frozen(paths) as con:
        _emit(frozen.frozen_scores(con, args.date, args.batch))
    return EXIT_OK


def cmd_parlays(args, paths: Paths) -> int:
    _emit(frozen.research_parlays(paths, args.date, args.limit))
    return EXIT_OK


# -- capture -----------------------------------------------------------------

def cmd_fetch(args, paths: Paths) -> int:
    from .bovada import FetchConfig, fetch_board, replay_run
    from .bovada.endpoints import LEAGUES

    if args.replay:
        run = replay_run(Path(args.replay))
    else:
        sports = [s.strip().upper() for s in args.sports.split(",")] if args.sports else list(LEAGUES)
        config = FetchConfig(max_age_seconds=args.max_age, all_variants=not args.first_ok,
                             recover_events=not args.no_recover)
        run = fetch_board(sports, Path(args.out) if args.out else paths.captures, config=config)
    manifest = run.manifest()
    manifest["run_dir"] = str(run.run_dir) if run.run_dir else None
    _emit(manifest)
    return EXIT_OK if run.ok else EXIT_FETCH_INCOMPLETE


# -- rolling database --------------------------------------------------------

def cmd_db(args, paths: Paths) -> int:
    from . import db
    from .db.export import export_snapshot
    from .db.queries import status

    if args.db_command == "init":
        _emit(db.init_database(paths))
        return EXIT_OK
    con = db.open_database(paths)
    try:
        if args.db_command == "status":
            result = status(con)
            _emit(result)
            return EXIT_CHECK_FAILED if result["integrity"] != "ok" or result["foreign_key_errors"] else EXIT_OK
        _emit({"archive": str(export_snapshot(con, paths.archives))})
        return EXIT_OK
    finally:
        con.close()


def cmd_ingest(args, paths: Paths) -> int:
    from . import db

    con = db.open_database(paths)
    try:
        run_dirs = [Path(p) for p in args.run_dirs]
        if args.all:
            run_dirs += db.pending_captures(con, paths.captures)
        if not run_dirs:
            _emit({"ingested": [], "note": "nothing to ingest"})
            return EXIT_OK
        results, failed = [], False
        for run_dir in run_dirs:
            try:
                results.append(db.ingest_capture(con, run_dir))
            except (db.IngestError, OSError, ValueError) as exc:
                failed = True
                results.append({"run_dir": str(run_dir), "status": "ERROR", "error": str(exc)})
        _emit({"ingested": results})
        return EXIT_CHECK_FAILED if failed else EXIT_OK
    finally:
        con.close()


def cmd_history(args, paths: Paths) -> int:
    from . import db
    from .db import queries
    from .timeutil import utcnow

    con = db.open_database(paths)
    try:
        if args.history_command == "latest":
            after = None if args.include_started else utcnow().isoformat()
            _emit(queries.latest_quotes(con, args.sport, upcoming_after=after,
                                        offered_only=not args.all_statuses, limit=args.limit))
        elif args.history_command == "lines":
            _emit(queries.line_history(con, args.game_key))
        elif args.history_command == "find":
            _emit(queries.find_games(con, args.text))
        else:
            _emit(queries.capture_health(con, args.since))
        return EXIT_OK
    finally:
        con.close()


def cmd_models(args, paths: Paths) -> int:
    from . import db
    from .db import models

    con = db.open_database(paths)
    try:
        if args.models_command == "list":
            _emit(models.current_releases(con, args.sport))
        elif args.models_command == "show":
            _emit(models.release_detail(con, args.release_id))
        elif args.models_command == "attribution":
            _emit(models.attribution_summary(con))
        else:
            result = models.verify_artifacts(con, release_id=args.release_id)
            _emit(result)
            return EXIT_OK if result["all_verified"] else EXIT_CHECK_FAILED
        return EXIT_OK
    finally:
        con.close()


def cmd_results(args, paths: Paths) -> int:
    """ESPN results: fetch (network, user machine), conflicts, NBA history feed."""
    from datetime import date, timedelta
    from . import db
    from .results import espn

    con = db.open_database(paths)
    try:
        if args.results_command == "fetch":
            start = date.fromisoformat(args.date)
            end = date.fromisoformat(args.through) if args.through else start
            days = [(start + timedelta(n)).isoformat() for n in range((end - start).days + 1)]
            out = []
            for sport in args.sport:
                try:
                    out += espn.collect(con, sport, days)
                except (OSError, espn.ResultsError, ValueError) as exc:
                    out.append({"sport": sport, "status": "ERROR", "error": str(exc)})
            _emit(out)
            return EXIT_FETCH_INCOMPLETE if any(r.get("status") == "ERROR" for r in out) else EXIT_OK
        if args.results_command == "conflicts":
            rows = con.execute("SELECT * FROM espn_result_conflicts ORDER BY conflict_id").fetchall()
            _emit([dict(r) for r in rows])
            return EXIT_CHECK_FAILED if rows else EXIT_OK
        feed = espn.nba_history_rows(con, Path(args.base), args.through)
        if feed["unknown_teams"] and not args.allow_new_names:
            _emit({**{k: v for k, v in feed.items() if k != "rows"}, "new_rows": len(feed["rows"]),
                   "status": "BLOCKED: team names not in the base history; review before scoring "
                             "(--allow-new-names to write anyway)"})
            return EXIT_CHECK_FAILED
        digest = espn.write_nba_history(Path(args.base), feed["rows"], Path(args.out))
        _emit({"out": args.out, "sha256": digest, "new_rows": len(feed["rows"]), "base_last_date": feed["base_last_date"],
               "unknown_teams": feed["unknown_teams"], "duplicates": feed["duplicates"]})
        return EXIT_OK
    finally:
        con.close()


def _print_text(text: str) -> None:
    """Print text, substituting characters the console cannot encode (e.g. '→' on a Windows cp1252 console).
    Report files are always written as UTF-8; this only affects what the terminal shows."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc))


def cmd_accounts(args, paths: Paths) -> int:
    """Bovada account exports: read-only profile, or import into the SEPARATE accounts database."""
    from .accounts import exports
    from .config import PACKAGE_ROOT

    if args.accounts_command == "cleanse":  # works on the accounts DB only; takes no --export-dir
        from .accounts.cleanse import run_cleanse
        db = Path(args.db) if args.db else paths.data_dir / "accounts" / "accounts.sqlite"
        scores = Path(args.scoring_db) if args.scoring_db else None
        r = run_cleanse(db, scoring_db=scores)
        failed = [k for k, v in r["gates"].items() if not k.startswith("_") and not v["pass"]]
        print(f"DQ run {r['run_id']}: {r['status']}  fingerprint {r['fingerprint'][:16]}")
        print(f"  wagers {r['wagers']}  open {r['open_wagers']}  adjustments {r['adjustments']}  exclusions "
              f"{r['exclusions']}  non-sports {r['non_sports']}  links {r['links']}")
        print(f"  issues by rule: {r['issues_by_rule']}")
        print(f"  raw tickets {r['raw_tickets']}; not yet in the baseline (settled):")
        for k, v in sorted(r["after_baseline"].items()):
            print(f"    {k}: {v['tickets']} tickets, stake {v['stake_cents'] / 100:,.2f}, net {v['net_pnl_cents'] / 100:+,.2f}")
        ns = r["non_sports_raw"]
        print(f"  raw non-sports {r['raw_non_sports']} ({ns['matched_baseline_rows']} matched to baseline rows); "
              "after the baseline:")
        for k, v in ns["after_baseline"].items():
            rec = "not classified" if v["recognized_pnl_cents"] is None else f"{v['recognized_pnl_cents'] / 100:+,.2f}"
            print(f"    {k}: {v['rows']} rows, wallet {v['delta_cents'] / 100:+,.2f}, recognized P&L {rec}")
        for k, v in r["gates"].items():
            if not k.startswith("_"):
                print(f"  [{'PASS' if v['pass'] else 'FAIL'}] {k}: {v['actual']} (expected {v['expected']})")
        if failed:
            print("No canonical rows written; see dq_issues for this run.")
        return 0 if not failed else 1
    folder = Path(args.export_dir or PACKAGE_ROOT / "bovada_transactions" / "bovada_export")
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} not found")
    if args.accounts_command == "import":
        from .accounts.importer import ImportRefused, import_exports
        db = Path(args.db) if args.db else paths.data_dir / "accounts" / "accounts.sqlite"
        try:
            result = import_exports(db, folder, Path(args.baseline) if args.baseline else None,
                                    scoring_db=paths.database, since=args.since)
        except ImportRefused as exc:
            _emit({"status": "REFUSED", "reason": str(exc)})
            return EXIT_CHECK_FAILED
        _emit({"status": "IMPORTED", "database": str(db), **result})
        return EXIT_OK
    report = exports.profile_exports(folder, Path(args.baseline) if args.baseline else None, args.since)
    out = Path(args.out) if args.out else paths.data_dir / "accounts" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_utc"][:19].replace(":", "").replace("-", "")
    (out / f"export_profile_{stamp}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / f"export_profile_{stamp}.md").write_text(exports.markdown(report), encoding="utf-8")
    _print_text(exports.markdown(report))
    _print_text(f"Written: {out / f'export_profile_{stamp}.md'} (+ .json)")
    return EXIT_OK if report["import_ready"] else EXIT_CHECK_FAILED


def cmd_daily(args, paths: Paths) -> int:
    from .pipeline.nba import PipelineError, latest_capture, run_nba_daily
    capture = Path(args.capture) if args.capture else latest_capture(paths.captures, "NBA")
    if capture.is_dir():
        capture = capture / "quotes.csv"
    db = paths.database if paths.database.exists() else None
    try:
        m = run_nba_daily(args.date, capture, paths.data_dir, db, allow_new_names=args.allow_new_names)
    except PipelineError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    print(f"NBA {m['slate_date']} run {m['run_id']} ({m['validation_status']})")
    print(f"  capture {capture} (quotes as of {m['inputs']['capture_quotes_csv']['quote_as_of_utc_max']})")
    h = m["inputs"]["history"]
    print(f"  history through {h['last_date']} (+{h['espn_rows_added']} ESPN finals)")
    print(f"  {m['outputs']['rows']} rows: {m['outputs']['sheet_status']}")
    print(f"  written to {m['run_dir']}")
    return 0


def cmd_reconcile(args, paths: Paths) -> int:
    """Replay recorded batches through the frozen adapters (read-only)."""
    import sqlite3
    if not paths.database.exists():
        raise FileNotFoundError(f"{paths.database} does not exist")
    con = sqlite3.connect(f"file:{paths.database}?mode=ro", uri=True)
    try:
        if args.sport == "NHL":
            from .reconcile import nhl as rec
        else:
            from .reconcile import nba as rec
        reports = [r for b in args.batch for r in (lambda x: x if isinstance(x, list) else [x])(
            rec.reconcile_batch(con, b))] if args.batch else rec.reconcile_all(con)
        _emit(reports)
        bad = [r for r in reports if r.get("status", "COMPARED") != "COMPARED"
               or any(k in (r.get("outcomes") or {}) for k in ("DIFFERS", "PROBABILITY_DIFFERS", "EV_DIFFERS",
                                                                "NOT_REPLAYED", "SIDE_UNRESOLVED"))
               and not (r.get("decisions_only") or {}).get("outcomes", {}).get("MATCH")]
        return EXIT_CHECK_FAILED if bad else EXIT_OK
    finally:
        con.close()


# -- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m gambling",
                                     description="Five-sport Gambling history, Bovada capture and rolling SQLite ledger")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Extract the read-only frozen snapshot from the bundled ZIP")
    init.add_argument("--force", action="store_true", help="Re-extract the frozen snapshot")
    init.set_defaults(handler=cmd_init)

    commands.add_parser("audit", help="Count frozen records and verify integrity").set_defaults(handler=cmd_audit)

    for name in ("scores", "replay"):  # `replay` kept as the original name
        score = commands.add_parser(name, help="Show frozen production/research score rows for a historical date")
        score.add_argument("--date", default="2026-11-11")
        score.add_argument("--batch", help="Explicit original capture batch ID")
        score.set_defaults(handler=cmd_scores)

    parlay = commands.add_parser("parlays", help="Inspect archived research-only theoretical parlays")
    parlay.add_argument("--date", default="2026-11-11")
    parlay.add_argument("--limit", type=int, default=8)
    parlay.set_defaults(handler=cmd_parlays)

    grab = commands.add_parser("fetch", help="Capture Bovada main-market odds to files (read-only)")
    grab.add_argument("--sports", help="Comma list of NFL,NCAAFB,NBA,NCAABB,NHL (default: all)")
    grab.add_argument("--out", help="Capture root directory (default: <data>/captures)")
    grab.add_argument("--max-age", type=int, default=900, help="Reject CDN responses older than N seconds")
    grab.add_argument("--first-ok", action="store_true", help="Stop at the first usable URL variant per sport")
    grab.add_argument("--no-recover", action="store_true", help="Skip event-page recovery of incomplete games")
    grab.add_argument("--replay", metavar="RUN_DIR", help="Rebuild a captured run offline instead of fetching")
    grab.set_defaults(handler=cmd_fetch)

    database = commands.add_parser("db", help="Rolling SQLite database")
    db_commands = database.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="Create/upgrade the database and import the frozen archive once")
    db_commands.add_parser("status", help="Migrations, imports, counts and integrity")
    db_commands.add_parser("export", help="Write a new point-in-time archive ZIP")
    database.set_defaults(handler=cmd_db)

    ingest = commands.add_parser("ingest", help="Load capture JSON files into the rolling database")
    ingest.add_argument("run_dirs", nargs="*", help="Capture run directories")
    ingest.add_argument("--all", action="store_true", help="Also ingest every not-yet-ingested capture")
    ingest.set_defaults(handler=cmd_ingest)

    history = commands.add_parser("history", help="Query the rolling history")
    h_commands = history.add_subparsers(dest="history_command", required=True)
    latest = h_commands.add_parser("latest", help="Newest observed price per upcoming game/market/side")
    latest.add_argument("--sport")
    latest.add_argument("--limit", type=int, default=500)
    latest.add_argument("--include-started", action="store_true", help="Include games already started")
    latest.add_argument("--all-statuses", action="store_true", help="Include suspended/not offered sides")
    lines = h_commands.add_parser("lines", help="Line movement for one game")
    lines.add_argument("game_key", help="e.g. NBA:BOVADA:33233970 (see `history find`)")
    find = h_commands.add_parser("find", help="Find game keys by team or matchup text")
    find.add_argument("text")
    health = h_commands.add_parser("health", help="Bovada fetch reliability by day and sport")
    health.add_argument("--since", help="UTC date YYYY-MM-DD")
    history.set_defaults(handler=cmd_history)

    registry = commands.add_parser("models", help="Model release registry")
    m_commands = registry.add_subparsers(dest="models_command", required=True)
    listing = m_commands.add_parser("list", help="Every release with its current role and authorization")
    listing.add_argument("--sport")
    show = m_commands.add_parser("show", help="One release: status history, files, legacy labels, predictions")
    show.add_argument("release_id")
    verify = m_commands.add_parser("verify", help="Re-hash every registered model file")
    verify.add_argument("release_id", nargs="?")
    m_commands.add_parser("attribution", help="How recorded scores map to releases; duplicates collapsed")
    registry.set_defaults(handler=cmd_models)

    results = commands.add_parser("results", help="ESPN finals: capture, record, NBA history feed (read-only)")
    r_commands = results.add_subparsers(dest="results_command", required=True)
    rf = r_commands.add_parser("fetch", help="Capture ESPN scoreboards and record new finals")
    rf.add_argument("--sport", action="append", required=True, choices=["NBA", "NHL", "NFL", "NCAAFB", "NCAABB"])
    rf.add_argument("--date", required=True, help="Scoreboard date YYYY-MM-DD")
    rf.add_argument("--through", help="Last date (inclusive) for a range")
    r_commands.add_parser("conflicts", help="Observed finals that differ from recorded ones (exit 1 if any)")
    nh = r_commands.add_parser("nba-history", help="Write base NBA history + new ESPN finals to a NEW file")
    nh.add_argument("--base", required=True)
    nh.add_argument("--through", required=True, help="Last game date to include (the day before the slate)")
    nh.add_argument("--out", required=True)
    nh.add_argument("--allow-new-names", action="store_true")
    results.set_defaults(handler=cmd_results)

    daily = commands.add_parser("daily", help="Daily pipeline: capture -> frozen scorer -> bet sheet (NBA)")
    daily.add_argument("sport", choices=["NBA"])
    daily.add_argument("--date", required=True, help="slate date (Central), YYYY-MM-DD")
    daily.add_argument("--capture", help="capture quotes.csv or run folder (default: newest capture with NBA)")
    daily.add_argument("--allow-new-names", action="store_true", help="accept ESPN team names the history never used")
    daily.set_defaults(handler=cmd_daily)

    reconcile = commands.add_parser("reconcile", help="Replay recorded score batches through frozen adapters (read-only)")
    reconcile.add_argument("--sport", required=True, choices=["NHL", "NBA"])
    reconcile.add_argument("--batch", action="append", help="batch_id (repeatable); default every recorded batch")
    reconcile.set_defaults(handler=cmd_reconcile)

    accounts = commands.add_parser("accounts", help="Bovada account exports (read-only profile; import comes after review)")
    a_commands = accounts.add_subparsers(dest="accounts_command", required=True)
    prof = a_commands.add_parser("profile", help="Coverage, counts, missing periods, duplicates, balance chain")
    prof.add_argument("--export-dir", help="default bovada_transactions/bovada_export")
    prof.add_argument("--baseline", help="P&L baseline gambling_pnl_*.sqlite to reconcile wagers against")
    prof.add_argument("--since", help="assess coverage from this date (e.g. 2026-09-02); earlier gaps reported")
    prof.add_argument("--out", help="report folder (default <data>/accounts/reports, outside Git)")
    imp = a_commands.add_parser("import", help="Import raw exports (+ P&L baseline) into data/accounts/accounts.sqlite")
    imp.add_argument("--export-dir", help="default bovada_transactions/bovada_export")
    imp.add_argument("--baseline", help="P&L baseline gambling_pnl_*.sqlite (copied verbatim)")
    imp.add_argument("--since", help="coverage assessment start, as for profile")
    imp.add_argument("--db", help="accounts database (default <data>/accounts/accounts.sqlite; never gambling.sqlite)")
    cl = a_commands.add_parser("cleanse", help="DQ-01..DQ-12 cleanse of the accounts DB raw layer (gated, append-only)")
    cl.add_argument("--db", help="accounts database (default <data>/accounts/accounts.sqlite)")
    cl.add_argument("--scoring-db", help="optional gambling.sqlite to reconcile score ids (DQ-10), opened read-only")
    accounts.set_defaults(handler=cmd_accounts)
    return parser


def main(argv: list[str] | None = None, paths: Paths | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args, paths or default_paths())


if __name__ == "__main__":
    sys.exit(main())
