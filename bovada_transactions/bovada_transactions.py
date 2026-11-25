#!/usr/bin/env python3
"""Export Bovada account transactions to JSON and CSV.

How it works
  1. Opens Chromium with a saved profile, so you log in once and later runs reuse it.
  2. Waits for the Transactions page to make its own API request, then copies that
     request's URL and Authorization header.
  3. Pages through the same API from inside the page, following `scroll.next`
     until the API returns no next cursor. No scrolling, no "quiet for N seconds" guess.

Each page is appended to a .jsonl file as it arrives, so a run that is stopped
early keeps everything it already fetched.

Folder:  C:\Github\Sports-Betting\bovada_transactions

Usage (Anaconda Prompt, from any folder):
    python bovada_transactions.py                     # last 31 days (the site's widest range)
    python bovada_transactions.py --days 7
    python bovada_transactions.py --from-date 2026-09-18

Spyder: Run works as-is. Ctrl+C or the console's stop button ends the run after
the current page and still writes the files.
"""
import argparse, asyncio, csv, json, re, sys, threading, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
TRANSACTIONS_PAGE = "https://www.bovada.lv/account/transactions"
TX_RE = re.compile(r"/services/transaction-group/v1/profiles/[^/?]+/transactions", re.I)
BROWSER_OPTS = {"headless": False, "viewport": {"width": 1400, "height": 900}}
RETRY_DELAYS = (2, 5)  # seconds before the 2nd and 3rd attempt at a page
MAX_DAYS = 31  # the API answers 410 Gone for an older createdAtFrom
LEAD_COLUMNS = [
    "id", "timestamp", "productGroupId", "productGroupTimestamp",
    "aggregate.wallet.category", "aggregate.wallet.delta.total",
    "aggregate.wallet.balance.total", "aggregate.wallet.currency",
]
STOP = threading.Event()  # set by Ctrl+C when running inside Spyder

# Runs inside the page, so the request goes out exactly like the site's own.
FETCH_JS = """async ({url, headers, credentials}) => {
    try {
        const r = await fetch(url, {headers, credentials, cache: "no-store"});
        return {status: r.status, body: await r.text()};
    } catch (e) {
        return {status: 0, body: String(e)};
    }
}"""


class FetchError(Exception):
    pass


class Stopped(Exception):
    pass


def redact(text):
    """Bovada puts the session id in the URL path; keep it out of logs and files."""
    return re.sub(r"(/profiles/)[^/?\s]+", r"\1<session>", text)


def start_time(days=31, from_date=None, now=None):
    if from_date:
        return datetime.combine(from_date, datetime.min.time()).astimezone()  # local midnight
    return (now or datetime.now().astimezone()) - timedelta(days=days)


def api_time(dt):
    """createdAtFrom as the site sends it: UTC, milliseconds, trailing Z."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def page_url(template_url, created_from, scroll="", size=None):
    parts = urlsplit(template_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["createdAtFrom"] = created_from
    query["scroll"] = scroll
    if size:
        query["size"] = str(size)
    return urlunsplit(parts._replace(query=urlencode(query)))


async def fetch_with_retry(fetch_once, url):
    """fetch_once(url) -> (status, body). Retries network errors, 429 and 5xx; nothing else."""
    attempts = 1 + len(RETRY_DELAYS)
    for attempt in range(1, attempts + 1):
        status, body = await fetch_once(url)
        what = f"HTTP {status}" if status else "network error"
        if status == 200:
            try:
                data = json.loads(body)
            except ValueError:
                raise FetchError(f"response was not JSON: {body[:200]!r}")
            if not isinstance(data, dict):
                raise FetchError(f"unexpected response shape: {type(data).__name__}")
            return data
        if status in (401, 403):
            raise FetchError(f"{what}: session expired or not logged in. Log in again and rerun.")
        if status == 410:
            raise FetchError(f"{what}: Bovada refused the date range (it only serves the last {MAX_DAYS} days).")
        if status not in (0, 429) and status < 500:
            raise FetchError(f"{what}: {redact(body[:300])}")
        if attempt < attempts:
            delay = RETRY_DELAYS[attempt - 1]
            print(f"  {what}, retrying in {delay}s...", flush=True)
            await asyncio.sleep(delay)
    raise FetchError(f"{what} after {attempts} attempts: {redact(body[:300])}")


async def collect_pages(fetch_page, url_for, on_page, max_pages=1000, delay=0.5):
    """Fetch the first page, then follow scroll.next until it is empty.
    Returns (pages_fetched, why_it_stopped)."""
    cursor, seen = "", set()
    for n in range(1, max_pages + 1):
        if STOP.is_set():
            return n - 1, "stopped by user"
        data = await fetch_page(url_for(cursor))
        on_page(n, data)
        cursor = (data.get("scroll") or {}).get("next") or ""
        if not cursor:
            return n, "reached the last page"
        if cursor in seen:
            return n, "API repeated a cursor; stopped to avoid looping"
        seen.add(cursor)
        await asyncio.sleep(delay)
    return max_pages, f"hit --max-pages {max_pages}"


def flatten_dict(d, prefix=""):
    out = {}
    if not isinstance(d, dict):
        return {"value": json.dumps(d, ensure_ascii=False)}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False)
        else:
            out[key] = v
    return out


def fingerprint(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def merge_pages(pages):
    """One entry per transaction id (first seen wins), plus merged translations."""
    items, translations = {}, {}
    for data in pages:
        for item in data.get("items") or []:
            if isinstance(item, dict):
                items.setdefault(item.get("id") or fingerprint(item), item)
        for key, value in (data.get("translations") or {}).items():
            if isinstance(value, dict) and isinstance(translations.get(key, {}), dict):
                translations.setdefault(key, {}).update(value)
            else:
                translations[key] = value
    summary = pages[0].get("summary") if pages else None
    return list(items.values()), translations, summary


def write_csv(path, items):
    rows = [flatten_dict(x) for x in items]
    keys = {k for row in rows for k in row}
    cols = [c for c in LEAD_COLUMNS if c in keys] + sorted(keys - set(LEAD_COLUMNS))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def describe_time(value):
    if isinstance(value, (int, float)):  # epoch milliseconds
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M")
    return str(value)


async def wait_for_transactions_request(context, timeout_s):
    found = []

    def on_request(request):
        if TX_RE.search(request.url):
            found.append(request)

    context.on("request", on_request)
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(TRANSACTIONS_PAGE, wait_until="domcontentloaded")
    print("\nWaiting for the Transactions page to load its data.\n"
          "If the browser asks you to log in, log in there. If you don't end up on\n"
          "Account -> Transactions afterwards, open it. Capture starts by itself.\n", flush=True)
    deadline = time.monotonic() + timeout_s
    while not found:
        if STOP.is_set():
            raise Stopped()
        if not context.pages:
            raise FetchError("the browser was closed before the transactions page loaded")
        if time.monotonic() > deadline:
            raise FetchError(f"no transactions request within {timeout_s}s. "
                             "Log in, open Account -> Transactions, and run again.")
        await asyncio.sleep(0.5)
    context.remove_listener("request", on_request)
    return found[0]


async def main(args):
    from playwright.async_api import Error as PlaywrightError, async_playwright

    out_dir = HERE / "bovada_export"
    out_dir.mkdir(exist_ok=True)
    start = start_time(args.days, args.from_date)
    earliest = datetime.now().astimezone() - timedelta(days=MAX_DAYS) + timedelta(minutes=1)
    if start < earliest:
        print(f"Bovada only returns the last {MAX_DAYS} days, so starting from "
              f"{earliest:%Y-%m-%d %H:%M} instead of {start:%Y-%m-%d %H:%M}.")
        start = earliest
    created_from = api_time(start)
    stem = f"bovada_transactions_{start:%Y-%m-%d}_to_{datetime.now():%Y-%m-%d}"
    pages_path = out_dir / f"{stem}_pages.jsonl"
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    run_path = out_dir / f"{stem}_run.json"

    pages = []
    run_log = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
               "created_at_from": created_from, "pages": []}

    def on_page(n, data):
        pages.append(data)
        with pages_path.open("w" if n == 1 else "a", encoding="utf-8") as f:
            f.write(json.dumps({"page": n, "data": data}, ensure_ascii=False, default=str) + "\n")
        count = len(data.get("items") or [])
        has_next = bool((data.get("scroll") or {}).get("next"))
        run_log["pages"].append({"page": n, "items": count, "has_next": has_next})
        total = sum(p["items"] for p in run_log["pages"])
        print(f"Page {n}: {count} transactions (running total {total})", flush=True)

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                str(HERE / "bovada_browser_profile"), **BROWSER_OPTS)
        except PlaywrightError as e:
            print("Could not start Chromium with bovada_browser_profile. If a browser window\n"
                  "from an earlier run is still open, close it (in Spyder, restart the kernel)\n"
                  "and try again.\n" + str(e).splitlines()[0])
            return

        reason = "not started"
        try:
            request = await wait_for_transactions_request(context, args.login_timeout)
            headers = await request.all_headers()
            forward = {k: v for k, v in headers.items()
                       if k in ("authorization", "accept") or k.startswith("x-")}
            if "authorization" not in forward:
                print("Warning: the site's request had no Authorization header; "
                      "the export requests may be rejected.")
            credentials = "include" if "cookie" in headers else "same-origin"
            try:
                page = request.frame.page
            except PlaywrightError:
                page = context.pages[0]
            run_log["template_url"] = redact(request.url)

            async def fetch_once(url):
                # The site sometimes reloads or redirects right after loading, which kills an
                # in-flight evaluate. Wait for the new page to load and send the request again.
                for attempt in range(1, 4):
                    try:
                        result = await page.evaluate(
                            FETCH_JS, {"url": url, "headers": forward, "credentials": credentials})
                        return result["status"], result["body"]
                    except PlaywrightError as e:
                        if attempt == 3 or page.is_closed() or "context was destroyed" not in str(e):
                            raise
                        print("  The page navigated; waiting for it to settle...", flush=True)
                        await page.wait_for_load_state("load")
                        await asyncio.sleep(1)

            print(f"Capturing transactions since {start:%Y-%m-%d %H:%M} "
                  "(don't navigate in the browser until it finishes)...\n", flush=True)
            _, reason = await collect_pages(
                lambda url: fetch_with_retry(fetch_once, url),
                lambda cursor: page_url(request.url, created_from, cursor, args.size),
                on_page, args.max_pages, args.delay)
        except Stopped:
            reason = "stopped by user"
        except FetchError as e:
            reason = f"error: {e}"
        except PlaywrightError as e:  # e.g. the browser window was closed mid-run
            reason = f"browser error: {redact(str(e).splitlines()[0])}"
        except asyncio.CancelledError:  # Ctrl+C in a terminal
            reason = "stopped by user"
            raise
        finally:
            run_log["stopped_because"] = reason
            run_log["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            run_path.write_text(json.dumps(run_log, indent=2), encoding="utf-8")
            items = []
            if pages:
                items, translations, summary = merge_pages(pages)
                json_path.write_text(json.dumps({
                    "created_at_from": created_from,
                    "page_count": len(pages),
                    "transaction_count": len(items),
                    "summary": summary,
                    "translations": translations,
                    "transactions": items,
                }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
                write_csv(csv_path, items)

            print("\n==============================")
            print("Stopped because:", reason)
            print("API pages:", len(pages))
            print("Unique transactions:", len(items))
            stamps = [i["timestamp"] for i in items if i.get("timestamp") is not None]
            if stamps:
                print("Oldest:", describe_time(min(stamps, key=str)),
                      " Newest:", describe_time(max(stamps, key=str)))
            if pages:
                print("CSV: ", csv_path)
                print("JSON:", json_path)
            print("Run log:", run_path)
            try:
                await context.close()
            except PlaywrightError:
                pass


def _run_in_new_loop(args):
    # Playwright starts a driver subprocess, which on Windows needs a Proactor loop.
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        loop.run_until_complete(main(args))
    finally:
        loop.close()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Export Bovada account transactions to JSON and CSV.")
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--days", type=int, default=31,
                      help="days back to export (default 31, the widest range the site offers)")
    when.add_argument("--from-date", type=date.fromisoformat,
                      help="export from this local date, YYYY-MM-DD")
    ap.add_argument("--size", type=int,
                    help="transactions per API page (default: what the site uses, 30)")
    ap.add_argument("--max-pages", type=int, default=1000, help="safety cap (default 1000)")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="seconds between page requests (default 0.5)")
    ap.add_argument("--login-timeout", type=int, default=600,
                    help="seconds to wait for you to log in (default 600)")
    return ap.parse_args(argv)


def run(argv=None):
    args = parse_args(argv)
    STOP.clear()
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # plain terminal: no loop running yet
        try:
            asyncio.run(main(args))
        except KeyboardInterrupt:
            print("\nStopped.")
        return
    # Spyder and Jupyter already run an event loop on this thread, so run ours on another.
    worker = threading.Thread(target=_run_in_new_loop, args=(args,), daemon=True)
    worker.start()
    while worker.is_alive():
        try:
            worker.join(0.5)
        except KeyboardInterrupt:
            print("\nStopping after the current page...", flush=True)
            STOP.set()


if __name__ == "__main__":
    run()
