"""Save and verify the nationwide CGHS hospital listing."""
import csv
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

endpoint = "https://cghs.mohfw.gov.in/AHIMSG5/hislogin/getEmpanelledHospitalsLgnFtr?stateCode=&cityCode=&status=&tier=&category="
out = Path(sys.argv[1])
request = Request(endpoint, headers={"Referer": "https://cghs.mohfw.gov.in/"})
with urlopen(request, timeout=90) as response:
    payload = json.load(response)
rows = payload["hospitalList"]
if payload.get("errCode") or not rows or not all(r.get("hospitalName") for r in rows):
    raise ValueError("CGHS returned an error or incomplete list")
fields = list(dict.fromkeys(k for row in rows for k in row))
def cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)
out.parent.mkdir(parents=True, exist_ok=True)
os.umask(0o077)
tmp = out.with_suffix(".csv.tmp")
with tmp.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
with tmp.open(newline="", encoding="utf-8") as f:
    saved = list(csv.DictReader(f))
assert saved == [{k: cell(row.get(k)) for k in fields} for row in rows]
os.replace(tmp, out)
print(f"{len(rows)} listings; {len(fields)} source fields; {len({r['hfrId'] for r in saved if r['hfrId']})} distinct nonblank HFR IDs")
