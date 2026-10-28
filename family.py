"""What this family scrapes: sources for HospitalDoor (hospitals and the people who work in them).

FAMILY must equal the repo name (s1d-labs/<FAMILY>). Each project is one queue of work on one site; `target` is the host it hits.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
FAMILY = json.loads((HERE / "scrape.json").read_text())["family"]

# NMC Indian Medical Register: registrations per year (search_type=year, counted 2026-10-28), 100 rows a page, 10 pages an item
NMC_YEARS = {int(y): n for y, n in json.loads((HERE / "data" / "nmc_year_counts.json").read_text()).items()}
NMC_PER_PAGE, NMC_PAGES_PER_ITEM = 100, 10


def nmc_items():
    items = []
    for year, total in sorted(NMC_YEARS.items()):
        pages = -(-total // NMC_PER_PAGE)
        for first in range(1, pages + 1, NMC_PAGES_PER_ITEM):
            last = min(pages, first + NMC_PAGES_PER_ITEM - 1)
            expected = min(total, last * NMC_PER_PAGE) - (first - 1) * NMC_PER_PAGE
            items.append({"key": f"y{year}-p{first}", "payload": {"year": year, "first": first, "last": last, "per_page": NMC_PER_PAGE,
                                                                  "total": total, "expected": expected}})
    return items


PROJECTS = [
    {
        "name": f"{FAMILY}-nmc",
        "title": "NMC Indian Medical Register (all registered doctors)",
        "task": "nmc",
        "target": "nmc.org.in",
        "env": {"SITE": "https://nmc.org.in"},
        "probe": f"{FAMILY}:nmc.org.in",
        "max_workers": 16,
        "unit_label": "block of 10 pages", "record_label": "doctor",
        "items": nmc_items(),
    },
]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:nmc.org.in", "url": "https://nmc.org.in/indian-medical-register/years", "expect": "\"success\":true"}]
