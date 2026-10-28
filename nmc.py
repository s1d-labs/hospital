"""The family's `nmc` task (see scrape.json): NMC's Indian Medical Register (nmc.org.in), every registered doctor.

The register has a public JSON search (`/indian-medical-register/search`, 100 rows a page at most). Queue items are one
registration year and a block of pages (`payload`: year, first, last, per_page, expected), so each query stays small: the
site sheds load on big result sets with a 429 ("this part of the register is busy ... narrow your search with a year").

Speed comes from the hub on every call (`hub.settings`): `threads` concurrent requests per process, `rps_per_worker` requests
per second for this process (shared by its threads), `delay_ms` as a floor between one thread's requests, `paused`.

Only professional fields are kept: home address, date of birth and father's name are dropped before anything is stored.
Try it without the hub: python nmc.py --local YEAR [PAGE]
"""
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
SITE = os.environ.get("SITE", "https://nmc.org.in")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "Mozilla/5.0 (compatible; s1d-labs scraper; +https://github.com/s1d-labs)"
KEEP = ("name", "registration_no", "registration_date", "uprn_no", "state_medical_council", "state_code", "year_of_info",
        "qualification", "qualification_year", "university", "additional_qualifications", "removed_status")
DROPPED = ("dob", "permanent_address", "father_name")      # personal, not professional: never stored


def search_url(year, page, per_page=100):
    return f"{SITE}/indian-medical-register/search?search_type=year&year={year}&page={page}&per_page={per_page}"


def clean(value):
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in DROPPED}
    return value


def parse(body, year):
    """[(record_id, data)] for one search page (the decoded JSON). Pure: tested on a saved page in tests/."""
    out = []
    for row in body.get("data") or []:
        if row.get("id") is None:
            continue
        data = {k: clean(row.get(k)) for k in KEEP}
        data["query_year"] = int(year)
        out.append((str(row["id"]), data))
    return out


class Pace:
    """Requests per second for this process, shared by its threads; the rate is re-read from hub.settings."""

    def __init__(self):
        self.lock = threading.Lock()
        self.next_at = time.time()

    def wait(self, rps):
        gap = 1.0 / max(0.05, float(rps))
        with self.lock:
            now = time.time()
            at = max(now, self.next_at)
            self.next_at = at + gap
        if at > now:
            time.sleep(at - now)


def fetch(hub, session, url, pace, attempts=8):
    """The decoded JSON of one page, or None. Retries the site's 429 'busy' answers with a growing wait."""
    for n in range(attempts):
        if time.time() > DEADLINE:
            return None
        pace.wait(hub.settings.get("rps_per_worker", 2))
        t = time.time()
        try:
            r = session.get(url, timeout=90, headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        except requests.RequestException:
            hub.metric("http_error")
            hub.error()
            time.sleep(min(30, 3 * (n + 1)))
            continue
        hub.metric("n_http")
        hub.metric("t_http_s", time.time() - t)
        if r.status_code == 200:
            try:
                body = r.json()
            except ValueError:
                hub.metric("bad_json")
                body = None
            if body and body.get("success"):
                return body
            hub.metric("not_success")
        else:
            hub.metric(f"http_{r.status_code}")
            if r.status_code in (403, 429, 503):
                hub.block()
        time.sleep(min(30, 3 * (n + 1)))
        delay = hub.settings.get("delay_ms", 0) / 1000
        if delay:
            time.sleep(delay)
    return None


def store(hub, rows):
    """All of a page's records in one batch (the client's own buffer flushes every 25 records)."""
    with hub.lock:
        hub.pending.extend({"record_id": rid, "data": data} for rid, data in rows)
    hub.flush()


def page_job(hub, session_for, pace, year, page, per_page, want):
    body = fetch(hub, session_for(), search_url(year, page, per_page), pace)
    if body is None:
        return None
    rows = parse(body, year)
    if want and len(rows) < want:
        hub.metric("short_page")
        hub.failure("short_page", f"{year}-{page}", f"{len(rows)} of {want} rows", year=year, page=page)
    store(hub, rows)
    time.sleep(hub.settings.get("delay_ms", 0) / 1000)
    return len(rows)


def run_item(hub, pool, session_for, pace, item):
    p = item["payload"]
    year, per_page, total = p["year"], p.get("per_page", 100), p["total"]
    pages = range(p["first"], p["last"] + 1)
    want = {pg: max(0, min(per_page, total - (pg - 1) * per_page)) for pg in pages}
    got = list(pool.map(lambda pg: page_job(hub, session_for, pace, year, pg, per_page, want[pg]), pages))
    if any(g is None for g in got):
        return None
    return sum(got)


def local(year, page):
    class LocalHub:
        settings = {"rps_per_worker": 0.5, "delay_ms": 0}
        counts = {}

        def metric(self, name, value=1):
            self.counts[name] = self.counts.get(name, 0) + value

        def error(self, n=1):
            self.metric("errors", n)

        def block(self, n=1):
            self.metric("blocked", n)

    hub = LocalHub()
    body = fetch(hub, requests.Session(), search_url(year, page), Pace(), attempts=3)
    rows = parse(body, year) if body else []
    for rid, data in rows[:3]:
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))
    print(f"{len(rows)} records, pagination {(body or {}).get('pagination')}, counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    signal.signal(signal.SIGINT, signal.default_int_handler)
    local_sessions = threading.local()

    def session_for():
        if not hasattr(local_sessions, "s"):
            local_sessions.s = requests.Session()
        return local_sessions.s

    pace = Pace()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left: exit, the worker asks the hub for more
            item = items[0]
            threads = max(1, min(32, int(hub.settings.get("threads", 4))))
            with ThreadPoolExecutor(threads) as pool:
                n = run_item(hub, pool, session_for, pace, item)
            if n is None:
                hub.complete([item["key"]], "failed", error="a page did not load")
            else:
                hub.complete([item["key"]], "done", fetched=n)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(int(sys.argv[2]) if len(sys.argv) > 2 else 2025, int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    else:
        main()
