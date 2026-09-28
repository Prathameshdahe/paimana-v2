# Web research sweep, September 2026

Every current project (1,763) was searched on the public web on 28 September 2026 for news and official updates about
its delays and blockers. The result is a cited evidence layer next to the model: 1,848 checked facts on 728 projects,
226 of them live blockers on 150 projects. It feeds the project pages, the External Factors page, the risk checklist,
early notice and the AI assistant. It is **not a model input** (see the end).

Data: `dataset/raw/external/research/research_sweep_2026-09.jsonl` (method and fields in the README next to it);
gold tables `research_facts.parquet`, `research_projects.parquet`, `research_summary.json`
(`python -m pipeline.run research`).

## How it was done

| Pass | Projects | How | Check |
|---|---|---|---|
| Article | 67 (the pilot and the first High / Critical batches) | Web search per project (2-10 queries), the result pages read; each project came with the portfolio's similarly named projects so neighbouring packages of one corridor were not confused | A second agent re-opened every source and kept, corrected or dropped each fact |
| Headline | 1,696 | The news scout's own queries (backend/live/scout.py `aliases`) against the Google News RSS feed, 2 workers at 1.5 s per request, no request blocked; an agent judged each project's candidates from the headline and feed summary only | A second agent checked each fact against its headline: this project or a neighbour, does the summary claim more than the headline, category and dates, privacy |

The article pass stopped because the session's web-search budget (200 searches, shared by every agent) ran out after
the first batches; the rest was switched to the feed. Each fact carries `basis: article | headline`, and the app says
"from the headline" on those.

Checks on the committed file: every fact `verified: keep | fix` (1,730 kept as written, 118 corrected, the dropped
ones removed); the pipeline's validation (enums, URLs, dates, 40-word summaries, the honorific + name privacy floor)
drops nothing; an adversarial privacy audit over every string found no private individual. It found 120 public
officials named in headlines (the Prime Minister, Union and state ministers, MPs, PSU heads); they now appear by
office, e.g. "[the Union Road Transport Minister]".

## What was found

| | Facts | of which live negative |
|---|---|---|
| Article basis | 252 | 72 |
| Headline basis | 1,596 | 154 |
| Match high / medium | 1,379 / 469 | |

By tier (projects with any fact / with a live blocker): Critical 28 / 8 of 70, High 115 / 47 of 213, Medium 143 / 27
of 425, Low 308 / 52 of 708, Watch 134 / 16 of 347. Roads & Highways 370 of 992 with facts, Railways 104 of 182,
Power 58 of 97, Coal 32 of 121.

Facts by category and direction:

| Category | Negative | Neutral | Positive |
|---|---|---|---|
| Schedule & progress | 118 | 355 | 325 |
| Contractor | 31 | 143 | 107 |
| Land | 62 | 17 | 38 |
| Other | 70 | 72 | 33 |
| Other approvals | 11 | 9 | 127 |
| Funds | 14 | 24 | 47 |
| Forest / environment | 20 | 12 | 22 |
| Design or scope | 13 | 39 | 3 |
| Inter-agency | 12 | 18 | 16 |
| Litigation | 19 | 2 | 10 |
| Law and order | 28 | 0 | 1 |
| Natural event | 19 | 0 | 0 |
| Utility shifting | 9 | 2 | 0 |

The sources also gave 112 contractor names and states, 108 new completion targets, 21 court cases, 11 forest-clearance
stages, 8 revised costs and 7 land-acquired shares (`research_projects.parquet`).

## What it changed

The risk checklist flags land, forest clearance, litigation and contractor stress from a live negative fact of
severity 2 or more with match high (source `news_research`); it never clears a row. On the 2026-07 profile:

| | Before | After |
|---|---|---|
| Land acquisition flagged | 135 | 142 |
| Forest clearance flagged | 20 | 23 |
| Litigation flagged | 0 | 4 |
| Contractor stress flagged | 0 | 13 |
| Early notice (a flagged factor while the numbers show no slip yet) | 109 projects, Rs 1.72 lakh crore | 122 projects, Rs 2.07 lakh crore |

Before the sweep every report-remark litigation and contractor flag had gone stale (free-text remarks end in 2023);
the sweep gives the first current evidence for both.

## Limits

- **Headline facts are thin.** They say what a headline says, no more; the article was not read.
- **Coverage is not risk.** Big, much-reported projects get more news; 1,035 projects have no fact, which is not "no
  problem".
- **One snapshot.** The sweep is dated 28 September 2026. The in-app research agent (backend/live/research.py) adds
  news judged by the local LLM between sweeps; those facts live in the app database and are labelled as such.
- **Not a model feature.** A 2026 search knows 2026 (hindsight for any earlier quarter), coverage measures fame as much
  as risk, and one snapshot has no point-in-time history for the backtest. The model upgrade round
  (docs/MODEL_UPGRADES_2026-09.md) records this as considered and rejected.

## Refreshing

Research the projects again, add `research_sweep_<YYYY-MM>.jsonl` next to this one (a project's latest line wins),
run `python -m pipeline.run research` and then `profile`. A larger web-search budget per session
(`CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION`) would let the article pass cover every project.
