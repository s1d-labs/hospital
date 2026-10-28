# hospital

s1d-labs scrape-pool family for **HospitalDoor**: hospitals in India, and the doctors and other professionals who work in them.
Runs on members' GitHub Actions minutes through scrape-hub (https://scrape.s1d.me). How families work: [CLAUDE.md](CLAUDE.md).

## Projects

| Project | Source | Task | Records |
|---|---|---|---|
| `hospital-dirs` | CGHS empanelled hospitals, e-Raktkosh blood centres (per state), ABDM master lists | `fetch` (`fetch.py`) | one per request: the whole response |
| `hospital-nmc` | NMC Indian Medical Register, `nmc.org.in/indian-medical-register/search` (public JSON) | `nmc` (`nmc.py`) | one per registration (~1.75M), id = the register's own id |

### hospital-nmc

- Queue: one item per registration year and block of 10 pages of 100 (`family.py`, counts in `data/nmc_year_counts.json`,
  taken 2026-10-28). Year slices keep each query small: the site answers 429 "this part of the register is busy" on big
  result sets.
- Speed comes from the project settings on every call: `threads` (concurrent requests per process), `rps_per_worker`
  (requests per second per process), `delay_ms`, `paused`.
- Kept: name, registration no./date, UPRN, council, year of info, qualification (+ year, university), additional
  qualifications, removed status, and the year queried. **Dropped before storing**: home address, date of birth, father's name.

### NMC from one machine (`nmc_box.py`)

NMC refuses GitHub/Azure runner IPs far more than other clients (2026-10-28: 55-90% 429s at 0.2 req/s per runner IP, while a
single VPS client got none), so the pool project is paused and the register is fetched from dev-vps-2 by `nmc_box.py`: one
client, one request at a time with an adaptive gap, every page saved as returned (all fields), resumable. Output stays private
on that box (`~/data/nmc/`); `--build` writes one row per register id and a per-year completeness summary.

## Check

`python -m pytest tests` (parsing, on a made-up saved page), `python nmc.py --local 1990 3` (one live page, no hub),
`scrape-check --items 2` (setup and task against a local stand-in hub).
