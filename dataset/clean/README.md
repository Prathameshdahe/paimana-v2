# dataset/clean

Clean CSVs extracted from the MoSPI IPMD reports in `Dataset drive folder/Dataset/`.
There are 262 PDFs plus 3 portal CSVs. The folder covers infrastructure sector
performance (2015-2026) and central-sector projects of Rs 150 crore and above
(2005-2026).

## Conventions

- UTF-8, comma-separated, header row, snake_case columns.
- Dates are `YYYY-MM`. The portal files use `YYYY-MM-DD` because the portal gives the day.
- Money is Rs crore (`*_cr`). Percentages are `*_pct`.
- A blank cell means the value was not printed in the source. It is never a hidden 0.
- Printed values are never overwritten. Derived values sit in their own columns,
  for example `*_computed`, `*_canon`, `cost_latest_cr` and `financial_progress_pct`.
- `source_file` and `page` (1-based) point back to the PDF each row came from.
- Row-level data-quality flags use `;`-separated tokens:
  - `dq_note` is set by the extractor. Examples: `placeholder_zero`,
    `placeholder_doc_1999`, `carried_forward:2025-12`, `printed_pct_mismatch`,
    `stale_repeat_of:2006-03`, `label_restored`, `transcribed_from_image`,
    `duplicate_in_source`.
  - `dq_flags` has a different meaning in each area:
    - Performance files: `dq_note` plus report-level flags.
    - Project files: report-level flags only, such as `report_partial`,
      `report_truncated`, `scope_excludes:MoRTH`, `stale_repeat_of:*` and
      `printed_code_conflict`. Row-level problems stay in `dq_note`.

## Files

### performance/  (monthly Review of Infrastructure Sector Performance)

| File | Rows | What |
|---|---|---|
| `performance_sector_monthly.csv` | 2,879 | **Main series.** One row per report month x indicator in canonical units. Month columns (target, actual, previous-year actual, growth %, % vs target) and April-to-month cumulative columns. `is_sector_headline` gives one headline indicator per sector. `data_month` differs from `report_month` when the source carried data forward. `pct_source` says whether each % was printed or computed. |
| `performance_annexure.csv` | 6,290 | Every Annexure-A row (month and cumulative) as printed, plus `indicator_key`, `*_canon` values and computed %. |
| `performance_detail.csv` | 242,960 | All other tables in long form: one numeric cell per row with `table_title`, `table_no`, `row_label(_clean)`, `column_label`, `period_start` and `period_end`. Covers Highlights, Areas of concern, Noteworthy performance and the sector detail tables (power by utility, coal by company, ports, airports, telecom and so on). Filter on the period columns, not the label text. |

The 11 sectors are Power, Coal, Steel, Cement, Fertilizers, Petroleum & Natural Gas,
Roads, Railways, Shipping & Ports, Civil Aviation and Telecommunications.

### projects/  (flash reports, quarterly QPISR and PAIMANA flash reports)

| File | Rows | What |
|---|---|---|
| `projects_monthly.csv` | 113,412 | One row per project x list x report, from the monthly flash reports (2005-05 to 2016-03) and the PAIMANA flash reports (2025-04 to 2026-07). |
| `projects_quarterly.csv` | 52,093 | Same layout, from the quarterly QPISR reports (2014-06 to 2018-03 and 2021-06 to 2025-06). |
| `project_summaries.csv` | 194,466 | Aggregate tables as printed (sector-wise, ministry-wise, state-wise, overall, delay ranges...) in long form: `dimension`, `dimension_value`, `metric`, `value`. |
| `project_sector_period.csv` | 2,624 | Computed from ongoing lists per report x harmonised sector: counts, costs, overrun, delays, expenditure. Also carries the report's own printed count (`printed_n_projects`) and the difference (`n_projects_diff`). |
| `project_state_period.csv` | 3,599 | Same, per canonical state. It only includes single-state projects: Multi-State, PAN India and Not Specified are left out, which is about 18% of projects. |
| `project_period_overview.csv` | 177 | One row per report with totals and `report_flags`. It is also the project coverage table. |
| `project_master.csv` | 8,435 | One row per `project_key`: latest name, sector, state and agency, first and last seen, status at last sighting, latest cost, progress and dates, `n_cost_revisions`, `n_schedule_slips`, and `in_portal_snapshot`. |

Key project columns:

- `list_type` is one of: `ongoing` (master list; use it for aggregates),
  `completed`, `newly_added`, `dropped`, or `other:<list>` (for example
  `other:additionally_delayed` or `other:delayed_wrt_original`).
- Costs: `cost_original_cr`, `cost_revised_cr` and `cost_anticipated_cr` are as printed.
  `cost_latest_cr` is anticipated, else revised, else original; `cost_latest_basis`
  says which one was used.
- Dates: `doa_*` is the date of approval and `doc_*` is the date of commissioning
  (original, revised or anticipated). `delay_months` is as printed and
  `time_overrun_months_computed` is derived.
- `sector_raw` is as printed. `sector` is the harmonised vocabulary covering 2005-2026
  (see `reference/sector_map.csv`). `sector_hml` is the PAIMANA / HML 2022 sector.
- `state_raw` is as printed. `state` is the canonical 2026 State/UT name, or one of
  Multi-State, PAN India, Offshore, Abroad, Not Specified.
- `project_key` links one project across reports and eras. It is a system-prefixed
  code, for example `OCMS:N16000018` or `PAIMANA:706718`. Rows with no code get
  `NAME:<hash>` from an exact name match. `key_source` says how the key was assigned.
- `project_code_alt` holds other printed IDs, for example `OCMS:...;PMG:...`.

### portal/  (PAIMANA portal export, snapshot around Jul 2026)

| File | Rows | What |
|---|---|---|
| `portal_projects.csv` | 1,775 | One row per project. A revised cost of 0 in the export means "not revised" and is stored blank. Adds overrun, delay and financial-progress columns and `dq_flags`. |
| `portal_sector_summary.csv` | 22 | Sector rollup. `cost_latest_cr` = revised cost if revised, else original. |
| `portal_state_summary.csv` | 36 | State rollup. |

### reference/

| File | What |
|---|---|
| `perf_indicator_map.csv` | Maps each printed performance label to an `indicator_key`. Also gives `unit_canonical`, `scale_to_canonical`, `is_sector_headline` and `comparable_across_years` (with a note). |
| `perf_coverage.csv` | One row per month from Apr 2015 to Mar 2027 with status ok, partial or missing. |
| `sector_map.csv` / `state_map.csv` | Raw value (by era, and by ministry where needed) to harmonised value. |
| `project_id_crosswalk.csv` | Links between OCMS, PAIMANA and PMG codes, with evidence. Includes links that were rejected and the reason. |
| `source_manifest.csv` | One row per source PDF: rows extracted, printed totals, status (`ok`, `partial`, `skipped_duplicate`) and quality notes. |

### _parts/

Intermediate layer, one folder per report family, with the raw extractor output.
The final files above are built from it. Keep it for debugging and rebuilds.

## Coverage and gaps

- **Performance.** 76 reports: FY2015-16 to FY2020-21, plus Jun 2025 to Jan 2026.
  No source report exists for:
  - Nov 2015, Sep 2017 and Apr 2019;
  - all of FY2021-22 to FY2024-25;
  - Apr, May and Aug 2025.

  The `Performance Monitoring/2026-27` folder actually holds PAIMANA project flash
  reports, which are processed as projects.
- **Monthly flash reports** run from 2005-05 to 2016-03. There are no monthly
  reports from 2016-04 to 2025-03.
- **Quarterly reports** run from 2014-06 to 2018-03 and from 2021-06 to 2025-06.
  There is nothing from 2018-06 to 2021-03.
- **PAIMANA flash reports** run from 2025-04 to 2026-07. Sep and Oct 2025 are missing.

## Caveats

- **Aug 2020 performance report.** Pages 14-43 have no text layer. Its Annexure-A
  and Highlights were transcribed from rendered page images, not parsed from text
  (`dq_note transcribed_from_image`). They were checked against the table's own
  sums and the neighbouring months. Its other tables are missing.
- **Steel series restated.** The source restated `steel_finished_total` from the
  Jun 2019 report onward (levels about 22% lower), so it is marked not comparable
  across years. Fertilizer totals include urea from FY2025-26.
- **Telecom.** Some reports reprint earlier months, flagged
  `carried_forward:<month>`; use `data_month`. The telecom headline series
  (net additions) stops at 2021-03. FY2025-26 prints subscriber stocks instead
  (`telecom_subscribers_total`).
- **Reports with reduced scope.** Jul, Aug and Nov 2025 PAIMANA reports exclude
  MoRTH road projects (`scope_excludes:MoRTH`), so their totals are about half of
  the neighbouring months.
- **Monthly flash reports with problems.** Sep 2007 is truncated in the source and
  has no ongoing rows. Apr 2006 and Jul 2008 reprint the previous month's list
  (`stale_repeat_of`). The Q2 2023-24 QPISR lacks 32 projects that are printed nowhere.
- **No state before mid-2010.** Monthly reports before 2010-07 print no state
  column. State aggregates start then.
- **Project linking.** Links are exact only; there is no fuzzy matching. The
  2005-10 reports carry codes on only about 16% of rows. The rest link by exact
  name within adjacent reports, so some old projects split into several keys. A
  printed code attached to a clearly different project is ignored for keying
  (`printed_code_conflict`).
- **Placeholders.** 01/1999 commissioning dates and placeholder 0.00 progress or
  expenditure are blanked where they are clearly placeholders. Other printed zeros
  are kept.
- **Kept as printed.** Some percentages printed in the source disagree with its own
  figures. They are kept and flagged `printed_pct_mismatch`.

## Rebuild

From the repo root, with `PYTHONIOENCODING=utf-8`:

```
python pipeline/extract/<family>.py        # each of the 10 extractors -> _parts/
python pipeline/extract/portal_csv.py      # -> portal/
python pipeline/build_clean_performance.py # -> performance/, reference/perf_*
python pipeline/build_clean_projects.py    # -> projects/, reference/*
```

The families are `perf_2015_18`, `perf_2018_21`, `perf_2025_26`,
`proj_monthly_2005_10`, `proj_monthly_2010_13`, `proj_monthly_2013_16`,
`proj_quarterly_2014_18`, `proj_qpsir_2021_24`, `proj_qpisr_2024_26` and
`proj_flash_2025_27`. Every script ends with assert-based checks.
