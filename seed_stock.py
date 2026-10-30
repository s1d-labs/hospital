"""Queue one e-Raktkosh blood-stock snapshot: all India, every blood group, one request per component (15), plus the list of
every blood centre. Run by the bloodstock workflow every 3 hours (GitHub OIDC: the hub trusts this repo). Item keys carry the
snapshot time (UTC, to the hour), so every snapshot is kept as its own records: live stock and a history.
"""
import time

from scrape_hub_client import seed_queue

from family import FAMILY

BB = "https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBB.cnt"
COMPONENTS = ["11", "12", "13", "14", "16", "17", "18", "19", "20", "21", "23", "28", "29", "30", "31"]   # master/all componentList + 31


def items(ts):
    out = [{"key": f"stock-{ts}-c{c}", "payload": {"url": f"{BB}?hmode=GETNEARBYSTOCKDETAILS&stateCode=-1&districtCode=-1"
                                                         f"&bloodGroup=all&bloodComponent={c}&lang=0", "snapshot": ts, "component": c, "expected": 1}}
           for c in COMPONENTS]
    out.append({"key": f"centres-{ts}", "payload": {"url": f"{BB}?hmode=GETAUTOCOMPLETEDATA&lang=0", "snapshot": ts, "expected": 1}})
    return out


if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H", time.gmtime())
    print(f"{FAMILY}-bloodstock {ts}:", seed_queue(f"{FAMILY}-bloodstock", items(ts)))
