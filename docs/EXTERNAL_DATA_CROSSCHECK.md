# External data cross-check

This note checks Garvit's External Factors guide (docs/EXTERNAL_FACTORS_GUIDE.md) and his two mock files
(dataset/raw/external/mock/) against the real sources in the repo. The research behind it is summed up for the team in
docs/EXTERNAL_RESEARCH_2026-09.md. It also says what we took from the guide and
what we left out. The checks run as tests in tests/test_external_crosscheck.py and tests/test_external.py.
Current numbers are for the scored portfolio at July 2026 (1,763 projects).

## What matches

The forest-clearance side of the mock is faithful to the real Parivesh rulebook. All 89 mock rows that need FC use
a real scenario id, and all 28 scenarios in `parivesh_fc_scenarios.csv` appear (the guide says about 27; the file
has 28). `fc_authority_level` and `fc_complexity_score` equal the rulebook values on every row, and every
`fc_violation_flag` is one the scenario allows.

The composite formulas are as described. In v0, `external_factor_composite_score` = 0.5 x fc/7 + 0.5 x la/5, with a
largest error of 0.0004 (rounding). In v1, it is (fc/7 + la/5 + gs/4) / 3, with a largest error of 0.0005.

The land rule is right on real data. The guide's rule adds one point each for more than one district, a
notification span of 365 days or more, a span of 3 x 365 days or more, 200 parcels or more, and 20 ha or more.
It reproduces `acquisition_complexity_score` on all 347 real Maharashtra stretches. The table also matches the
guide's totals: 89,950 parcels on 90 highways, all in Maharashtra.

## What is synthetic or inconsistent

- The land side of the mock does not follow the rule. It reproduces only 35 of the 71 mock LA rows (49%), because
  the guessed state fragmentation factor (Bihar 1.5, UP 1.35, and so on) is applied after scoring. 62 of those
  71 rows are outside Maharashtra, where we have no real land data at all.
- The outcomes are fabricated. `actual_time_overrun_days` and `overrun_flag` were built from the composite
  (correlation 0.87; the guide says 0.88), so a model trained on them would only learn the formula back.
- The projects are not ours. The ids PAIMANA-1000 to 1149 are not real projects. Only 9% of them cost Rs 150 cr or
  more, and 58 of the 150 are Rural Road, State Highway or Bridge, sectors that are not in the portfolio.
- `fc_status`, `fc_duration_days` and all six `gs_*` GatiShakti columns are invented. There is no Parivesh
  proposal data or GatiShakti data behind them.

Rule: the mock data is synthetic. It is only a test fixture for the formulas. It never feeds the model, the gold
features, the predictions, the risk profile or the app. A test checks that no pipeline, ml or backend code
references it and that every gold key is a real PRJ key.

## What we implemented from the guide

- **Bhoomi Rashi parser** (pipeline/bhoomi_rashi.py). `parse_bhoomi_rashi` reads the HTML-as-.xls export with
  `pd.read_html`. It takes the header from inside the table, forward-fills the blank group cells with `.ffill()`,
  and parses Publish Date as dd/mm/YYYY. That date is the Section-3 gazette notification, not possession.
  `aggregate_stretches` builds one row per stretch in the exact schema of `land_acquisition_maharashtra.csv`.
- **LA rule** (`la_complexity`), which is the guide's 0-5 score.
- **Multi-state land loading** (pipeline/external.py `load_land`). It reads every `land_acquisition_*.csv` and
  every export dropped into `dataset/raw/external/bhoomi_rashi/`, and drops duplicate stretches. A road links only
  to stretches in its own state. A Multi-State road links to each state whose district its name mentions.
  `land_acquisition_india.csv` holds the other 28 states with data (2,679 stretches, pulled from the public
  whole-state Highway Register on 2026-09-27; Arunachal Pradesh and Nagaland return empty tables), so 29 states
  are covered with the Maharashtra file.
- **Km-range linking** (`link_land`). A km range in the project name ('Km 217.500 to Km 254.430', 'KM 267+500 TO
  KM 290+000') picks the stretches of its NH whose own chainage shares more than 1 km with it (`nh_chainage`); a
  stretch that only touches the range is a neighbour, and a stretch whose chainage the range contradicts is ruled
  out at every step. Without a km range the link falls back to (NH, district named) and then to the NH alone. An NH
  the name gives only as an end point ('from Junction with ... NH-54') is not the project's road. Only
  `nh_chainage` links rate a project, flagged at complexity 4 or more (the research cut) and clear below; district
  and NH-only links are `possible`: shown with their stretches, never flagged, and not counted in the composite.
  See "Land link precision" below for why.
- **The model keeps its old land input.** The all-state table and the km link added no backtest lift (2026-09
  ablation: flash y_any_h2 -0.0057 [-0.0096, -0.0021]), so the model's `la_*_by_t` features still read
  `gold/external_land_pairs.parquet`, built as before from the Maharashtra table with the NH/district link. It is
  byte-identical after this change, so the gold version and the champions are unchanged. The display links are in
  `gold/external_land_links.parquet`.
- **Composite with coverage** (`external_composite`, written to gold/external_composite.parquet):
  - Forest part: fc = the rulebook's expected complexity / 7. It always has a value, but it is measured only when
    the forest hectares are known. Without them it is the median over the scenarios of every area band (3/7 for a
    linear project), which is an estimate, not a measurement.
  - Land part: la = linked land complexity / 5. This is known only when the project is linked to land data.
  - With both parts, the score is the v0 formula, 0.5 x fc + 0.5 x la, and coverage is `fc+la`.
  - Without land data, the score is the forest part alone and coverage is `fc_only`. Missing land is never
    treated as 0.
  - The composite shows as a 13th, informational row in the risk profile. That row is flagged at a score of 0.6
    or more with `fc+la`, and unknown with `fc_only`. Below 0.6 it is clear only when the forest hectares are
    known (or the clearance is reported done) and neither the land nor the forest row is flagged. Otherwise it
    is unknown, so the composite never reads clear while a half is an estimate or flagged. It also appears in
    external_summary.json.
  - It is not a model feature, because its inputs already are.

## The guide's open gaps

- **Project to LA crosswalk.** We link on the NH number and km range in the project name, then the district,
  then the NH alone. The links are in gold/external_land.parquet. 692 projects are rated on a km match, 412 of
  them current: 135 flagged (complexity 4 or more) and 277 clear. 378 more (133 current) have only a possible link.
  FC still has no linking key in the land table. Each project gets a rulebook profile from its sector and name,
  plus any forest hectares or violations in its report remarks.
- **Parivesh proposal tracker.** Partly filled from the public legacy portal (pipeline/parivesh.py):
  - `dataset/raw/external/parivesh_fc_proposals_legacy.csv`: 10,025 proposals visible in the PARIVESH 1.0 online
    list (received 2014 to mid-2022). It is not a census: a known proposal (FP/MP/RAIL/41734/2019) is missing, it
    holds 42% of the Stage-II approvals Parliament reports for 2014-2024, and state counts diverge widely from
    the official receipts. User agency names are kept only for government bodies and PSUs.
  - The three proposal numbers the remarks name are looked up (gold/fc_proposal_status.parquet) and set the
    project's forest hectares and pending flag. FP/JH/MIN/44804/2020 (Muraidih, PRJ-001354) was filed in March
    2020 and still had no Stage-I 76 months later, at July 2026. FP/MP/RAIL/41734/2019 (Katni-Singrauli,
    PRJ-002234, 72.8 ha in Sanjay Tiger Reserve) has a DFO query of 17 Jan 2023 with no reply on its timeline
    page, and the page now notes the proposal as withdrawn, so that forest land has no approval on PARIVESH 1.0.
  - Project links: we reviewed all 1,312 automatic name/NH/km candidates (656 projects) by hand and kept 470
    links (396 projects, 376 proposals) in `dataset/raw/external/fc_project_links_reviewed.csv`, each with its
    reason. 394 are specific (same named section, km or package, or the same named mine or line); 76 are softer
    (a corridor-wide proposal, ancillary works such as muck disposal, or a mine proposal that names no phase).
    Our precision estimate is about 95% for the specific links and 70-80% for the softer ones. This is a
    self-check by the same reviewer, not an independent audit.
  - gold/external_fc_portal.parquet: 173 current projects have a linked proposal. At July 2026, 36 of them had
    one still open (filed with no Stage-I, or Stage-I awaiting Stage-II), and none of those 36 has an open forest
    event in its report remarks. These projects are open on PARIVESH but not mentioned in the report.
  - Forest events in the report remarks cover the rest. In the current portfolio, 71 projects mention forest or
    environment clearance, 34 had a forest event still open when the remarks ended, and 21 have known forest
    hectares.
- **Multi-state land data.** Done for the 29 states with data (see above). To refresh, turn on the backend's
  quarterly pull (`BHOOMI_PULL=1`, backend/live/portals.py), which keeps only the aggregated stretches in
  `dataset/raw/external/bhoomi_rashi_pulls/`, or drop a whole-state export into `dataset/raw/external/bhoomi_rashi/`
  (see the README there); then rerun `python -m pipeline.run external`. Most states' latest Publish Date is 2025-05-09, so the register has barely
  changed since May 2025.
- **Compensation and possession status.** Not in Bhoomi Rashi. Report remarks tagged `compensation` and
  `possession` are the only signal.

## Land link precision

On 2026-09-28 we hand-checked 100 current links, drawn after the rules above were fixed on two earlier samples:
25 `nh_chainage`, 25 `nh_district` and 50 `nh_only`. Each was judged from the project name, NH, district and km
range against the linked stretches: correct when the stretch that sets the maximum complexity is on the project's
own section. The table with a reason per link is `dataset/gold/land_link_check.csv`.

| Method | Correct | Precision | Wilson 95% CI | Main errors | Used as |
|---|---|---|---|---|---|
| `nh_chainage` | 21 of 25 | 84% | 65-94% | km restarts per district, a range mixing two roads | flagged / clear |
| `nh_district` | 16 of 25 (1 unclear) | 64% | 45-80% | districts named as the road's end points, other packages of the same road | possible |
| `nh_only` | 16 of 50 (4 unclear) | 32% | 21-46% | the maximum over every stretch of a long NH | possible |

A method under 70% is shown as possible, never flagged. So only `nh_chainage` rates a project.

## Current numbers

- **Coverage.** 412 current projects are `fc+la` and 1,351 are `fc_only`. The 412 are in 28 states (Uttar Pradesh
  43, Karnataka 37, Maharashtra 36, Andhra Pradesh 24, Madhya Pradesh 22, Assam and Jammu & Kashmir 21 each).
- **Why the rest have no rated land.** Of the 1,351 current projects without it:

  | Reason | Projects |
  |---|---|
  | Not a road project | 771 |
  | No NH number in the name | 210 |
  | Their NH is not in their state's table | 88 |
  | Possible link on the NH alone | 75 |
  | No stretch of their NH at the km range in the name | 67 |
  | Possible link on the NH and a district | 58 |
  | Their state has no land data | 56 |
  | The name gives NH numbers only as end points | 26 |

- **Land row.** 135 current projects are flagged (complexity 4 or more on the km-matched stretches) and 277 are
  clear. Before this change, 58 were linked (Maharashtra only), 35 of them flagged at complexity 3 or more.
- **Scores with `fc+la`.** Scores run from 0.21 to 0.71, with a median of 0.51. 135 projects are flagged at 0.6
  or more; in practice these are the projects with land complexity 4 or more, because the forest part barely
  varies. None is rated clear: all have unknown forest hectares.
- **Scores with `fc_only`.** The median is 0.43, and these projects are not rated. 128 of them would score 0.6 or
  more on forest alone (mostly non-linear mining, expected 6.5/7).
- **The forest part barely varies.** It is 3/7 for most current projects, because forest hectares are rarely
  known (63 projects in all have them).
- **Forest row.** 20 current projects are flagged: 19 have a linked PARIVESH proposal still open past its rule
  limit at July 2026 (filed with no Stage-I after more than the 255 or 300 days of the 2004 rules, or Stage-I
  granted more than five years ago with Stage-II still awaited), and 1 is flagged by the rulebook (linear, known
  area, worst complexity 6 or more). Before the portal data, 1.
- **Early notice.** 109 current projects (Rs 171,650 cr) have a flagged external factor while the numbers show no
  slip yet or a Low/Medium tier: 98 for land and 14 for forest clearance. 22 have no slip to date. Before this
  work, 32 (11).
- **Open events in the current portfolio.** The remark rule leaves 34 forest and 44 land events open, but remark
  free text ends in 2023-Q2, so under the four-quarter expiry none of them is open at July 2026.

## Garvit's prior vs measured

Garvit's mock files give each forest-clearance status and each land-acquisition share a "hidden delay" in months.
Those numbers are guesses: the mock outcomes were built from them. `pipeline/hidden_delay.py` measures the same
groups on real projects instead (gold/hidden_delay_priors.parquet). For every key-quarter from 2014 that has a
4-quarter date label, it compares projects in the group with matched projects that have no forest (or land)
mention: within the same sector and year for the remark groups, and within the same months-to-deadline band for land
complexity. The two outcomes are the extra months the anticipated completion moved over the next 4 quarters and the
extra chance of a push of 3 months or more. The 95% intervals come from a project-cluster bootstrap. Groups with
fewer than 15 projects are not measured. The groups were chosen after looking at the data, so these are exploratory
results; after a Holm correction over all groups and both outcomes only "FC awaited" stays below 0.05 (p = 0.048).

| Group (remark stage or land band) | Garvit's status: hidden delay (months) | Projects (rows) | Extra push, next 4 quarters (months) | Extra date-push risk (points) |
|---|---|---|---|---|
| Applied or preparing the proposal | Pending Clearances: 15-32 (median 25.5) | 9 (29) | too few to measure | too few to measure |
| Pending at state level (DFO, CF, nodal, state government) | Pending Clearances: 15-32 (median 25.5) | 53 (253) | +0.1 [-2.7, +3.2] | -5 [-16, +6] |
| Pending at the regional office | Pending at IRO: 11-31 (median 19.5) | 6 (10) | too few to measure | too few to measure |
| Pending at FAC / MoEFCC | Pending at FAC: 28-63 (median 46) | 13 (52) | too few to measure | too few to measure |
| Stage-I granted, awaiting Stage-II or working permission | Stage-I Approved: 4-20 (median 11) | 38 (137) | +2.5 [+0.5, +4.3] | +19 [+7, +30] |
| Stage-II or final approval | Stage-II Approved: 0-16 (median 8) | 28 (119) | +3.0 [-1.2, +8.5] | +16 [+1, +31] |
| Forest clearance awaited, no stage named | Pending Clearances: 15-32 (median 25.5) | 105 (494) | +1.5 [-0.7, +3.5] | +12 [+4, +21] |
| Rejected, returned or in appeal | Rejected / In-Appeal: 78-85 (median 79) | 3 (8) | too few to measure | too few to measure |
| Land under 50% acquired | about 29-59 (0.59 per point left; mock median 31) | 17 (58) | -0.3 [-5.2, +5.8] | -14 [-36, +13] |
| Land 50-80% acquired | about 12-29 (mock median 21) | 31 (156) | +1.1 [-2.4, +4.7] | +4 [-10, +16] |
| Land 80-95% acquired | about 3-12 (mock median 6) | 24 (140) | +0.3 [-3.3, +4.2] | -5 [-20, +8] |
| Land 95-100% acquired | 0-3 (0 at 100%; mock median 1) | 15 (70) | +1.0 [-3.3, +4.9] | -3 [-21, +15] |
| Land complexity 4-5 on the km-matched stretch | fragmentation factor only | 69 (246) | -1.2 [-3.3, +0.5] | +3 [-6, +11] |
| Land complexity 0-3 on the km-matched stretch | fragmentation factor only | 212 (1,072) | -0.9 [-2.2, +0.1] | -1 [-6, +3] |
| Land complexity 4-5 on an NH or district link | fragmentation factor only | 184 (665) | +0.3 [-0.8, +1.1] | +6 [+1, +11] |

How to read it:

- **Garvit's order and sizes are not supported.** His numbers are a total hidden delay; ours is the extra slip over
  the next year, so they are not the same quantity. Even so, no group comes near his bands. Pending at state level
  shows nothing, and the stages he rates worst (FAC, rejected) have too few projects with labels to measure.
- **Stage-I granted, awaiting Stage-II** is the clearest forest signal: about 2.5 extra months and 19 points more
  date-push risk. It does not survive the Holm correction (p = 0.32 and 0.09).
- **"FC awaited" with no stage** adds 12 points of date-push risk and survives Holm.
- **Land share (the real version of his "Land Acquisition Progress %") has no measurable effect in any band.** His
  0.59 months per point is not supported.
- **Land complexity depends on the link.** On the km-matched links that the checklist rates, complexity 4-5 adds
  +3 points (CI -6 to +11, not measurable). On the looser NH or district links of the 2026-09 analysis it adds
  +6 points (CI +1 to +11), which reproduces that analysis, but those links were only 32-64% right on the hand
  check.
- **Pending at FAC / MoEFCC:** the 2026-09 research reported +7 months (CI 2-12) on 16 projects. It counted every
  key-quarter; here only rows with a 4-quarter date label count, which leaves 13 projects, so we show it as too few
  to measure.

The checklist shows the matching line next to each project's forest and land rows, with the quarter the remark
stage or share is as of, for example "expected hidden delay, Stage-I granted, awaiting Stage-II or working
permission (as of 2023-Q2): +3 months over the next year (CI +1 to +4) and +19 pts date-push risk (CI +7 to +30),
measured on 38 projects". Projects linked to PARIVESH also get the portal stage and the rule limit, for example "no
Stage-I after 76 months at Jul 2026; rule limit about 10 months (FC Rules 2004: 300 days to Stage-I for more than 40
ha or mining)".

## What we deliberately did not do

- We did not train, calibrate or backtest on the mock outcomes, because they are fabricated.
- We did not use the fragmentation factors or the mock LA rows outside Maharashtra.
- We did not integrate GatiShakti or the v1 three-way composite. That waits for real GatiShakti layers.
- We did not add the composite as a model feature, to avoid counting forest and land twice.
