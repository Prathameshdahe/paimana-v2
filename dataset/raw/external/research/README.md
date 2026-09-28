# Web research sweep

`research_sweep_<YYYY-MM>.jsonl`: what the public web said about each current project when it was researched, one
JSON line per project, each fact cited to its source. It is evidence for the project page, the External Factors page,
the risk profile and the assistant; it is **not a model feature** (see below). `python -m pipeline.run research`
(pipeline/research.py) validates it and writes `dataset/gold/research_facts.parquet`,
`dataset/gold/research_projects.parquet` and `dataset/gold/research_summary.json`. The counts (projects searched,
projects with facts, facts per category, rejected lines) live in `research_summary.json`, not here, so this page
stays true as the file grows from the pilot sample to the full portfolio.

## Method

Two passes, told apart per fact by `basis`:

1. **Article pass** (`basis: article`). A research agent ran web searches (2 to 10 queries, kept in `queries`) built
   from the project's name, place names, agency and object (tunnel, bypass, terminal ...), then read the result
   pages. It kept only items about this project (not a neighbouring package or a same-named place; each project came
   with the portfolio's similarly named projects to rule out) and wrote for each a category, direction, severity,
   dates, status, a headline, its own short paraphrase and the URL. The session's web-search budget ran out after
   the first projects, so this pass covers the pilot and the riskiest projects searched first.
2. **Headline pass** (`basis: headline`). For every other project the news scout's own queries (backend/live/scout.py
   `aliases`) were run against the Google News RSS feed at a polite rate, and an agent judged each project's
   candidates from the headline and the feed summary alone: which items are about this project, and what they say.
   Its summaries state only what the headline and feed summary say. These facts are thinner than article facts, and
   their URLs are Google News links that open the publisher's page.
3. **Adversarial check.** A second agent, told to find faults, checked each fact: is it this project, does the
   summary say more than the source (the re-opened page for article facts, the headline and feed summary for headline
   facts), are the dates and category right, does anything name a private person. Its verdict is `keep`, `fix` (the
   fact is kept with the corrected fields) or `drop` (removed). A batch without a verifier verdict is never merged,
   so every fact in the file carries `verified: keep | fix`.
4. **Merge.** Per project the passes are unioned (deduplicated by URL, article facts first) with the verifier's
   corrections into this file, one line per project, in the committed shape below.

`researched_on` is the date the project was searched. A project searched with nothing found has `searched: true`
and `facts: []`: that reads "searched, nothing found", which is not the same as "not searched" (a project with no
line). Neither is "clear": the web is not a register, and absence of news is not absence of a problem.

## Fields

```
{"project_key": "PRJ-000698", "researched_on": "YYYY-MM-DD", "searched": true, "queries": ["..."],
 "latest_status": "one-sentence status in our words" | null,
 "external": {"land_acquired_pct": {"value", "as_of"} | null, "forest_clearance": {"stage", "as_of"} | null,
              "court_case": {"court", "status", "as_of"} | null, "contractor": {"company", "status", "as_of"} | null,
              "new_target": {"date", "as_of"} | null, "cost_revision": {"new_cost_cr", "as_of"} | null},
 "facts": [{"category", "direction", "severity", "event_date", "published_date", "status", "summary", "headline",
            "source", "url", "match", "match_reason", "verified", "basis"}]}
```

| Field | Meaning |
|---|---|
| `category` | `land`, `forest_env`, `litigation`, `contractor`, `funds`, `utility_shifting`, `inter_agency`, `law_order`, `design_scope`, `natural_event`, `approvals_other`, `progress`, `other`. The pipeline maps them to the report-remark taxonomy of pipeline/external.py (`funds` -> `funding`, `natural_event` -> `weather`; the last four have no taxonomy row and keep their name) |
| `direction` | `negative` (holds the project up), `positive` (removes a hold-up or shows progress), `neutral` |
| `severity` | 1 a mention, 2 a hold-up (stoppage, protest, pending clearance, dispute), 3 severe (accident with deaths, court stay, contract termination, cancellation) |
| `event_date`, `published_date` | when it happened and when the source published it: `YYYY-MM-DD`, `YYYY-MM` or `YYYY`, as precisely as the source says |
| `status` | `ongoing`, `resolved` or `unknown`, as of the source |
| `summary` | our own paraphrase, at most 40 words (the agents were asked for 30) |
| `headline`, `source`, `url` | the citation: the page's headline as a label, the publisher, and the page address (`http` or `https`) |
| `match`, `match_reason` | `high`, `medium` or `low`: how surely the item is about this project, and what in the page ties it to the project |
| `verified` | the adversarial checker's verdict, `keep` or `fix` |
| `basis` | `article` (the source page was read) or `headline` (only the news-feed headline and summary were judged); a line without it is `article` |
| `external` | the latest figure the sources give for land acquired (%), the forest-clearance stage, a court case, the contractor and its state, a new completion target and a revised cost (Rs crore), each with the date it is as of; null when no source gives it |

A fact is **live** in the gold table and the API when it is negative, not resolved, and its event date (else its
publish date) is within 4 calendar quarters of the data's as-of quarter, the same window as the report-remark flags
(pipeline/hidden_delay.py `LIVE_Q`). A month or a year date counts from its first day, so a coarse date errs toward
not live.

## Privacy and copyright

- **No article text.** Per fact we keep the headline (as a citation label), our own paraphrase, the publisher, the
  date and the URL. Never the article body, never a quoted paragraph.
- **No private individuals.** No names of landowners, villagers, petitioners, accused persons, contractor staff or
  journalists; officials by office only ("the District Magistrate", "the Works Minister"). Companies, PSUs, government
  bodies, courts and places are named. The pipeline enforces a floor: a text with an honorific (Mr, Mrs, Ms, Shri,
  Smt, Sri, Dr ...) followed by a capitalised word is rejected unless the words after it name an organisation or an
  office (a hospital, a university, a road, a board ...); a test runs this guard over every committed line.
- Sources are public news sites, agency and ministry pages, PIB and parliamentary answers; nothing behind a login or
  a paywall was read.

## Not a model feature

The facts are evidence shown next to the model's score, never an input to it:

- **Hindsight.** A sweep run in 2026 finds what is known in 2026. Training on it would let the model see, for a past
  quarter, news published after that quarter.
- **Notoriety bias.** Large, troubled and much-reported projects get far more coverage than small or quiet ones, so
  "has news" measures fame as much as risk, and "no news" is not "no problem".
- **No point-in-time history.** One search per project gives one snapshot, not a quarterly series the backtest could
  replay.

They do feed the risk profile (ml/risk_profile.py): a live negative fact of severity 2 or more with match `high` flags
the land, forest-clearance, litigation or contractor row (source `news_research`). It never clears a row, so a project
that was not researched stays as the reports and registers left it.

## How to refresh

Research the projects again with the same method and add the result as a new file,
`research_sweep_<YYYY-MM>.jsonl`, in this folder (keep the older one). The pipeline reads every
`research_sweep_*.jsonl`, and for a project in more than one file the line with the latest `researched_on` wins
(a re-search re-finds the older facts that still matter). Then run `python -m pipeline.run research` (or `all`, or
let the report watcher's next run do it) and check the validation counts it prints. The in-app research agent
(backend/live/research.py) adds facts between sweeps from the news scout's items; those live in the app database,
not here.
