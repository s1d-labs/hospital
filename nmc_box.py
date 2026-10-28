"""NMC Indian Medical Register from one machine (dev-vps-2), without the pool: NMC refuses GitHub/Azure runner IPs far more
than other clients (429 "this part of the register is busy"), so the full register is fetched here, one client, politely.

Every search page is saved exactly as NMC returned it (all fields), gzipped: OUT/raw/y<year>/p<page>.json.gz. Pages already
saved are skipped, so the job can be stopped and restarted at any time. Progress: OUT/progress.json; log on stdout.

Pace: one request at a time, with a gap between requests that adapts: +50% (and a pause) on a refusal, -5% after 50 clean
answers in a row, between GAP_MIN and GAP_MAX seconds. Years and their totals: data/nmc_year_counts.json.

    python nmc_box.py OUT_DIR            # fetch everything missing
    python nmc_box.py OUT_DIR --build    # also write OUT/doctors.jsonl.gz (one row per register id, all fields) + a summary
"""
import gzip
import json
import sys
import time
from pathlib import Path

import requests

SITE = "https://nmc.org.in"
UA = "Mozilla/5.0 (compatible; s1d-labs research; +https://github.com/s1d-labs)"
PER_PAGE = 100
GAP_MIN, GAP_START, GAP_MAX = 0.3, 1.0, 60.0
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


def fetch_all(out):
    raw = out / "raw"
    todo = [(y, p, want) for y, p, want in plan() if not (raw / f"y{y}" / f"p{p}.json.gz").exists()]
    total = len(plan())
    print(f"{total - len(todo)} of {total} pages already saved, {len(todo)} to fetch", flush=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
    gap, clean, stats, t0 = GAP_START, 0, {"ok": 0, "refused": 0, "errors": 0, "short": 0}, time.time()
    for i, (year, page, want) in enumerate(todo):
        while True:
            time.sleep(gap)
            try:
                r = s.get(url(year, page), timeout=120)
                body = r.json() if r.status_code == 200 else None
            except (requests.RequestException, ValueError):
                stats["errors"] += 1
                gap = min(GAP_MAX, gap * 1.5)
                time.sleep(30)
                continue
            if body and body.get("success"):
                break
            stats["refused"] += 1                 # 429 "busy", or a 200 without success: slow down and try the same page again
            clean, gap = 0, min(GAP_MAX, gap * 1.5)
            time.sleep(min(120, 10 + gap * 2))
        rows = len(body.get("data") or [])
        if rows < want:
            stats["short"] += 1
            print(f"short page y{year} p{page}: {rows} of {want} rows (register total now {body.get('pagination', {}).get('total')})", flush=True)
        (raw / f"y{year}").mkdir(parents=True, exist_ok=True)
        save(raw / f"y{year}" / f"p{page}.json.gz", body)
        stats["ok"] += 1
        clean += 1
        if clean >= 50:
            clean, gap = 0, max(GAP_MIN, gap * 0.95)
        if stats["ok"] % 100 == 0 or i == len(todo) - 1:
            el = time.time() - t0
            left = (len(todo) - i - 1) * el / (i + 1)
            prog = {**stats, "done": total - len(todo) + i + 1, "total": total, "gap_s": round(gap, 2),
                    "pages_per_s": round((i + 1) / el, 3), "eta_h": round(left / 3600, 1), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            (out / "progress.json").write_text(json.dumps(prog))
            print(json.dumps(prog), flush=True)


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
    fetch_all(out)
    if "--build" in sys.argv:
        build(out)
