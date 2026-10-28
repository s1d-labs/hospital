"""NMC Indian Medical Register from one machine (dev-vps-2), without the pool: NMC refuses GitHub/Azure runner IPs far more
than other clients (429 "this part of the register is busy"), so the full register is fetched here, one client, politely.

Every search page is saved exactly as NMC returned it (all fields), gzipped: OUT/raw/y<year>/p<page>.json.gz. Pages already
saved are skipped, so the job can be stopped and restarted at any time. Progress: OUT/progress.json; log on stdout.

Pages go out in shuffled order. NMC limits each client IP: past roughly 2.5-3 pages/s it answers 429 "this part of the
register is busy", and after a burst it keeps refusing for a while even at one request at a time (2026-10-28). Pace:
CONC_START requests in flight, one more after every STEP clean pages, halved on any refusal, after which nothing goes out for
REFUSED_WAIT seconds (all threads), at least MIN_GAP seconds between requests, never above CONC_MAX; the first refusal of a burst sets the ceiling. After a long run of refusals,
stop it and let it cool off rather than retrying. Years and their totals: data/nmc_year_counts.json.

    python nmc_box.py OUT_DIR            # fetch everything missing
    python nmc_box.py OUT_DIR --build    # also write OUT/doctors.jsonl.gz (one row per register id, all fields) + a summary
    python nmc_box.py OUT_DIR --part 1/2 # only slice 1 of 2 (another machine runs --part 0/2; merge the raw/ folders, then --build)
"""
import gzip
import json
import queue
import random
import sys
import threading
import time
from pathlib import Path

import requests

SITE = "https://nmc.org.in"
UA = "Mozilla/5.0 (compatible; s1d-labs research; +https://github.com/s1d-labs)"
PER_PAGE = 100
CONC_START, CONC_MAX, STEP, PROBE = 1, 32, 50, 500   # in flight: start, hard ceiling, clean pages per step up / per probe
REFUSED_WAIT = 30                                   # after a refusal, nothing goes out for this many seconds
MIN_GAP = 1.0                                       # seconds between the starts of two requests, whatever the concurrency
HERE = Path(__file__).parent


def url(year, page):
    return f"{SITE}/indian-medical-register/search?search_type=year&year={year}&page={page}&per_page={PER_PAGE}"


def plan():
    years = {int(y): n for y, n in json.loads((HERE / "data" / "nmc_year_counts.json").read_text()).items()}
    return [(y, p, min(PER_PAGE, n - (p - 1) * PER_PAGE)) for y, n in sorted(years.items()) for p in range(1, -(-n // PER_PAGE) + 1)]


def save(path, body):
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(body, ensure_ascii=False).encode()))
    tmp.rename(path)


class Slots:
    """How many requests may be in flight: +1 after STEP clean pages in a row, halved on a refusal (additive up, halve down).
    The first refusal of a burst sets the ceiling to 75% of the level it happened at; PROBE clean pages raise it by one."""

    def __init__(self, start, top):
        self.cond = threading.Condition()
        self.limit, self.top, self.busy, self.clean, self.since_refusal = start, top, 0, 0, 0
        self.pause_until = self.last_at = 0.0

    def __enter__(self):
        with self.cond:
            while True:                      # wait for a free slot, the end of a refusal pause, and the minimum gap
                now = time.time()
                wait = max(self.pause_until, self.last_at + MIN_GAP) - now
                if self.busy < self.limit and wait <= 0:
                    break
                self.cond.wait(timeout=max(0.05, wait) if wait > 0 else None)
            self.busy += 1
            self.last_at = time.time()

    def __exit__(self, *exc):
        with self.cond:
            self.busy -= 1
            self.cond.notify_all()

    def ok(self):
        with self.cond:
            self.clean += 1
            self.since_refusal += 1
            if self.since_refusal >= PROBE and self.top < CONC_MAX:      # keep probing upward, slowly, past the learned ceiling
                self.top, self.since_refusal = self.top + 1, 0
            if self.clean >= STEP and self.limit < self.top:
                self.limit, self.clean = self.limit + 1, 0
                self.cond.notify_all()

    def refused(self):
        with self.cond:
            if self.since_refusal:                                       # first refusal of a burst: learn the ceiling from it
                self.top = max(2, int(self.limit * 0.75))
            self.clean, self.since_refusal, self.limit = 0, 0, max(1, self.limit // 2)
            self.pause_until = time.time() + REFUSED_WAIT          # every thread waits, not just the refused one
            self.cond.notify_all()


def mine(year, page, part):
    """--part K/N: this machine fetches every page whose (year, page) falls in slice K of N, so N machines split the work."""
    if not part:
        return True
    k, n = part
    return (year * 100003 + page) % n == k


def fetch_all(out, part=None):
    raw = out / "raw"
    pages = [(y, p, want) for y, p, want in plan() if mine(y, p, part)]
    skip = set()                                  # OUT/skip.txt: "year page" lines another machine already saved
    if (out / "skip.txt").exists():
        skip = {tuple(map(int, line.split())) for line in (out / "skip.txt").read_text().split("\n") if line.strip()}
    todo = [(y, p, want) for y, p, want in pages if (y, p) not in skip and not (raw / f"y{y}" / f"p{p}.json.gz").exists()]
    total = len(pages)
    print(f"{total - len(todo)} of {total} pages already saved, {len(todo)} to fetch", flush=True)
    random.Random(7).shuffle(todo)          # spread requests over years: NMC limits concurrent queries on one part of the register
    work = queue.Queue()
    for t in todo:
        work.put(t)
    slots = Slots(CONC_START, CONC_MAX)
    lock = threading.Lock()
    stats, t0 = {"ok": 0, "refused": 0, "errors": 0, "short": 0}, time.time()
    local = threading.local()

    def session():
        if not hasattr(local, "s"):
            local.s = requests.Session()
            local.s.headers.update({"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        return local.s

    def report():
        el = time.time() - t0
        done = stats["ok"]
        prog = {**stats, "done": total - len(todo) + done, "total": total, "in_flight_limit": slots.limit, "ceiling": slots.top,
                "pages_per_s": round(done / el, 3), "eta_h": round((len(todo) - done) * el / max(1, done) / 3600, 1),
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        (out / "progress.json").write_text(json.dumps(prog))
        print(json.dumps(prog), flush=True)

    def one(year, page, want):
        while True:
            with slots:
                try:
                    r = session().get(url(year, page), timeout=120)
                    body = r.json() if r.status_code == 200 else None
                    err = False
                except (requests.RequestException, ValueError):
                    body, err = None, True
            if body and body.get("success"):
                slots.ok()
                return body
            slots.refused()                          # 429 "busy", a 200 without success, or a dropped connection: all threads pause
            with lock:
                stats["errors" if err else "refused"] += 1

    def worker():
        while True:
            try:
                year, page, want = work.get_nowait()
            except queue.Empty:
                return
            body = one(year, page, want)
            rows = len(body.get("data") or [])
            (raw / f"y{year}").mkdir(parents=True, exist_ok=True)
            save(raw / f"y{year}" / f"p{page}.json.gz", body)
            with lock:
                stats["ok"] += 1
                if rows < want:
                    stats["short"] += 1
                    print(f"short page y{year} p{page}: {rows} of {want} rows (register total now "
                          f"{body.get('pagination', {}).get('total')})", flush=True)
                if stats["ok"] % 100 == 0:
                    report()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(CONC_MAX)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    report()


def build(out):
    seen, rows, per_year = set(), 0, {}
    years = {int(y): n for y, n in json.loads((HERE / "data" / "nmc_year_counts.json").read_text()).items()}
    with gzip.open(out / "doctors.jsonl.gz", "wt", encoding="utf-8") as f:
        for d in sorted((out / "raw").glob("y*")):
            year = int(d.name[1:])
            for p in sorted(d.glob("p*.json.gz"), key=lambda x: int(x.name[1:].split(".")[0])):
                for row in json.loads(gzip.decompress(p.read_bytes())).get("data") or []:
                    rows += 1
                    if row.get("id") in seen:
                        continue
                    seen.add(row.get("id"))
                    per_year[year] = per_year.get(year, 0) + 1
                    f.write(json.dumps({**row, "query_year": year}, ensure_ascii=False) + "\n")
    gaps = {y: [n, per_year.get(y, 0)] for y, n in years.items() if per_year.get(y, 0) < n}
    summary = {"unique_ids": len(seen), "rows_read": rows, "expected": sum(years.values()), "years_short": gaps}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "years_short"}), f"{len(gaps)} years short", flush=True)


if __name__ == "__main__":
    out = Path(sys.argv[1]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    part = None
    if "--part" in sys.argv:
        k, n = sys.argv[sys.argv.index("--part") + 1].split("/")
        part = (int(k), int(n))
    fetch_all(out, part)
    if "--build" in sys.argv:
        build(out)
