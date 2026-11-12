"""Bovada capture layer: golden parser replays and transport fault injection.

No test here touches the network. Fixtures are archived raw Bovada responses
(sha256-verified against the archive manifest) plus live captures from
2026-11-11 that contain live, suspended and one-sided markets.
"""

import copy
import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from gambling.bovada import FetchConfig, Outcome, RetryPolicy, classify, fetch_board, parse_feed, replay_run
from gambling.bovada.capture import CaptureStore, load_attempts
from gambling.bovada.endpoints import event_variants, league_variants
from gambling.bovada.parse import NOT_OFFERED, NOT_PREGAME, OFFERED, SUSPENDED, parse_american
from gambling.bovada.transport import HttpResponse
from gambling.config import default_paths
from gambling.history import connect_frozen

FIXTURES = Path(__file__).parent / "fixtures" / "bovada"
SERVER_DATE = datetime(2026, 11, 11, 18, 55, 0, tzinfo=timezone.utc)  # before any fixture tip-off


def fixture_bytes(name):
    data = (FIXTURES / name).read_bytes()
    return gzip.decompress(data) if name.endswith(".gz") else data


def fixture_json(name):
    return json.loads(fixture_bytes(name))


def response(url, status=200, body=b"", *, age=60, date=SERVER_DATE, headers=None, error=None):
    hdrs = {"Content-Type": "application/json"}
    if date is not None:
        hdrs["Date"] = format_datetime(date, usegmt=True)
    if age is not None:
        hdrs["Age"] = str(age)
    hdrs.update(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    return HttpResponse(url, status, hdrs, body, SERVER_DATE, SERVER_DATE, error)


class FakeTransport:
    """url -> list of responses (served in order; the last one repeats)."""

    def __init__(self, script=None, default=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.default = default
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        queue = self.script.get(url)
        if queue:
            item = queue.pop(0) if len(queue) > 1 else queue[0]
        elif self.default is not None:
            item = self.default
        else:
            item = response(url, 404, b"{}")
        return item(url) if callable(item) else HttpResponse(url, item.status, item.headers, item.body,
                                                             item.requested_utc, item.received_utc, item.error)


def nba_url(i):
    return league_variants("NBA")[i].url


def board_with(events):
    payload = copy.deepcopy(fixture_json("live_20261111_nba_coupon_prematch.json.gz"))
    payload[0]["events"] = events
    return payload


def nba_events():
    return copy.deepcopy(fixture_json("live_20261111_nba_coupon_prematch.json.gz")[0]["events"])


FAST = RetryPolicy(max_attempts=3, base_delay=1, polite_delay=0)


# --------------------------------------------------------------------------- parser


class GoldenParser(unittest.TestCase):
    def test_nfl_fixture_is_archived_payload(self):
        meta = json.loads((FIXTURES / "nfl_20261110_072712cst_feed_metadata.json").read_text())
        digest = hashlib.sha256(fixture_bytes("nfl_20261110_072712cst_raw.json.gz")).hexdigest()
        self.assertEqual(digest, meta["payload_sha256"])

    def test_nfl_matches_archived_quote_sheet_including_ids(self):
        events = {e.event_id: e for e in parse_feed(fixture_json("nfl_20261110_072712cst_raw.json.gz"), "NFL")}
        with (FIXTURES / "nfl_20261110_072712cst_quotes.csv").open(newline="") as stream:
            golden = list(csv.DictReader(stream))
        self.assertEqual(len(golden), 12)
        for row in golden:
            e = events[row["event_id"]]
            self.assertTrue(e.complete, row["event_id"])
            self.assertEqual((e.away, e.home), (row["away_name"], row["home_name"]))
            self.assertEqual(datetime.fromisoformat(e.start_utc), datetime.fromisoformat(row["start_utc"]))
            checks = [("Spread", "Away", "away_spread", "away_spread_odds", "2W-HCAP", "A"),
                      ("Spread", "Home", "home_spread", "home_spread_odds", "2W-HCAP", "H"),
                      ("Moneyline", "Away", None, "away_moneyline", "2W-12", "A"),
                      ("Moneyline", "Home", None, "home_moneyline", "2W-12", "H"),
                      ("Total", "Over", "total", "over_odds", "2W-OU", "O"),
                      ("Total", "Under", "total", "under_odds", "2W-OU", "U")]
            for market, side, line_col, odds_col, key, code in checks:
                q = e.quote(market, side)
                self.assertEqual(q.quote_status, OFFERED)
                self.assertEqual(q.odds_american, int(row[odds_col]), (row["event_id"], market, side))
                if line_col:
                    self.assertEqual(q.line, float(row[line_col]))
                self.assertEqual(q.market_id, row[f"{key}_market_id"])
                self.assertEqual(q.outcome_id, row[f"{key}_{code}_outcome_id"])
                self.assertEqual(q.price_id, row[f"{key}_{code}_price_id"])

    def test_nfl_events_without_main_lines_are_explicit_not_dropped(self):
        events = {e.event_id: e for e in parse_feed(fixture_json("nfl_20261110_072712cst_raw.json.gz"), "NFL")}
        skipped = json.loads((FIXTURES / "nfl_20261110_072712cst_skipped_events.json").read_text())
        self.assertEqual(len(events), 14)
        for item in skipped:
            e = events[item["event_id"]]
            self.assertFalse(e.has_main_lines)
            self.assertEqual(len(e.quotes), 6)
            self.assertTrue(all(q.quote_status == NOT_OFFERED for q in e.quotes))

    def test_nba_matches_rolling_history_database(self):
        events = {e.event_id: e for e in parse_feed(fixture_json("nba_20261110_181127z_api_response.json.gz"), "NBA")}
        with connect_frozen(default_paths()) as con:
            rows = con.execute("SELECT event_id, market, side, line, odds_american FROM market_quotes "
                               "WHERE batch_id='NBA_20261110_181127Z_R4_R3'").fetchall()
        self.assertEqual(len(rows), 36)
        for row in rows:
            e = events[row["event_id"]]
            if row["market"] == "Total":
                q = e.quote("Total", row["side"])
            else:
                side = "Away" if row["side"] == e.away else "Home"
                self.assertEqual(row["side"], e.away if side == "Away" else e.home)
                q = e.quote(row["market"], side)
            self.assertEqual(q.quote_status, OFFERED)
            self.assertEqual(q.odds_american, int(row["odds_american"]))
            self.assertEqual(q.line, row["line"])

    def test_live_suspended_and_one_sided_markets(self):
        events = parse_feed(fixture_json("live_20261111_ncaabb_v2_league.json.gz"), "NCAABB")
        statuses = {q.quote_status for e in events for q in e.quotes}
        self.assertTrue({OFFERED, SUSPENDED, NOT_OFFERED, NOT_PREGAME} <= statuses)
        for e in events:
            if e.live:
                self.assertTrue(all(q.quote_status == NOT_PREGAME for q in e.quotes), e.description)
            for q in e.quotes:
                if q.market_id:  # never a first-half or live line in place of the full game
                    self.assertIn(q.period, ("Game", "Live Game"))
                if q.quote_status == SUSPENDED:
                    self.assertFalse(q.usable)
        one_sided = [q for e in events for q in e.quotes if q.status_detail.startswith("no ")]
        self.assertTrue(one_sided)

    def test_event_marked_not_pregame_once_started(self):
        raw = nba_events()[0]
        start = datetime.fromtimestamp(raw["startTime"] / 1000, timezone.utc)
        before = parse_feed(board_with([raw]), "NBA", as_of=start - timedelta(hours=1))[0]
        after = parse_feed(board_with([raw]), "NBA", as_of=start)[0]
        self.assertTrue(before.complete)
        self.assertTrue(all(q.quote_status == NOT_PREGAME for q in after.quotes))

    def test_placeholder_special_is_not_a_physical_game(self):
        raw = nba_events()[0]
        raw["description"] = "Away Goals @ Home Goals"
        raw["competitors"][0]["name"], raw["competitors"][1]["name"] = "Home Goals", "Away Goals"
        event = parse_feed(board_with([raw]), "NHL")[0]
        self.assertFalse(event.physical_game)
        self.assertTrue(all(q.quote_status == "SPECIAL_NON_GAME" for q in event.quotes))
        self.assertFalse(event.has_main_lines)
        real = parse_feed(board_with(nba_events()[:1]), "NBA")[0]
        self.assertTrue(real.physical_game)

    def test_parse_american(self):
        self.assertEqual(parse_american("EVEN"), 100)
        self.assertEqual(parse_american("+105"), 105)
        self.assertEqual(parse_american("-110"), -110)
        self.assertIsNone(parse_american("50"))
        self.assertIsNone(parse_american("n/a"))
        self.assertIsNone(parse_american(None))


# --------------------------------------------------------------------------- classification


class Classification(unittest.TestCase):
    URL = "https://example.invalid/feed"

    def test_cached_empty_object_days_old_is_stale(self):
        verdict = classify(response(self.URL, body=b"{}", age=152140), 900)
        self.assertEqual(verdict.outcome, Outcome.STALE)
        self.assertFalse(verdict.outcome.retryable)

    def test_fresh_empty_object_is_empty(self):
        self.assertEqual(classify(response(self.URL, body=b"{}", age=5), 900).outcome, Outcome.EMPTY)
        self.assertEqual(classify(response(self.URL, body=b"[]", age=5), 900).outcome, Outcome.EMPTY)
        self.assertEqual(classify(response(self.URL, body=b"", age=5), 900).outcome, Outcome.EMPTY)

    def test_failure_classes(self):
        cases = [
            (response(self.URL, 403, b"<html>Access denied</html>"), Outcome.BLOCKED),
            (response(self.URL, 200, b"<!DOCTYPE html><html>captcha</html>"), Outcome.NON_JSON),
            (response(self.URL, 200, b'[{"path": [], "events": [{"id"'), Outcome.TRUNCATED),
            (response(self.URL, 200, b'{"error": "x"}'), Outcome.MALFORMED),
            (response(self.URL, 503, b"busy"), Outcome.HTTP_5XX),
            (response(self.URL, 404, b"{}"), Outcome.NOT_FOUND),
            (response(self.URL, None, b"", error="timeout"), Outcome.NETWORK_ERROR),
        ]
        for resp, expected in cases:
            self.assertEqual(classify(resp, 900).outcome, expected, expected)

    def test_rate_limit_reads_retry_after(self):
        verdict = classify(response(self.URL, 429, b"", headers={"Retry-After": "7"}), 900)
        self.assertEqual(verdict.outcome, Outcome.RATE_LIMITED)
        self.assertEqual(verdict.retry_after_seconds, 7)

    def test_snapshot_time_is_server_date_minus_cdn_age(self):
        verdict = classify(response(self.URL, body=board_with(nba_events()), age=300), 900)
        self.assertEqual(verdict.outcome, Outcome.OK)
        self.assertEqual(verdict.event_count, 10)
        self.assertEqual(verdict.snapshot_as_of_utc, datetime(2026, 11, 11, 18, 50, 0, tzinfo=timezone.utc))


# --------------------------------------------------------------------------- fetch orchestration


class FetchOrchestration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_fetch(self, transport, sports=("NBA",), **config):
        config.setdefault("policy", FAST)
        return fetch_board(list(sports), self.root, config=FetchConfig(**config), transport=transport,
                           sleep=self.sleeps.append, rand=lambda: 0.5)

    def test_stale_cached_variants_fall_through_to_fresh_one(self):
        stale = response("", body=b"{}", age=349825)
        transport = FakeTransport({nba_url(0): [stale], nba_url(1): [stale],
                                   nba_url(2): [response("", body=board_with(nba_events()), age=40)],
                                   nba_url(3): [stale]})
        run = self.run_fetch(transport)
        nba = run.sports["NBA"]
        self.assertEqual(nba.status, "OK")
        self.assertEqual(len(nba.events), 10)
        self.assertTrue(all(e.complete for e in nba.events))
        self.assertEqual({p["variant"] for p in nba.provenance.values()}, {"v2_league"})
        # A cached answer is not retried on the same URL: one request per variant.
        self.assertEqual([transport.calls.count(nba_url(i)) for i in range(4)], [1, 1, 1, 1])

    def test_transient_errors_are_retried_with_backoff(self):
        ok = response("", body=board_with(nba_events()), age=10)
        transport = FakeTransport({nba_url(0): [response("", None, error="timed out"),
                                                response("", 503, b"busy"), ok]}, default=ok)
        run = self.run_fetch(transport, all_variants=False)
        attempts = run.sports["NBA"].attempts
        self.assertEqual([a["outcome"] for a in attempts], ["NETWORK_ERROR", "HTTP_5XX", "OK"])
        self.assertEqual([a["attempt"] for a in attempts], [1, 2, 3])
        self.assertEqual(self.sleeps, [1.0, 2.0])

    def test_rate_limit_honours_retry_after(self):
        ok = response("", body=board_with(nba_events()), age=10)
        transport = FakeTransport({nba_url(0): [response("", 429, b"", headers={"Retry-After": "7"}), ok]})
        self.run_fetch(transport, all_variants=False)
        self.assertIn(7.0, self.sleeps)

    def test_everything_failing_is_reported_not_hidden(self):
        transport = FakeTransport(default=response("", 503, b"busy"))
        run = self.run_fetch(transport)
        self.assertEqual(run.sports["NBA"].status, "FAILED")
        self.assertFalse(run.ok)
        self.assertEqual(len(transport.calls), 4 * FAST.max_attempts)
        manifest = json.loads((run.run_dir / "manifest.json").read_text())
        self.assertFalse(manifest["all_sports_ok"])
        self.assertEqual(manifest["sports"]["NBA"]["attempt_outcomes"], {"HTTP_5XX": 12})

    def test_blocked_and_no_events_verdicts(self):
        blocked = self.run_fetch(FakeTransport(default=response("", 403, b"<html>denied</html>")))
        self.assertEqual(blocked.sports["NBA"].status, "BLOCKED")
        empty = self.run_fetch(FakeTransport(default=response("", body=b"[]", age=5)))
        self.assertEqual(empty.sports["NBA"].status, "NO_EVENTS")
        self.assertTrue(empty.ok)

    def test_variants_are_unioned_and_fresher_copy_wins(self):
        events = nba_events()
        older = copy.deepcopy(events[:6])
        newer = copy.deepcopy(events[4:])
        newer[0]["displayGroups"][0]["markets"][0]["outcomes"][0]["price"]["american"] = "+333"
        transport = FakeTransport({nba_url(0): [response("", body=board_with(older), age=500)],
                                   nba_url(1): [response("", body=board_with(newer), age=20)]},
                                  default=response("", body=b"{}", age=99999))
        nba = self.run_fetch(transport).sports["NBA"]
        self.assertEqual(len(nba.events), 10)
        overlap = newer[0]["id"]
        self.assertEqual(nba.provenance[overlap]["variant"], "coupon_prematch_nolimit")
        changed = next(e for e in nba.events if e.event_id == overlap)
        self.assertIn(333, [q.odds_american for q in changed.quotes])
        self.assertEqual(nba.provenance[events[0]["id"]]["variant"], "coupon_prematch")

    def test_incomplete_event_recovered_from_event_page(self):
        events = nba_events()
        target = copy.deepcopy(events[0])
        stripped = copy.deepcopy(events)
        stripped[0]["displayGroups"] = []
        page = event_variants(target["link"])[0].url
        transport = FakeTransport({nba_url(0): [response("", body=board_with(stripped), age=30)],
                                   page: [response("", body=board_with([target]), age=5)]},
                                  default=response("", body=b"{}", age=99999))
        nba = self.run_fetch(transport).sports["NBA"]
        self.assertEqual(nba.recovered, [target["id"]])
        self.assertEqual(nba.unrecovered, [])
        self.assertEqual(nba.provenance[target["id"]]["purpose"], f"event_recovery:{target['id']}")
        self.assertTrue(all(e.complete for e in nba.events))

    def test_unrecoverable_event_stays_explicitly_incomplete(self):
        stripped = nba_events()
        stripped[0]["displayGroups"] = []
        transport = FakeTransport({nba_url(0): [response("", body=board_with(stripped), age=30)]},
                                  default=response("", body=b"{}", age=99999))
        nba = self.run_fetch(transport).sports["NBA"]
        self.assertEqual(nba.unrecovered, [stripped[0]["id"]])
        event = next(e for e in nba.events if e.event_id == stripped[0]["id"])
        self.assertTrue(all(q.quote_status == NOT_OFFERED for q in event.quotes))

    def test_every_attempt_is_captured_with_checksums_and_provenance(self):
        stale = response("", body=b"{}", age=349825)
        transport = FakeTransport({nba_url(0): [stale],
                                   nba_url(1): [response("", body=board_with(nba_events()), age=300)]},
                                  default=response("", 503, b"busy"))
        run = self.run_fetch(transport)
        captured = load_attempts(run.run_dir)
        self.assertEqual(len(captured), len(transport.calls))
        self.assertEqual(captured[0][0]["outcome"], "STALE")
        self.assertEqual(captured[0][1], b"{}")
        self.assertEqual(captured[0][0]["response_headers"]["Age"], "349825")
        prov = next(iter(run.sports["NBA"].provenance.values()))
        self.assertEqual(prov["snapshot_as_of_utc"], "2026-11-11T18:50:00+00:00")
        with (run.run_dir / "quotes.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 60)
        self.assertTrue(all(r["source_attempt_id"] for r in rows))

    def test_capture_store_is_append_only(self):
        store = CaptureStore(self.root, "RUN1")
        resp = response("u", body=b"[]")
        store.record("x", resp, classify(resp, 900), sport="NBA", variant="v", attempt=1, purpose="p")
        with self.assertRaises(FileExistsError):
            CaptureStore(self.root, "RUN1")
        with self.assertRaises(FileExistsError):
            store.write_document("doc.json", {})
            store.write_document("doc.json", {})
        (store.run_dir / "0001_x.body").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            load_attempts(store.run_dir)

    def test_replay_reproduces_board_offline(self):
        stripped = nba_events()
        stripped[1]["displayGroups"] = []
        transport = FakeTransport({nba_url(0): [response("", None, error="reset"),
                                                response("", body=board_with(stripped), age=30)]},
                                  default=response("", body=b"{}", age=99999))
        run = self.run_fetch(transport)
        replayed = replay_run(run.run_dir)
        self.assertEqual(replayed.board(), run.board())
        self.assertEqual(replayed.manifest()["sports"], run.manifest()["sports"])


if __name__ == "__main__":
    unittest.main()
