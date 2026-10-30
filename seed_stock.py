"""Queue one e-Raktkosh blood-stock snapshot: every state x every blood component (36 x 14 = 504 requests, all blood groups),
plus the list of every blood centre. Also the daily items (keys carry the date, so re-queueing them is a no-op): every centre
with its coordinates (bloodbank/nearest, one call), the donation-camp schedule per state for the next 60 days, the centres
that refresh stock live, and the public notices. Run by the bloodstock workflow every 3 hours (GitHub OIDC: the hub trusts this repo).
Item keys carry the snapshot time (UTC, to the hour), so every snapshot is kept: live stock and a history.

State-level queries honour the component; the all-India query (stateCode=-1) ignores it and returns each centre's totals.
"""
import datetime
import json
import time
from pathlib import Path

from scrape_hub_client import seed_queue

from family import FAMILY

BB = "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt"
PORTAL = "https://eraktkosh.mohfw.gov.in/eraktkoshPortal/eraktkosh"
COMPONENTS = ["11", "12", "13", "14", "16", "17", "18", "19", "20", "21", "23", "28", "29", "30"]   # master/all componentList
STATES = sorted({s for s, _, _, _ in json.loads((Path(__file__).parent / "data" / "eraktkosh_districts.json").read_text())})


def items(ts):
    out = [{"key": f"stock-{ts}-s{s}-c{c}",
            "payload": {"url": f"{BB}?hmode=GETNEARBYSTOCKDETAILS&stateCode={s}&districtCode=-1&bloodGroup=all&bloodComponent={c}&lang=0",
                        "snapshot": ts, "state": s, "component": c, "expected": 1}}
           for s in STATES for c in COMPONENTS]
    out.append({"key": f"centres-{ts}", "payload": {"url": f"{BB}?hmode=GETAUTOCOMPLETEDATA&lang=0", "snapshot": ts, "expected": 1}})
    return out


def daily(day):
    d = datetime.date.fromisoformat(day)
    end = (d + datetime.timedelta(days=60)).isoformat()
    tag = day.replace("-", "")
    out = [{"key": f"daily-{tag}-nearest", "payload": {"url": f"{PORTAL}/bloodbank/nearest?latitude=22.5&longitude=79.0&radius=3000000", "expected": 1}},
           {"key": f"daily-{tag}-refresh", "payload": {"url": f"{PORTAL}/master/portal-refresh-hospitals", "expected": 1}},
           {"key": f"daily-{tag}-ticker", "payload": {"url": f"{PORTAL}/notifications/ticker", "expected": 1}}]
    out += [{"key": f"daily-{tag}-camps-s{s}", "payload": {"url": f"{PORTAL}/camps/details?stateCode={s}&districtCode=-1&startDate={day}&endDate={end}",
                                                          "state": s, "expected": 1}} for s in STATES]
    return out


if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H", time.gmtime())
    print(f"{FAMILY}-bloodstock {ts}:", seed_queue(f"{FAMILY}-bloodstock", items(ts)))
    day = time.strftime("%Y-%m-%d", time.gmtime())
    print(f"{FAMILY}-bloodstock daily {day}:", seed_queue(f"{FAMILY}-bloodstock", daily(day)))
