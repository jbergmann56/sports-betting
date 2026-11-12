"""Model registry queries and artifact verification.

A release's identity is its ``release_id``; scores link to it by that ID. The
artifact hashes are checked here, when verifying a release, not on every query.
"""

from __future__ import annotations

import hashlib
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from ..config import PACKAGE_ROOT


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cursor.fetchall()]


def _read_artifact(location: str, root: Path) -> bytes:
    if location.startswith("zip:"):
        archive, member = location[4:].split("!", 1)
        with zipfile.ZipFile(root / archive) as bundle:
            return bundle.read(member)
    return (root / location).read_bytes()


def verify_artifacts(con: sqlite3.Connection, root: Path = PACKAGE_ROOT,
                     release_id: str | None = None) -> dict[str, Any]:
    """Recompute every registered artifact's sha256. A release is VERIFIED only if all match."""
    sql = "SELECT release_id, location, artifact_role, sha256 FROM model_release_artifacts"
    args: tuple = ()
    if release_id:
        sql += " WHERE release_id = ?"
        args = (release_id,)
    results: dict[str, dict[str, Any]] = {}
    for row in con.execute(sql + " ORDER BY release_id, location", args):
        entry = results.setdefault(row["release_id"], {"release_id": row["release_id"], "files": []})
        try:
            actual = hashlib.sha256(_read_artifact(row["location"], root)).hexdigest()
            status = "OK" if actual == row["sha256"] else "MODIFIED"
        except (FileNotFoundError, KeyError):
            status = "MISSING"
        entry["files"].append({"location": row["location"], "role": row["artifact_role"], "status": status})
    for entry in results.values():
        entry["status"] = "VERIFIED" if all(f["status"] == "OK" for f in entry["files"]) else "FAILED"
    releases = [dict(r) for r in con.execute(
        "SELECT release_id, artifact_status FROM model_releases" + (" WHERE release_id = ?" if release_id else ""), args)]
    for release in releases:
        if release["release_id"] not in results:
            results[release["release_id"]] = {"release_id": release["release_id"], "files": [],
                                              "status": "NO_ARTIFACTS_REGISTERED"}
        results[release["release_id"]]["artifact_status"] = release["artifact_status"]
    ordered = sorted(results.values(), key=lambda r: r["release_id"])
    return {"all_verified": all(r["status"] in ("VERIFIED", "NO_ARTIFACTS_REGISTERED") for r in ordered),
            "releases": ordered}


def current_releases(con: sqlite3.Connection, sport: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT sport, release_id, component_kind, markets_json, role, scoring_authority, wagering_authorized, "
           "effective_from_utc, evidence_level, artifact_status FROM current_release_status")
    args: tuple = ()
    if sport:
        sql += " WHERE sport = ?"
        args = (sport,)
    return _rows(con.execute(sql + " ORDER BY sport, scoring_authority DESC, role, release_id", args))


def release_detail(con: sqlite3.Connection, release_id: str) -> dict[str, Any]:
    release = con.execute("SELECT * FROM model_releases WHERE release_id = ?", (release_id,)).fetchone()
    if release is None:
        raise KeyError(f"Unknown release {release_id!r}")
    return {
        "release": dict(release),
        "status_history": _rows(con.execute(
            "SELECT role, scoring_authority, wagering_authorized, effective_from_utc, effective_until_utc, "
            "evidence_level, decision_source, notes FROM release_status_history WHERE release_id = ? "
            "ORDER BY julianday(effective_from_utc), status_id", (release_id,))),
        "artifacts": _rows(con.execute(
            "SELECT location, artifact_role, sha256, bytes FROM model_release_artifacts WHERE release_id = ? "
            "ORDER BY location", (release_id,))),
        "legacy_labels": _rows(con.execute(
            "SELECT model_version, market, evidence_level, evidence FROM model_release_aliases "
            "WHERE release_id = ? ORDER BY model_version, market", (release_id,))),
        "predictions": dict(con.execute(
            "SELECT COUNT(*) AS predictions, SUM(action_status = 'PRODUCTION_QUALIFIED') AS production_qualified, "
            "SUM(action_status = 'RESEARCH_POSITIVE_EV') AS research_positive_ev, "
            "MIN(quote_captured_utc) AS first_quote_utc, MAX(quote_captured_utc) AS last_quote_utc "
            "FROM model_predictions WHERE release_id = ?", (release_id,)).fetchone()),
    }


def attribution_summary(con: sqlite3.Connection) -> dict[str, Any]:
    """How every recorded score is attributed, and how many duplicate copies collapse."""
    return {
        "by_attribution": _rows(con.execute(
            "SELECT attribution, COUNT(*) AS scores FROM model_score_attribution GROUP BY 1 ORDER BY 1")),
        "unresolved_labels": _rows(con.execute(
            "SELECT sport, recorded_label, market, COUNT(*) AS scores FROM model_score_attribution "
            "WHERE attribution = 'UNRESOLVED' GROUP BY 1, 2, 3")),
        "recorded_scores": con.execute("SELECT COUNT(*) FROM model_scores").fetchone()[0],
        "distinct_predictions": con.execute("SELECT COUNT(*) FROM model_predictions").fetchone()[0],
        "collapsed_copies": _rows(con.execute(
            "SELECT sport, release_id, market, COUNT(*) AS predictions, SUM(recorded_rows - 1) AS extra_copies "
            "FROM model_predictions WHERE recorded_rows > 1 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3")),
    }
