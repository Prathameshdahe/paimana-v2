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
  Rebuilding the current Maharashtra-only data gives the same linked projects and values as before.
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

- **Project to LA crosswalk.** We link on the NH number in the project name, then the district. The links are in
  gold/external_land.parquet. 106 projects are linked, 58 of them current: 35 flagged (complexity 3 or more) and
  23 clear. FC still has no linking key. Each project gets a rulebook profile from its sector and name, plus any
  forest hectares or violations in its report remarks.
- **Parivesh proposal tracker.** Still missing. Forest events in the report remarks cover part of it. In the
  current portfolio, 71 projects mention forest or environment clearance, 35 have an open forest event, and 20
  report forest hectares.
- **Multi-state land data.** Drop each state's whole-state export into `dataset/raw/external/bhoomi_rashi/` (see
  the README there) and rerun `python -m pipeline.run external`. That state's road projects then become linkable
  with no code change.
- **Compensation and possession status.** Not in Bhoomi Rashi. Report remarks tagged `compensation` and
  `possession` are the only signal.

## Current numbers

- **Coverage.** 58 current projects are `fc+la` and 1,705 are `fc_only`.
- **Why the rest have no land data.** Of the current projects without it:

  | Reason | Projects |
  |---|---|
  | Their state has no land data | 907 |
  | Not a road project | 771 |
  | No NH number in the name | 20 |
  | Their NH is not in their state's table | 7 |

- **Scores with `fc+la`.** Scores run from 0.21 to 0.71, with a median of 0.61. 31 projects are flagged at 0.6 or
  more. None is clear: all 58 have unknown forest hectares, so the other 27 are unknown. 23 of them have a clear
  land row, and 4 have a flagged land row (land 3/5, score 0.51), such as PRJ-003297 on NH-61.
- **Scores with `fc_only`.** The median is 0.43, and these projects are not rated. 128 of them would score 0.6 or
  more on forest alone (mostly non-linear mining, expected 6.5/7), but without land data the score is not a
  combined one.
- **The forest part barely varies.** It is 3/7 for 93% of current projects, because forest hectares are rarely
  known. So among `fc+la` projects the composite mostly ranks by land, and flagged in practice means land
  complexity of 4 or more. The land row flags at 3 or more, so the land row, not the composite, is the one to
  read for land.
- **Open events in the current portfolio.** 35 forest events and 46 land events.

## What we deliberately did not do

- We did not train, calibrate or backtest on the mock outcomes, because they are fabricated.
- We did not use the fragmentation factors or the mock LA rows outside Maharashtra.
- We did not integrate GatiShakti or the v1 three-way composite. That waits for real GatiShakti layers.
- We did not add the composite as a model feature, to avoid counting forest and land twice.
