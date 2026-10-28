"""The family's `fetch` task (see scrape.json): fetch whole small directory endpoints, one queue item per URL.

Item payload: {"url", "method" (GET/POST, default GET), "json" (POST body, optional)}. The response is stored as one record
(id = the item key): status, content type, and the body (decoded JSON when it parses, else text). For sources that are a
handful of requests in all (CGHS empanelled hospitals, e-Raktkosh blood centres, ABDM master lists), not paged crawls.
"""
import os
import time

import requests

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def parse(r):
    """The record for one response. Pure apart from reading the response object."""
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return {"status": r.status_code, "content_type": r.headers.get("content-type", ""), "url": r.url, "body": body}


def get(hub, session, item):
    p = item["payload"]
    t = time.time()
    try:
        r = session.request(p.get("method", "GET"), p["url"], json=p.get("json"), timeout=120,
                            headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
    except requests.RequestException as e:
        hub.metric("http_error")
        hub.error()
        hub.failure("fetch", item["key"], f"{type(e).__name__}: {e}"[:300], url=p["url"])
        return None
    hub.metric("n_http")
    hub.metric("t_http_s", time.time() - t)
    if r.status_code != 200:
        hub.metric(f"http_{r.status_code}")
        if r.status_code in (403, 429, 503):
            hub.block()
        hub.failure("fetch", item["key"], f"HTTP {r.status_code}", url=p["url"], body=r.text[:300])
        return None
    return parse(r)


def main():
    from scrape_hub_client import HubClient
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    s = requests.Session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break
            item = items[0]
            rec = get(hub, s, item)
            if rec is None:
                hub.complete([item["key"]], "failed", error="did not load")
            else:
                hub.record(item["key"], rec)
                hub.complete([item["key"]], "done", fetched=1)
            time.sleep(max(1.0, hub.settings.get("delay_ms", 0) / 1000))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    main()
