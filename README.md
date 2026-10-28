# hospital

s1d-labs scrape-pool family for **HospitalDoor**: hospitals in India, and the doctors and other professionals who work in them.
Runs on members' GitHub Actions minutes through scrape-hub (https://scrape.s1d.me). How families work: [CLAUDE.md](CLAUDE.md).

## Projects

| Project | Source | Task | Records |
|---|---|---|---|
| `hospital-nmc` | NMC Indian Medical Register, `nmc.org.in/indian-medical-register/search` (public JSON) | `nmc` (`nmc.py`) | one per registration (~1.75M), id = the register's own id |

### hospital-nmc

- Queue: one item per registration year and block of 10 pages of 100 (`family.py`, counts in `data/nmc_year_counts.json`,
  taken 2026-10-28). Year slices keep each query small: the site answers 429 "this part of the register is busy" on big
  result sets.
- Speed comes from the project settings on every call: `threads` (concurrent requests per process), `rps_per_worker`
  (requests per second per process), `delay_ms`, `paused`.
- Kept: name, registration no./date, UPRN, council, year of info, qualification (+ year, university), additional
  qualifications, removed status, and the year queried. **Dropped before storing**: home address, date of birth, father's name.

## Check

`python -m pytest tests` (parsing, on a made-up saved page), `python nmc.py --local 1990 3` (one live page, no hub),
`scrape-check --items 2` (setup and task against a local stand-in hub).
