# PAIMANA v2 — Complete Project Guide

> **PAIMANA** = **P**roject **A**nalysis, **I**ntelligence, **M**onitoring **A**nd **N**otification **A**ssistant  
> A system that watches India's major infrastructure projects and tells you — *before the delay shows up in a report* — which ones are about to slip.

---

## Table of Contents

1. [What This System Does (Plain English)](#1-what-this-system-does)
2. [System Architecture Overview](#2-system-architecture)
3. [Data Journey — Raw → Clean → Silver → Gold](#3-data-journey)
4. [The ML Model — How It Predicts Delays](#4-the-ml-model)
5. [External Factors — Land, Forest, Court Cases](#5-external-factors)
6. [Backend — Services Running at Port 8000](#6-backend-services)
7. [Frontend — Pages and Who Sees What](#7-frontend-pages)
8. [AI Worker — The 5-Step LLM Pipeline](#8-ai-worker)
9. [Live Monitoring — What Happens When a New Report Drops](#9-live-monitoring)
10. [Access Control — Roles and Scopes](#10-access-control)
11. [How to Run Locally](#11-how-to-run-locally)
12. [Key Numbers (Current State)](#12-key-numbers)
13. [Glossary](#13-glossary)

---

## 1. What This System Does

India has ~1,800 active infrastructure projects (roads, railways, bridges, pipelines) under central government monitoring. Each project is worth hundreds of crores of rupees. Most of them are late.

**The problem:** By the time a delay shows up in an official report, the project has already been late for months. The report is published quarterly, reviewed manually, and action — if any — comes even later.

**What PAIMANA does:**

```
PDFs of government reports  ──►  extract data  ──►  build timeline
                                                              │
External signals (news,           ◄──  predict slip  ◄──────┘
PARIVESH, land data)                      │
                                          ▼
                              Alert the right person NOW
                              before the next quarterly report
```

**In one sentence:** PAIMANA reads 20 years of project reports, learns what a project looks like 2–4 quarters *before* it slips, and fires an alert as soon as it sees those signs — along with the top reasons why.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                         │
│  262 PDFs (2005–2026)  │  Portal CSVs  │  External APIs    │
│  Performance reports   │  1,775 rows   │  PARIVESH, news   │
└──────────┬──────────────┴──────┬────────┴──────┬────────────┘
           │                    │                │
           ▼                    ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                     PIPELINE (Python)                        │
│  pipeline/extract/   pipeline/silver.py    pipeline/gold.py  │
│  Read PDFs           Type & clean          Point-in-time     │
│  165,000+ rows       73,167 panel rows     features          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    ML MODEL (LightGBM)                       │
│  ml/train.py  ──►  ml/registry.py  ──►  ml/score.py         │
│  Backtest          Best model kept        Score portfolio     │
│  PR-AUC 0.771      (champion/challenger)  1,416 projects     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              BACKEND — FastAPI  (port 8000)                  │
│  backend/main.py   backend/routes.py   backend/live/         │
│  35 REST endpoints  Serving scores     Inbox watcher         │
│  SQLite for alerts  Access control     News scout            │
│  SSE alert stream   LLM worker         PARIVESH jobs         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│            FRONTEND — React + Vite  (port 3000)             │
│  10 pages  │  Role-based views  │  Real-time bell alerts    │
│  Project detail drawer with tier ring, gauges, timeline      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Data Journey

### 3a. Raw Sources

| Source | Format | What is in it |
|--------|--------|---------------|
| Monthly flash reports 2005–2016 | PDF | 130 reports, 89,500 project rows |
| Quarterly project reports 2014–2026 | PDF | 34 reports, 51,800 project rows |
| PAIMANA flash reports 2025–2026 | PDF | 14 reports, 23,000 project rows |
| Performance reviews 2015–2026 | PDF | 76 reports, 6,206 target-vs-actual rows |
| Portal CSV snapshot | CSV | 1,775 active projects with metadata |
| PARIVESH (forest clearance) | Web/CSV | 470 linked proposals |
| Bhoomi Rashi (land acquisition) | CSV | 412 projects in 29 states |

### 3b. Extract (pipeline/extract/)

12 extractor scripts — one per report family. They use `pymupdf` to read PDF text, parse tables row by row, and write raw rows to `dataset/clean/_parts/`.

```
PDF file
  │
  ▼ pymupdf reads text
  ▼ regex finds table rows
  ▼ fix common errors:
     - minus signs lost on negative numbers
     - sector labels carried across page breaks
     - "not reported" zeros stored as real zeros
  ▼
dataset/clean/_parts/{report_type}/*.csv
```

### 3c. Identity Resolution (pipeline/build_identity.py)

**Problem:** The same project appears in 20 years of reports with different codes and spellings.

**Solution:** Every unique `project_key` (8,429 distinct entities after deduplication) gets one stable `PRJ-xxxxxx` key. Rules:

- Two projects with different *vetted* codes are **never** merged
- Name-only matches from older reports link to a code key if confident
- Ties are broken by sort (deterministic — same result every run)
- Uncertain pairs go to `review_queue.csv` for a human

```
Result: 6,253 PRJ- keys
        1,767 / 1,775 portal projects matched cleanly
        542 in review queue (e.g. "Part-A vs Part-B of same scheme")
        Build time: ~29 seconds
```

### 3d. Silver Layer (pipeline/silver.py)

Cleans and structures the raw extracted rows into a panel (one row per project per quarter).

**Quarantine rules** — rows are *set aside* (not deleted):

| Rule | Rows held |
|------|-----------|
| Expenditure > 3× latest cost | 217 |
| Completion before sanction date | 150 |
| Placeholder dates (1999-01, etc.) | 71 |
| Negative money values | 6 |
| Duplicate project+period rows | 407 |
| **Total** | **851** |

**Output:** `dataset/silver/observations.parquet` — 73,167 project-quarter rows across 6,250 projects.

### 3e. Gold Layer (pipeline/gold.py)

Builds the model's **features** using only data available at each point in time (strict cutoff — a test fails the build if any future data leaks in).

**Key features built:**

- Cost overrun ratio (current cost ÷ original cost)
- Physical progress lag (expected vs actual % done)
- Days since last report update
- Sector, agency, state (encoded)
- Time in system (quarters since sanction)
- S-curve deviation (how far from expected spend profile)

**Labels built:**

- `y_any_h2` — did the project slip in the next 2 quarters?
- `y_any_h4` — did the project slip in the next 4 quarters?

> **Label fix applied:** A slip label is only set when *both* the date and cost outcome are known. Projects with no completion date get no label — they are not assumed to have slipped.

---

## 4. The ML Model

### Training (ml/train.py + ml/backtest.py)

**Method:** Rolling-origin backtest — the model is trained on everything up to quarter Q, then tested on Q+1. This simulates real-world use where you can never use future data.

**Models compared:**

| Model | PR-AUC (validation) | PR-AUC (flash reports) |
|-------|--------------------|-----------------------|
| Naive baseline | 0.420 | — |
| Rule score | 0.435 | — |
| Logistic regression | 0.485 | — |
| **LightGBM** | **0.698** | **0.771** |

> PR-AUC = how well the model ranks slipping projects above safe ones. 1.0 = perfect, 0.5 = random.

### Model Registry (ml/registry.py)

Every training run is saved to `model/runs/ML-{timestamp}/`. A new model replaces the current champion **only if** it scores better on the same held-out quarters. This prevents accidentally deploying a worse model.

```
model/runs/
  ML-20260927-222602/   ← current champion
    lightgbm_y_any_h2.txt
    lightgbm_y_any_h4.txt
    backtest_folds.csv
    shap_summary.csv
    params.json
```

### Scoring (ml/score.py)

Every project in the current portfolio is scored. Output per project:

- Slip probability (0–1)
- 90% confidence range for months slipped
- 90% confidence range for cost overrun %
- Top 5 SHAP reasons (e.g. "cost overrun 2.3×", "no progress update 3 quarters")
- Tier assignment by rank
- Similar past projects (analogues that look the same and did slip)
- 3 scenario curves (best case / median / worst case)

### Risk Tiers (at 2026-07)

| Tier | Projects | What it means |
|------|----------|---------------|
| 🔴 Critical | 70 | Top 5% by slip probability |
| 🟠 High | 213 | Next 15% |
| 🟡 Medium | 425 | Middle band |
| 🟢 Low | 708 | Low probability |
| ⬜ Watch | 347 | No completion date — cannot score |

> **Stalled badge:** 282 projects are flagged as "Stalled" (no physical progress for 2+ quarters). This is shown as a badge — it does NOT raise their tier.

---

## 5. External Factors

These are signals that do **not** appear in the project reports but explain why a project is stuck.

### 5a. Report Remarks Tagger (pipeline/external.py)

Every project report has a free-text "remarks" field. The tagger scans it for keywords:

| Tag | What it catches | Active flags |
|-----|----------------|--------------|
| Land | Land acquisition pending, compensation, possession | 79 projects |
| Forest | Forest clearance, PARIVESH, diversion | — |
| Court | NGT order, High Court stay, litigation | — |
| Contractor | Contractor dispute, rescinded, terminated | — |
| Funds | Budget release pending, funds not available | — |

> **Stale flags:** Remark flags older than 4 quarters are marked stale (the issue was likely resolved). All 76 old "open" remark flags turned out to be stale.

**Land false-alarm fix:** Projects whose remarks said "99% land acquired" or "compensation already paid" were wrongly flagged as open. Keywords like "acquired", "paid", "taken", "handed over" now close the issue.

### 5b. PARIVESH (Forest Clearance)

Government forest-clearance proposals, matched to projects.

- 1,312 automatic matches reviewed → 470 kept
- 173 current projects linked
- 36 have a proposal still open
- 19 of those 36 are past the legal time limit

**Demo cases (blocked on PARIVESH, not visible in report numbers):**

- Sardar Sarovar — 102 months waiting for Stage-II
- Goa–Kundapur NH-66 — 98 months, no Stage-I
- Muraidih — 76 months, no Stage-I

### 5c. Bhoomi Rashi (Land Acquisition)

Land acquisition register for all 29 states, matched by NH number and km range.

| Match type | Accuracy | Used as |
|------------|----------|---------|
| NH number + km range | 84% correct | Rated (flagged or clear) |
| NH + district | 64% correct | "Possible" only — never flagged |
| NH number alone | 32% correct | "Possible" only — never flagged |

412 current projects are rated; 135 are flagged.

### 5d. Measured Hidden Delay

Real delay added by each external factor, measured on actual projects (not guessed):

| Factor | Extra delay | Projects measured |
|--------|-------------|-------------------|
| Stage-I granted, awaiting Stage-II | +2.5 months, +19 pts date-push risk | 38 |
| Land % acquired | No measurable effect | — |
| Groups with fewer than 15 projects | "Too few" — not reported | — |

---

## 6. Backend Services

The backend is a **FastAPI** app at `http://localhost:8000`. It starts four background jobs and serves 35 REST endpoints.

### 6a. How It Starts (backend/main.py)

```python
# On startup:
serving.state()      # load current model + data files into memory
db.init()            # create/connect SQLite (alerts, watchlist, audit)
scheduler.start()    # start inbox watcher + news scout + PARIVESH jobs
```

### 6b. Background Jobs (backend/live/scheduler.py)

```
Every 60 seconds ──► inbox watcher    (dataset/raw/inbox/)
Every 24 hours   ──► news scout       (Google News + PIB)
Every 6 hours    ──► PARIVESH snapshot
On demand only   ──► Bhoomi Rashi pull (set BHOOMI_PULL=1)
```

### 6c. Inbox Watcher (backend/live/watcher.py)

```
New file lands in dataset/raw/inbox/
          │
          ▼ (within 60 seconds)
Classify: portal CSV or PAIMANA flash PDF?
          │
          ▼
Run extractor → silver → external → gold → score → profile
          │
       Success?
      ┌──┴──┐
     Yes    No
      │      │
      ▼      ▼
Move to     Roll back everything
raw/pdf/    Stay on old predictions
or raw/csv/ Raise pipeline_error alert
          │
          ▼
Diff old vs new predictions:
  tier_up alert    (project moved to higher tier)
  tier_down alert  (project improved)
  new_project alert (project appeared for first time)
  slip_realised alert (we predicted it and it happened)
```

### 6d. News Scout (backend/live/scout.py)

Checks Google News and PIB for articles mentioning project names. Links articles to projects. Tags them with the same delay categories (land, forest, court, contractor, funds).

Real run on 5 Critical projects: **28 articles stored**, 17 linked to a project, 11 unlinked (match too uncertain). For 3 linked projects, the article came **47–84 days before the report confirmed the delay**.

### 6e. Alert Stream (SSE)

The frontend connects to `GET /api/stream` and receives real-time alerts as Server-Sent Events (SSE). The backend polls SQLite every 2 seconds for new alerts and pushes them. A heartbeat every 15 seconds keeps the connection alive.

### 6f. All API Endpoints

| Endpoint | What it returns |
|----------|----------------|
| `GET /api/meta` | Dataset version, last update |
| `GET /api/portfolio` | Tier counts, current snapshot |
| `GET /api/projects` | Paginated project list (filters: tier, sector, state, search) |
| `GET /api/projects/{key}` | Full project detail: predictions, checklist, PARIVESH, land, analogues |
| `GET /api/projects/{key}/timeline` | Quarter-by-quarter history |
| `GET /api/projects/{key}/forecast` | Scenario curves |
| `GET /api/projects/{key}/brief` | 2-paragraph LLM summary |
| `GET /api/projects/{key}/signals` | News + remark events for this project |
| `GET /api/agencies/matrix` | Agency scatter: on-time % vs overrun % |
| `GET /api/bottlenecks` | Groups of 3+ projects stuck on the same issue |
| `GET /api/external/summary` | Land, forest, court flag counts |
| `GET /api/models` | Model history, calibration, top features |
| `GET /api/alerts` | Paginated alert list |
| `POST /api/alerts/{id}/ack` | Acknowledge an alert |
| `GET /api/watchlist` | Projects you are watching |
| `POST /api/watchlist` | Add to watchlist |
| `GET /api/radar/summary` | State heatmap + news feed data |
| `GET /api/stream` | SSE alert stream |
| `POST /api/jobs/ingest` | Manually trigger inbox processing |
| `POST /api/jobs/scout` | Manually trigger news scout |
| `POST /api/jobs/parivesh-snapshot` | Manually trigger PARIVESH pull |
| `GET /api/worker-runs` | AI worker run history |
| `POST /api/worker-runs/trigger` | Trigger an AI worker cycle |
| `GET /api/dispatch` | Pending AI-drafted notices |
| `POST /api/approvals` | Approve/reject a drafted notice |

### 6g. SQLite Database (backend/db.py)

Small operational data that does NOT go in parquet files:

| Table | What is stored |
|-------|----------------|
| `alerts` | Tier changes, new projects, slip realisations, pipeline errors |
| `watchlist` | Ministry/agency starred projects |
| `audit_log` | Who approved what and when |
| `news_items` | Articles found by the scout |
| `worker_runs` | AI worker cycle results |
| `job_runs` | Inbox/scout/PARIVESH run history |

---

## 7. Frontend Pages

Built with **React + Vite + TypeScript**, served at `http://localhost:3000`.

### Page Map

```
/login              Sign-in (email and password; "Continue as public")
/signup             Request access (reviewed by an IPMD administrator)
/                   Home — role-specific landing
/command            Portfolio table, filters, tier strip
/projects/:key      Full project page
/agencies           Agency performance scatter
/bottlenecks        Shared blockers
/radar              News feed + state heat map
/external           Land, forest, clearance panel
/models             Model history + calibration (developer only)
/workers            AI worker control (developer only)
/approvals          Approve AI-drafted notices (IPMD only)
/admin              Access requests and users (administrators); the audit log (developer)
```

### Project Detail Drawer

Opens from any list by clicking a project. Contains:

```
┌─────────────────────────────────┐
│  Tier Ring + 3 Probability      │
│  Gauges (slip / date push /     │
│  cost revision)                 │
├─────────────────────────────────┤
│  Time-used vs Work-done bar     │
│  Money bar (overrun hatched)    │
│  Progress trend line            │
├─────────────────────────────────┤
│  Timeline: Sanction → Original  │
│  → Anticipated → Predicted      │
│  completion + Today marker      │
├─────────────────────────────────┤
│  13 Risk Check tiles (coloured  │
│  icons, hover for evidence)     │
├─────────────────────────────────┤
│  Top 3 SHAP reasons             │
│  External issue chips           │
│  "Open full page" button        │
└─────────────────────────────────┘
```

### The 13-Row Risk Checklist

Every project gets a checklist row for each of these signals:

1. Cost overrun > 20%
2. Cost overrun > 50%
3. Physical progress behind plan
4. No physical progress for 2+ quarters
5. Expected completion in the past
6. Completion date changed 2+ times
7. Stagnation (no change to any field)
8. Land issue (open)
9. Forest clearance pending
10. Court / NGT order active
11. Contractor issue
12. News article signals delay
13. Similar past projects that slipped

---

## 8. AI Worker

Five sequential LLM calls, no agent framework — a for-loop is enough.

```
llm/worker.py → run_worker_cycle()

Step 1: AUDITOR
  Plain Python, no LLM.
  Checks staleness, data quality, and whether the project looks suspicious.
  Only calls the LLM if it finds issues.

Step 2: SCOUT
  LLM reads the top-10 projects by slip probability.
  Summarises what the data says about each one.
  Output: EvidenceItem list

Step 3: ANALYST
  LLM gets the scout evidence + external signals.
  Decides which projects need action, with reasoning.
  Output: AnalystOutput with priority ranking

Step 4: DISPATCHER
  LLM drafts a formal notice for each flagged project.
  Notice goes to the project's controlling ministry.
  Output: DispatchDraft (not sent — waits for approval)

Step 5: DRAFTER (optional)
  LLM writes a 2-paragraph brief for the IPMD dashboard.
  Every number in the brief must appear in the project data.
  If it hallucinates a number, the brief is rejected.
```

The drafted notices sit in the approval inbox. An IPMD officer reviews and approves them. Only then does any communication go out.

---

## 9. Live Monitoring

### What Happens When a New Report Drops

```
Ministry uploads PDF/CSV to the inbox folder
              │
              ▼ (within 60 seconds)
Inbox watcher wakes up
              │
              ▼
Classify → extract → clean → silver → external → gold → score → profile
              │
        (takes ~111 seconds)
              │
              ▼
Diff predictions: which projects changed tier?
              │
         ┌────┴────┐
         │         │
    tier_up    tier_down
    alerts     alerts
         │
         ▼
Real-time SSE push → browser bell rings
              │
              ▼
Scout batch checks news for affected projects
              │
              ▼
If a prediction made 6 months ago has now come true:
   slip_realised alert → model accuracy card updates
```

### Alert Types

| Type | When it fires |
|------|--------------|
| `tier_up` | Project moved to a higher risk tier |
| `tier_down` | Project improved |
| `new_project` | Project appeared for first time |
| `slip_realised` | We predicted a slip and the report confirmed it |
| `pipeline_error` | The rebuild failed — old predictions still live |

---

## 10. Access Control

Enforced in the backend on every request. Officials sign in with an email and password (`/login`); the session is a
cookie the backend checks, an IPMD administrator approves access requests (`/signup`, `/admin`) and assigns the role
and scope, and every write is audited. The public needs no account. Details: `docs/ACCESS_CONTROL.md` (roles and
the endpoint matrix) and `docs/SECURITY.md`.

| Feature | Public | Agency | Ministry | IPMD |
|---------|--------|--------|----------|------|
| Home page | Yes | Own projects only | Own ministry | All |
| Project detail | Limited | Own only | Own ministry | All |
| AI assistant (chat) | Yes (public tools and outputs only, rate-limited) | Yes (scoped) | Yes (scoped) | Yes |
| Models page | No | No | No | No |
| Worker Console | No | No | No | No |
| Approve notices | No | No | No | Yes |
| Administration | No | No | No | Administrators |

The models page, the worker console, the job controls, the raw model numbers and the audit log belong to the hidden
developer account alone (created by the bootstrap from `.env.db`, never listed to administrators).

A project outside your scope returns **404 Not Found** (not 403) — no information leaks about its existence.

---

## 11. How to Run Locally

### Prerequisites

```bash
pip install -r requirements.txt
cd frontend && npm install
```

### Build the data pipeline (first time only)

```bash
# Extract and clean — reads PDFs, takes about 10 minutes
python -m pipeline.run extract

# Build silver and gold layers — about 30 seconds
python -m pipeline.run silver
python -m pipeline.run gold

# Train the model — about 2 minutes
python -m ml.train

# Score the current portfolio and build risk profiles
python -m ml.score
python -m ml.risk_profile
```

### Start the servers

```bash
# Terminal 1 — Backend API
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open `http://localhost:3000`.

### Environment Variables

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `LIVE_JOBS` | `1` | Set to `0` to disable background jobs (for tests) |
| `PARIVESH_SNAPSHOT` | `1` | Set to `0` to disable PARIVESH pulls |
| `BHOOMI_PULL` | `0` | Set to `1` to enable quarterly land register pulls |
| `WATCH_INTERVAL_S` | `60` | How often the inbox is checked (seconds) |
| `SCOUT_INTERVAL_H` | `24` | How often the news scout runs (hours) |

---

## 12. Key Numbers (Current State)

| Metric | Value |
|--------|-------|
| PDFs processed | 262 |
| Project rows extracted | 165,000+ |
| Stable project keys (PRJ-) | 6,253 |
| Portal projects matched | 1,767 / 1,775 |
| Silver panel rows | 73,167 |
| Current portfolio scored | 1,416 projects |
| Model PR-AUC (2-quarter, flash) | 0.771 |
| Model PR-AUC (4-quarter) | 0.860 |
| Critical tier | 70 |
| Watch tier (no completion date) | 347 |
| PARIVESH proposals linked | 470 |
| Land-linked projects (29 states) | 412 |
| Backend tests passing | 264 |
| Full rebuild time | ~111 seconds |
| API response time | 2–13 ms |

---

## 13. Glossary

| Term | Meaning |
|------|---------|
| **PRJ- key** | A stable project identifier that works across all 20 years of reports |
| **Silver layer** | Cleaned, typed, quarantine-filtered rows — one per project per quarter |
| **Gold layer** | Point-in-time features ready for ML — no future data allowed |
| **PR-AUC** | Area under the Precision-Recall curve. Measures ranking quality. 1.0 = perfect, 0.5 = random |
| **Slip** | A project's expected completion date has been pushed back |
| **Tier** | Risk category: Critical / High / Medium / Low / Watch |
| **SHAP** | A method that explains why the model gave a project its score |
| **Analogue** | A past project that looked similar to this one and eventually slipped |
| **PARIVESH** | Government portal for forest-clearance proposals |
| **Bhoomi Rashi** | Government portal for land-acquisition records |
| **S-curve** | The expected spend profile for a project (slow start, fast middle, slow end) |
| **SSE** | Server-Sent Events — real-time push from server to browser |
| **Quarantine** | Rows that failed data quality checks, set aside but not deleted |
| **Stale flag** | An issue flag from remarks that has not been seen in 4+ quarters |
| **Champion** | The currently deployed ML model — replaced only by a provably better one |
| **Backtest** | Training on past data, testing on the next period — simulates real-world use |

---

*Built for Smart India Hackathon 2026 · Branch `v2-early-warning` · All commits under prathameshDahe123*
