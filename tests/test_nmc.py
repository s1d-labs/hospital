"""Parsing tests for the NMC task on a saved (made-up) search page: fast, no network."""
import json
from pathlib import Path

import family
import nmc

PAGE = json.loads((Path(__file__).parent / "pages" / "nmc-search.json").read_text())


def test_rows_keep_professional_fields_only():
    rows = nmc.parse(PAGE, 1995)
    assert [rid for rid, _ in rows] == ["101", "102"]                # the register's own id; rows without one are skipped
    doc = dict(rows)["101"]
    assert doc["name"] == "Asha Kumari" and doc["registration_no"] == "1234" and doc["state_code"] == "BIH"
    assert doc["additional_qualifications"][0]["qualification"] == "MD (Obst & Gynae)"
    assert doc["query_year"] == 1995
    for rid, data in rows:
        assert not set(nmc.DROPPED) & set(data)                     # home address, date of birth, father's name: never stored
        assert "Patna" not in json.dumps(data) or data["university"] == "Patna University"


def test_empty_strings_become_none():
    doc = dict(nmc.parse(PAGE, 1995))["102"]
    assert doc["name"] is None and doc["uprn_no"] is None and doc["removed_status"] == 1


def test_items_cover_every_registration_once():
    items = family.nmc_items()
    assert len({i["key"] for i in items}) == len(items)
    for year, total in family.NMC_YEARS.items():
        mine = sorted((i["payload"] for i in items if i["payload"]["year"] == year), key=lambda p: p["first"])
        assert sum(p["expected"] for p in mine) == total
        assert mine[0]["first"] == 1 and all(a["last"] + 1 == b["first"] for a, b in zip(mine, mine[1:]))
