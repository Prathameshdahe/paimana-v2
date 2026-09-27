# External data cross-check

This note checks Garvit's External Factors guide (docs/EXTERNAL_FACTORS_GUIDE.md) and his two mock files
(dataset/raw/external/mock/) against the real sources in the repo. It also says what we took from the guide and
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
- **Parivesh proposal tracker.** Still missing. Forest events in the report remarks cover part of it. In the
  current portfolio, 71 projects mention forest or environment clearance, 35 have an open forest event, and 20
  report forest hectares.
- **Multi-state land data.** Done for the 29 states with data (see above). To refresh a state, drop its
  whole-state export into `dataset/raw/external/bhoomi_rashi/` (see the README there) and rerun
  `python -m pipeline.run external`. Most states' latest Publish Date is 2025-05-09, so the register has barely
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
- **Early notice.** 99 current projects (Rs 129,920 cr) have a flagged external factor while the numbers show no
  slip yet or a Low/Medium tier, 98 of them for land; 18 have no slip to date. Before, 32 (11).
- **Open events in the current portfolio.** The remark rule leaves 34 forest and 44 land events open, but remark
  free text ends in 2023-Q2, so under the four-quarter expiry none of them is open at July 2026.

## What we deliberately did not do

- We did not train, calibrate or backtest on the mock outcomes, because they are fabricated.
- We did not use the fragmentation factors or the mock LA rows outside Maharashtra.
- We did not integrate GatiShakti or the v1 three-way composite. That waits for real GatiShakti layers.
- We did not add the composite as a model feature, to avoid counting forest and land twice.
