# Bhoomi Rashi state exports

Drop raw whole-state Highway Register exports from https://bhoomirashi.gov.in/ here to give that state's road
projects land-acquisition data. Nothing else needs to change.

1. On the Highway Register page (RepState) pick the state and export the whole-state block, not the
   district-by-district drill-down.
2. Save it here as it comes, one file per state, e.g. `gujarat.xls` (the `.xls` is really an HTML table; `.html`
   works too). Keep files under 25 MB; split a big state into several files if needed, duplicates are dropped.
3. Run `python -m pipeline.run external`, then `gold`, `score` and `profile` as usual.

`pipeline/bhoomi_rashi.py` parses each file (header row inside the table, blank group cells forward-filled,
Publish Date dd/mm/YYYY) and aggregates it to NH stretches in the schema of `../land_acquisition_maharashtra.csv`.
`pipeline/external.py` `load_land` reads those stretches together with every `../land_acquisition_*.csv` and drops a
(state, highway, chainage) stretch it has already seen.

The State column decides which projects can link: a road project links to stretches of its own state (a
Multi-State project: of each state whose district its name mentions) on the NH number in its name. Road projects in
a state with no export stay `unknown`, never `clear`.

Needed columns (matched ignoring case, spaces and punctuation): State, Highway Name, Chainage, District,
Sub District, Village, Survey No, Area, Publish Date. The parser stops with the list of columns it found if one is
missing; `parse_bhoomi_rashi(path, state="Gujarat")` fills a missing State column.

Publish Date is the Section-3 gazette notification date, not the possession or compensation date.
