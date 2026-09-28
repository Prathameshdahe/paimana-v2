# PAIMANA Early Warning Radar

Our entry for Smart India Hackathon 2026, problem statement 26103 (MoSPI, IPMD).
MoSPI tracks central sector infrastructure projects of Rs 150 crore and above
through quarterly QPISR reports and monthly flash reports. We try to predict
which of those projects will report a schedule or cost slip in their next report.

## Layout

```
paimana-v2/
  frontend/      React dashboard, see frontend/README.md
  backend/       FastAPI
  llm/           LM Studio client and the worker cell
  ml/            train.py
  model/         trained LightGBM model, feature schema, metrics
  pipeline/      data prep scripts
  dataset/       all data, raw to processed
    raw/         QPISR PDFs and MoSPI CSVs, never edited; raw/inbox/ takes new reports
    silver/      cleaned observations (Parquet)
    gold/        features, labels, scores, risk profile (Parquet + JSON)
  database/      paimana.db (SQLite app state, gitignored) and JSON for worker runs and memo drafts
  docs/          design notes and pitch
  temp/          scratch, gitignored
```

Design notes and the pitch are in `docs/PROJECT_DOCUMENTATION.md`. Parts of it
(sections 0, 5, 8, 10 and 12) were written before the model, backend and LLM
workers existed and are out of date.

## Setup

Python 3.10+ and Node 18.18+. We run 3.13 and Node 20. Commands in this file run
from the repo root unless they start with `cd frontend`.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
cd frontend
npm install
```

That's for cmd or PowerShell. In Git Bash use `source .venv/Scripts/activate`
and `cp`, on macOS/Linux `source .venv/bin/activate`. If PowerShell won't run the
activate script, `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

One `.env` at the root is shared by the Python code and Vite (see `envDir` in
`frontend/vite.config.ts`). The defaults from `.env.example` work for a local run.

## Running

The dashboard needs the backend; there is no bundled data. Backend, with the venv active:

```
uvicorn backend.main:app --reload --port 8000 --timeout-graceful-shutdown 3
```

It starts the report watcher and the news scout in the background (see Live
tracking). `LIVE_JOBS=0` in `.env` or the shell turns both loops off; the jobs
still start from the API. The alert stream (`/api/stream`) never ends by itself,
so without `--timeout-graceful-shutdown` Ctrl+C and `--reload` wait forever on an
open dashboard tab.

Dashboard, in a second terminal:

```
cd frontend
npm run dev
```

Open http://localhost:3000. API docs are at http://localhost:8000/docs. Every
page except Home sends you to `/login` until you pick a role. It's only a role
picker, there's no auth. Public can't open the Approval Inbox, and the Worker
Console is for IPMD Analyst and Ministry Official only.

Pages: `/` (map, live status, alert inbox), `/command` (triage), `/external`
(external factors and news evidence), `/bottlenecks` (projects sharing an open
land or clearance issue), `/agencies` (agency schedule and cost bias),
`/radar` (news evidence feed, state heat map, "Run scout now"),
`/projects/:key` (with the validated LLM brief), `/models` (registry,
backtest, calibration, live accuracy; `/audit` redirects there), `/workers`,
`/approvals` and `/login`. The top bar shows the first four and puts the rest
under MORE.

To feed a new report, drop a portal `Projects_Report.csv` export or a PAIMANA
flash PDF into `dataset/raw/inbox/`. The watcher picks it up within a minute, or
at once from "Check inbox now" on Home (IPMD Analyst). New alerts reach the top
bar bell and the Home inbox through `/api/stream`.

The backend reads `dataset/silver/` and `dataset/gold/` through DuckDB and
reloads when a new score or profile lands. Alerts, watchlists and the audit log
are in SQLite (`database/paimana.db`, created on first start); worker runs and
memo drafts stay JSON in `database/`. Routes are in `backend/routes.py`.

Gotchas:

- Vite has `strictPort` on. If 3000 is taken it exits instead of picking
  another port.
- Both servers read `.env` at startup, and `--reload` only watches `.py` files.
  Restart them after editing it.

Smoke tests:

```
python -m backend.test_smoke
```

The two auditor tests call LM Studio, so start it first or the run stops with
`LLMConnectionError`. Frontend checks (`npm run lint`, `npm run typecheck`,
`npm run build`) are in `frontend/README.md`.

### LLM worker cell

Load `qwen/qwen2.5-coder-14b` in LM Studio (or set `LLM_MODEL` to what you
loaded) and start its server on port 1234. Then click "Run Monitoring Cycle Now"
in the Worker Console, or:

```
curl -X POST http://localhost:8000/api/worker-runs/trigger
```

It takes the 10 projects with the highest slip probability and makes 3 or 4 LLM
calls for each. On a 14B model that's a couple of minutes, and the request
blocks until it's done. Without LM Studio you get a 500.

`llm/worker.py` runs five steps per project in order: auditor, forecaster,
scout, analyst, dispatcher. Only the forecaster skips the LLM, it's a lookup into
the model scores. The auditor's checks are plain Python and it calls the LLM
only to word a query to the agency when one fails. Memo drafts from the
dispatcher wait in the Approval Inbox until someone approves or rejects them.

The scout step reads only recorded evidence: the delay events found in the
project's report remarks (`gold/project_events`, with document and page) and
the news signals linked to it (see Live tracking). A project with neither gets
no LLM call and no cause tags.

### Live tracking

The backend runs these background loops (`backend/live/scheduler.py`):

- **Report watcher**, every `WATCH_INTERVAL_S` seconds (60). Drop a portal
  `Projects_Report.csv` export or a PAIMANA flash PDF into `dataset/raw/inbox/`,
  or upload one with `POST /api/jobs/ingest`. The watcher runs the extractor,
  the clean merge and `pipeline.run` silver, external, research, gold, score and profile,
  then raises tier-change and new-project alerts and fills realised outcomes
  in `gold/prediction_log.parquet`. `train` is not part of it; retrain by hand
  each month. One portal file takes about two minutes. If a step fails, the old
  scores keep serving and a `pipeline_error` alert is raised.
- **News scout**, every `SCOUT_INTERVAL_H` hours (24; the first run is 10
  minutes after start). It searches Google News for up to 50 projects
  (watchlists first, then Critical and High) and reads the PIB feed, links items
  to projects and raises `signal` alerts for severity 2 and 3 items.
  `POST /api/jobs/scout?project_key=PRJ-...` scouts one project on the spot.
- **Research agent**, every `RESEARCH_INTERVAL_H` hours (24; the first run is
  30 minutes after start; `RESEARCH_AGENT=0` turns it off). For up to
  `RESEARCH_PER_RUN` projects (20; watchlists, then Critical, High and Watch)
  it refreshes the news, has the local LLM judge each new item from its
  headline (relevant or not, category, direction, severity, a short summary
  whose numbers must be in the headline), stores the relevant ones as cited
  research facts next to the web research sweep, and pauses while a chat
  answer is using the LLM. `POST /api/jobs/research?project_key=PRJ-...` runs
  it for one project.

`POST /api/jobs/watch` runs the watcher now. `GET /api/live/status` shows the
last and next runs and the inbox count, and `GET /api/stream` pushes each new
alert as a Server-Sent Event. `GET /api/signals/feed` pages the stored signals
with the state heat and, for each linked project, the first report after the
news that pushed its date or revised its cost. Set `LIVE_JOBS=0` to turn every
loop off; the tests do.

### Access by role

The sign-in page picks a role: public (no sign-in needed), agency official (one
canonical agency), ministry official (one ministry) or IPMD analyst. Every page
and API answer is cut to that role's projects, and the public gets a simple
project page without model internals. The role goes to the backend in
`X-Paimana-*` headers that it trusts: a prototype, not authentication. The
role-by-page table is in `docs/ACCESS_CONTROL.md`.

## Rebuilding data and the model

The outputs are already in the repo, so you only need this if the raw data or the
training code changes.

```
python pipeline/extract_pdf_context.py    # PDFs -> dataset/silver/pdf_sector_state_fix.csv
python pipeline/clean_sector_state.py     # raw CSVs -> dataset/silver/*_clean.csv
python ml/train.py                        # -> dataset/gold/*.csv and model/*
```

The frontend has no bundled data; every view reads the backend API. The Audit
Suite shows the champion run's `backtest_summary.csv` and `ablation.csv` through
`/api/models`, so it follows a retrain without edits.

## Data cleaning

The sector and state columns in the MoSPI CSVs came from the wrong row during
PDF extraction upstream. Among rows whose project name matches a sector keyword,
the sector disagreed with the name in 70% of 2024-25 rows and 95% of 2025-26
rows. In 2026-27 the sector column is blank on every row.

The PDFs only print State and Sector when the value changes, so
`pipeline/extract_pdf_context.py` re-reads them by the x-position of each word.
It parses the Q1 and Q2 2024-25 PART2 files (the ongoing projects table), Q3 and
Q4 2024-25, and the 2025-26 QR file. The two PART1 files aren't read.
`pipeline/clean_sector_state.py` fills the rest by majority vote across the
project's other reports that year, then keyword rules on the name, then the raw
value. Every row gets a `sector_source` and `state_source` tag, which the
dashboard shows as a data-confidence badge.

After cleaning, 26% of 2024-25 rows and 7% of 2025-26 rows still fail the name
check. Those are lower bounds. Rows filled by the keyword rules get checked
against the same rules and pass automatically, which is also why 2026-27 comes
out at 0%.

## Model

`ml/train.py` labels each report by whether the project's next report shows a
slip: anticipated completion moves out by 3 months or more, or anticipated cost
goes up by 5% or more. Tier 1 features are the raw report fields. Tier 2 adds
time elapsed, optimism gap, progress and spend velocity, revision count,
staleness, size band and the agency's past slip rate.

Features use data from the report date or earlier, with two small leaks. Agency
past slip rate pools other projects' labels, and some of those come from reports
dated after the row being scored. Size band uses quartile edges computed over
the whole training split.

Training data runs up to January 2025 and the test set starts in May 2025, a 3
month gap. The test set is 1,589 reports from 2025-26, of which 64 (about 4%)
are slips. The Tier 2 model goes to `model/`, and scores for all 4,429 projects
go to `dataset/gold/latest_features.csv` with slip probability, top 5 SHAP
drivers and risk exposure in crore (probability times remaining cost). Risk
exposure is blank for about half the projects because they report no
anticipated cost.

| Model | PR-AUC | Slips in top 50 |
|---|---|---|
| Trust the reported date | 0.040 | 2 / 64 |
| Earned schedule extrapolation | 0.044 | 1 / 64 |
| Reference class (sector x type x size) | 0.043 | 2 / 64 |
| Logistic regression, Tier 2 features | 0.043 | 2 / 64 |
| LightGBM, Tier 1 | 0.063 | 3 / 64 |
| LightGBM, Tier 2 (used in the app) | 0.079 | 8 / 64 |

Numbers are from `model/metrics.json`. Tier 2 is best on both metrics, but PR-AUC
is only 0.079 against about 0.04 for random. The top 50 catch 8 of 64 slips, the
baselines 1 or 2. With 64 positives this is noisy. The biggest SHAP features on
the test set are physical progress, agency, number of prior revisions, time
elapsed and recorded delay.

## Known limitations

- 7,845 report pairs were dropped because neither date nor cost could be
  compared. We wanted a 6 month train/test gap and could only fit 3.
- IDs are stable from 2024-25 on, but the 2005-10 and 2021-24 files use other ID
  formats, so history before 2024-25 can't be linked yet. The model uses
  2024-25 and 2025-26. 2026-27 is cleaned but not used for training yet.
- Forecast overrun in crore reads Rs 0 for many projects because `cost_revised`
  is often missing in the source.
- The JSON store in `database/` has no locking, so one user at a time.
- There is no authentication. The role and its scope come from request headers
  the backend trusts (`docs/ACCESS_CONTROL.md`), so they separate views and do
  not protect data.
