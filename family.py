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


CGHS = "https://cghs.mohfw.gov.in/AHIMSG5/hislogin/getEmpanelledHospitalsLgnFtr?stateCode=&cityCode=&status=&tier=&category="
ERAKTKOSH = "https://eraktkosh.mohfw.gov.in/eraktkoshPortal/eraktkosh"
ABDM = "https://apinhpr.abdm.gov.in/v4"
# e-Raktkosh state codes (POST master/all, statesWithDistricts, 2026-10-28): census codes 10-37 (no 26), and 91-99 for the
# first nine (J&K, Himachal, Punjab, Chandigarh, Uttarakhand, Haryana, Delhi, Rajasthan, Uttar Pradesh)
ERAKTKOSH_STATES = [*range(10, 26), *range(27, 38), *range(91, 100)]


def dirs_items():
    """Whole small directories, one request each: CGHS hospitals (all India in one answer), e-Raktkosh blood centres per state
    (e-Raktkosh's own state codes, from its master list)."""
    items = [{"key": "cghs-hospitals", "payload": {"url": CGHS, "expected": 1}},
             {"key": "eraktkosh-master", "payload": {"url": f"{ERAKTKOSH}/master/all", "method": "POST", "json": {"hospitalCode": 100}, "expected": 1}},
             ]
    # ABDM (apinhpr.abdm.gov.in) answers 403 to the runners too (2026-10-28): India-only, fetch it from an Indian connection
    items += [{"key": f"eraktkosh-state-{n:02d}", "payload": {"url": f"{ERAKTKOSH}/bloodbanks?stateCode={n}", "expected": 1}} for n in ERAKTKOSH_STATES]
    # the same listing per district (master/all statesWithDistricts, 781 districts): it places every centre in its district
    items += [{"key": f"eraktkosh-district-{s}-{d}", "payload": {"url": f"{ERAKTKOSH}/bloodbanks?stateCode={s}&districtCode={d}", "expected": 1}}
              for s, d, _, _ in json.loads((HERE / "data" / "eraktkosh_districts.json").read_text())]
    # discovery: the public pages, to find the stock-availability and centre-detail endpoints they call
    items += [{"key": f"eraktkosh-page-{k}", "payload": {"url": u, "expected": 1}} for k, u in [
        ("home", "https://eraktkosh.mohfw.gov.in/"),
        ("portal", "https://eraktkosh.mohfw.gov.in/eraktkoshPortal/"),
        ("stock", "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/stockAvailability.cnt"),
        ("nearby", "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt"),
        ("portal-js", "https://eraktkosh.mohfw.gov.in/eraktkoshPortal/static/js/main.fd5d38b3.js"),
        ("sitemap", "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/eraktkoshSiteMap.cnt"),
        # public portal calls (no login): probes before scraping them in full
        ("nearest-all", f"{ERAKTKOSH}/bloodbank/nearest?latitude=22.5&longitude=79.0&radius=3000000"),
        ("refresh-hospitals", f"{ERAKTKOSH}/master/portal-refresh-hospitals"),
        ("ticker", f"{ERAKTKOSH}/notifications/ticker"),
        ("camps-delhi", f"{ERAKTKOSH}/camps/details?stateCode=97&districtCode=-1&startDate=2026-10-30&endDate=2026-12-31"),
    ]]
    # probe: does a state/district stock query honour the component? (the all-India query returns the same totals for every one)
    items += [{"key": f"eraktkosh-probe-aligarh-c{c}", "payload": {"url": "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt"
               f"?hmode=GETNEARBYSTOCKDETAILS&stateCode=99&districtCode=143&bloodGroup=all&bloodComponent={c}&lang=0", "expected": 1}}
              for c in ("11", "12", "20")]
    items += [{"key": f"eraktkosh-probe-up-c{c}", "payload": {"url": "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt"
               f"?hmode=GETNEARBYSTOCKDETAILS&stateCode=99&districtCode=-1&bloodGroup=all&bloodComponent={c}&lang=0", "expected": 1}}
              for c in ("11", "20")]
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
    {
        "name": f"{FAMILY}-bloodstock",
        "title": "e-Raktkosh live blood stock: every state x component, every 3 hours (snapshots kept)",
        "task": "fetch",
        "target": "eraktkosh.mohfw.gov.in",
        "env": {},
        "probe": None,                          # the hub's own box can't reach e-Raktkosh
        "max_workers": 2,
        "unit_label": "request", "record_label": "response",
        "items": [],                            # seeded per snapshot by seed_stock.py (bloodstock workflow)
    },
    {
        "name": f"{FAMILY}-dirs",
        "title": "Small health directories: CGHS hospitals, e-Raktkosh blood centres, ABDM master lists",
        "task": "fetch",
        "target": "mohfw.gov.in",
        "env": {},
        "probe": None,                          # the hub's own box is outside India and can't reach these, so no health check
        "max_workers": 2,
        "unit_label": "request", "record_label": "response",
        "items": dirs_items(),
    },
]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [{"name": f"{FAMILY}:nmc.org.in", "url": "https://nmc.org.in/indian-medical-register/years", "expect": "\"success\":true"}]
