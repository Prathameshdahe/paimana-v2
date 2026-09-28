# Bhoomi Rashi state exports

Drop raw whole-state Highway Register exports from https://bhoomirashi.gov.in/ here to give that state's road
projects land-acquisition data. Nothing else needs to change.

1. On the Highway Register page (RepState) pick the state and export the whole-state block, not the
   district-by-district drill-down.
2. Save it here as it comes, one file per state, e.g. `gujarat.xls` (the `.xls` is really an HTML table; `.html`
   works too). Keep files under 25 MB; split a big state into several files if needed, duplicates are dropped.
3. Check the file is complete: its size should equal the response's Content-Length and the file should end with
   `</table>`. The Haryana export was once cut at 15.9 of 51.0 MB and still parsed (34,240 rows of 110,188).
4. Run `python -m pipeline.run external`, then `profile`. The model's land features stay on
   `../land_acquisition_maharashtra.csv` (see `LA_MODEL_TABLE` in pipeline/external.py): the other states add no
   backtest lift, so they are evidence and display only and `gold` and `train` need not rerun.

All 29 states with data were pulled on 2026-09-27 and are already in `../land_acquisition_india.csv` (aggregated
stretches only; the raw exports total about 731 MB, so they are not committed). Arunachal Pradesh and Nagaland
return an empty table. To refresh, run the backend's pull instead of dropping files here: with `BHOOMI_PULL=1` it
pulls every state once a quarter (or one state on `POST /api/jobs/bhoomi-pull?state=GOA`), runs the checks of step
3 itself and keeps only the stretches, in `../bhoomi_rashi_pulls/<date>.csv`.

`pipeline/bhoomi_rashi.py` parses each file (header row inside the table, blank group cells forward-filled,
Publish Date dd/mm/YYYY) and aggregates it to NH stretches in the schema of `../land_acquisition_maharashtra.csv`.
`pipeline/external.py` `load_land` reads those stretches together with every `../land_acquisition_*.csv` and drops a
(state, highway, chainage) stretch it has already seen.

The State column decides which projects can link: a road project links to stretches of its own state (a
Multi-State project: of each state whose district its name mentions) on the NH number in its name, and on the km
range in its name when it gives one. Only a km match rates a project flagged or clear; a link on the NH or district
alone is `possible`. Road projects in a state with no export stay `unknown`, never `clear`.

Needed columns (matched ignoring case, spaces and punctuation): State, Highway Name, Chainage, District,
Sub District, Village, Survey No, Area, Publish Date. The parser stops with the list of columns it found if one is
missing; `parse_bhoomi_rashi(path, state="Gujarat")` fills a missing State column.

Publish Date is read as the Section-3 gazette notification date, not the possession or compensation date. The
portal does not say whether it is the 3A or the 3D date; the register's area by state tracks the land Parliament
answers say was acquired through the portal (93%, r = 0.977), so it looks like acquired (3D) land.
