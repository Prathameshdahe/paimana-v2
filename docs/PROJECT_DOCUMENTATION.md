# PAIMANA Radar — Master Project Document

**Smart India Hackathon 2026 · Problem Statement 26103 · MoSPI / IPMD**

Single source of truth. Supersedes the separate presentation-script and
tech-stack-context files — everything from both is folded in here.

Last updated: 2026-09-22.

---

## 0. Where we actually stand, in one paragraph

The data pipeline and the frontend dashboard are real and working: 300 real
MoSPI projects, cleaned with a verified before/after fix (sector
contradiction 70–100% → 0–26%), a live map, risk triage, an early-warning
inbox, a rule-based chat assistant. What is **not** built yet is the thing
that actually answers the problem statement: a trained model that predicts
a **future** slip, not a heuristic score built from numbers the agency
already reported. That is the next and most important build task —
everything else on top (workers, RBAC, Scout) is secondary to getting that
one thing right and honestly evaluated.

---

## 1. The pitch, updated

> **"Prediction is our foundation. Our differentiation is what happens
> after prediction: we find causes the CUF doesn't capture, we honestly
> benchmark AI against conventional statistics as the problem statement
> asks, and every AI-drafted action is routed through role-based human
> approval before it reaches a real official."**

### The three pillars (in this order — order matters for the pitch)

1. **Causes beyond the CUF, plus a CUF-gap finder** (answers PS clause c).
   Scout extracts source-backed cause tags (land, clearance, litigation,
   contractor, funds) from text the CUF doesn't structure, and a three-tier
   ablation measures whether that evidence actually improves prediction —
   producing a ranked list of fields MoSPI should consider adding to the
   form, with measured lift, not a guess.
2. **ML vs conventional statistics, honestly benchmarked** (answers PS
   clause b). LightGBM is compared against four baselines — trusting the
   reported date, earned-schedule extrapolation, reference-class
   forecasting, and logistic/Cox regression — on the same temporal split.
   If a simple baseline ties LightGBM somewhere, we say so.
3. **An AI monitoring cell with role-based human approval.** Five workers
   run the monthly monitoring cycle end to end; RBAC is not a login demo,
   it is the accountability chain that decides who may approve what the
   workers drafted.

Prediction of the next slip (§3) sits underneath all three as the
foundation they're built on — necessary, not sufficient, and not the part
we lead with.

---

## 2. The five AI workers

| Worker | Job | Output | Uses an LLM? |
|---|---|---|---|
| **Auditor** | Checks every monthly upload: stale repeated figures, progress moving backwards, spend exceeding cost, past-due dates, sector/state mismatches. This is where our existing PDF re-parse and provenance tiers (§5) already live. | Data-confidence score + a query list back to the agency. Staleness itself becomes a model feature. | Only to word the query in plain language |
| **Forecaster** | Runs the trained models — nothing else | Slip probability (6-month horizon), delay/cost as P50/P80 ranges, ₹ exposure | **Never** — every number here is model output |
| **Scout** | Reads what the CUF doesn't capture: report remarks, news, clearance/court items, for the top-priority projects only | Structured cause tags (land, clearance, litigation, contractor, funds, utility shifting) with a source link on every tag | Extraction/classification only, into a fixed schema |
| **Analyst** | Combines the Forecaster's numbers, SHAP, Scout's tags, and similar historical projects; clusters shared causes across projects | Project brief, a bottleneck list ("fixing one clearance unlocks N projects, ₹X Cr"), a ranked review-meeting agenda | Writes from computed facts, invents nothing |
| **Dispatcher** | Drafts the memo to the nodal officer, tracks the response, re-checks next month, scores past alerts against what actually happened | A draft awaiting human approval, follow-up status, a running model report card | Drafting only — never sends anything itself |

A dedicated **Worker Console** page (not built yet) should log what each
worker did this cycle, with evidence attached — this is what makes "five
AI workers" demonstrable instead of sounding like marketing copy over a
chatbot. Example of what it should show per worker: model/version used,
dataset, number of projects processed, number crossing the alert
threshold, timestamp.

**Boundary that must never blur:** trained models produce every number;
the LLM explains, classifies, and drafts language from those numbers — it
never invents a probability, a delay estimate, a cost figure, or a cause
without a source link, and it never sends anything without a human
approving it first. This is the answer to "aren't LLMs hallucination-prone"
— yes, which is why the LLM isn't the numerical engine.

---

## 3. How the real prediction is supposed to work

This is the part that doesn't exist yet and matters most.

### 3.1 The problem with what we had

The current composite risk score is a weighted sum of **already-reported**
cost overrun and delay. If a project's completion date was already revised
from June 2026 to December 2026, scoring it "high risk" is detection, not
prediction — the delay already happened and is sitting in the row we read
it from. Feeding `cost_overrun_pct` / `delay_months` *at the same period*
into a model as a feature is leakage; the model would just be reading the
answer off the row it's trying to score.

### 3.2 The fix: predict the *next* revision, not the current one

- **Grain:** one row = one project at one reporting period. The same
  project appears multiple times (Q1, Q2, Q3...), each row asking "given
  what was known at this point, what happened next?"
- **Label:** compare **consecutive** snapshots. Positive if, within the
  next 6 months, the completion date is pushed by **3+ months** or the
  anticipated cost rises by **5%+**. This needs no final project outcome —
  only two reports in sequence — so it's buildable today from the 2024-25
  quarterly panel (stable N-code project IDs), and extends naturally once
  more periods are linked (§8).
- **Leakage rule, enforced in code, not just documented:** a row predicting
  from the March report may use March progress, March expenditure, March
  dates, and anything calculated from *earlier* periods (past revisions,
  agency history). It may never use June's numbers, June's revision, or
  final completion data.

### 3.3 Features (all point-in-time safe)

- **Schedule physics:** % time elapsed vs. % physical progress, progress
  velocity across periods, the "optimism gap" (elapsed-time % minus
  physical-progress %), and the finish date implied by current pace vs. the
  reported date.
- **Money:** our existing Δ(P-F) disparity index, spending velocity.
- **History:** count of prior revisions, months since the last one.
- **Reporting behaviour:** from the Auditor (staleness, repeated figures).
- **Context:** sector, project type, size band, state, and the
  implementing agency's own past slip rate — computed only from periods
  *before* the one being scored.
- **Scout tags**, once Scout exists.

### 3.4 Models

- **LightGBM classifier** — slip probability. Chosen because the dataset
  is tabular (~9K rows scale), has missing values and categorical mixes,
  and gradient boosting handles that natively; a deep net here would be a
  buzzword, not a benefit.
- **LightGBM quantile regressors** — delay/cost as a P50/P80 range instead
  of false single-number precision.
- **Survival model** (Cox proportional hazards or Random Survival Forest)
  — time-to-completion, because most projects are still ongoing
  (censored — we don't know their eventual finish date yet, and pretending
  otherwise biases a plain regression).
- **Risk exposure = slip probability × remaining unspent cost** (the money
  still at stake, not the whole project value), shown as a separate number
  from **data confidence** (the Auditor's score) — never blended into one
  opaque figure.

### 3.5 Baselines (PS clause b — do not skip this)

Compare LightGBM against, on the *same* temporal split:

1. Trusting the agency's reported completion date as-is.
2. Earned-schedule extrapolation from observed progress.
3. Reference-class forecasting — the overrun distribution of similar past
   projects grouped by sector × type × size band (the method UK Treasury
   guidance uses for optimism bias in appraisal).
4. Logistic regression / Cox regression.

Report **PR-AUC**, **Recall@50** (of projects that truly slipped later, how
many were in our top-50 attention-budget list), and **lead time** (months
between our first alert and the agency's own eventual revision — the
single most important operational metric, and the one that makes the "early
warning" claim real). If logistic regression ties LightGBM anywhere, report
that plainly — the PS explicitly asks whether AI/ML gives *significant*
gains over conventional statistics, and an honest "not everywhere" answer
is a stronger research result than a rigged comparison.

### 3.6 Validation — chronological, not random

Random splitting leaks future project behaviour into training. Train on
older reporting periods, validate on a later period, test on the newest
held-out period — train on the past, test on the future, matching real
deployment. A gap/buffer between train and test at least as long as the
prediction horizon (6 months) avoids near-boundary leakage.

### 3.7 Three-tier ablation (PS clause c — this is what actually answers it)

Our earlier plan's "engineered extras" (velocity, Δ(P-F), agency history)
are still arithmetic *on CUF columns* — that doesn't answer clause (c) on
its own. The real three-tier test is:

1. **Tier 1:** raw CUF/QPISR fields only.
2. **Tier 2:** Tier 1 + engineered features (optimism gap, velocities,
   revision history, agency track record).
3. **Tier 3:** Tier 2 + Scout's external evidence (genuinely outside the
   CUF).

Measure the lift at each tier. That produces a real, defensible answer to
"which additional fields should MoSPI consider collecting" — a ranked list
with measured improvement, not an opinion.

### 3.8 Explainability

Once LightGBM is trained, run `shap.TreeExplainer` per project and replace
the current heuristic driver-picker (§5) with real per-feature
contribution weights. The frontend's SHAP waterfall UI does not need to
change shape — only where the numbers come from.

### 3.9 One data check to run before claiming it on a slide

Physical progress is often sparsely populated in project monitoring data,
which makes the "optimism gap" signal hard to use. Our QPISR-derived
2024-25 panel looks much better (early indication: see §6, 100% physical
progress in the 2024-25 Silver slice). Re-confirm this against the actual
training panel, not just the display dataset, before putting it on a slide.

---

## 4. RBAC — repurposed as governance, not a login demo

The problem statement already says PAIMANA has role-based access. Four
logins will not differentiate anyone tomorrow. What differentiates is what
the roles are *for*:

```
Worker drafts an action (query / memo / brief)
        ↓
RBAC determines who has authority to approve it
        ↓
IPMD Analyst · Ministry Official · Agency Official
        ↓
Approve / Edit / Reject
        ↓
Action executes (or doesn't)
        ↓
Next reporting cycle grades the old alert
```

| Role | Approves / sees |
|---|---|
| IPMD Analyst | Auditor queries, Dispatcher drafts, the model report card |
| Ministry Official | Sector brief, bottleneck list, review-meeting agenda |
| Implementing Agency | Its own project forecasts, responds to data queries, runs what-if |
| Public | A plain-language summary card — no drafts, no internal workflow |

Technical explanation for Q&A: JWT answers *who are you*; RBAC answers
*what are you allowed to do*. Authorization must be enforced again at the
FastAPI backend on every request — hiding a button in the frontend is not
the security model.

---

## 5. What is actually implemented today (verified, working)

### 5.1 Data cleaning pipeline

The raw MoSPI CSV extraction had `sector`/`state`/`agency` values from the
**wrong row entirely** — a PDF table-extraction bug upstream, not typos.
Verified against project-name keywords: 70–100% of rows contradicted their
own project name depending on fiscal year. Root cause, confirmed by reading
the actual PDF layout: the "Ongoing Projects" table prints State/Sector as
columns that only show text **when the value changes from the row above**,
sharing vertical space with wrapped project-name text — a naive line scan
can't tell a sector-column word from a project-name word that happens to
say "POWER".

**Fix, in order of trust** (`pipeline/clean_sector_state.py`):

1. **PDF word-position re-parse** (`pipeline/extract_pdf_context.py`) —
   reads words by x-coordinate (state column x0 < 70, sector 70–140,
   project ≥ 150), clusters wrapped labels by vertical proximity,
   forward-fills between changes, joins back by project code. Real ground
   truth, but only 5 source PDFs exist locally (2024-25's four quarters +
   one 2025-26 QR file) — ~9% of rows directly, propagated further via
   project_id reuse across periods.
2. **Cross-period majority vote** — mode of the raw value across a
   project's other periods in the same fiscal year.
3. **Name-keyword regex tagging** — 14 rules (`NH-`/`LANING`→Road
   Transport, `AIIMS`/`HOSPITAL`→Health, etc.), also derives `project_type`.
4. **Raw column value** — last resort.

Same bug independently found and fixed in `agency` (a project showed
agency `GUJARAT`, a state name, instead of `NPCIL`).

**Verified result** (sector, vs. project-name keyword check):

| Fiscal year | Before | After |
|---|---|---|
| 2024-25 | 70% contradiction | 26% |
| 2025-26 | 95% contradiction | 7% |
| 2026-27 | 100% contradiction | 0% |

Every row carries `sector_source`/`state_source` (`pdf_reparse` /
`cross_period_vote` / `name_keyword_rule` / `original_extraction`) — feeds
the frontend's data-confidence badge. Output:
`dataset/silver/project_monitoring_{FY}_clean.csv`. **Bronze CSVs never
modified.**

### 5.2 Frontend dataset generation

`pipeline/build_real_projects.py` reads the cleaned 2024-25 Silver file
(the best-quality slice — 100% cost data, 100% physical-progress, 91%
dates), takes the top 300 projects by anticipated cost, computes:

- **Composite risk score** (heuristic, not a trained model — see §3):
  percentile-anchored weighted blend, anchors are this dataset's real P95
  values (cost-overrun P95 = 81.4%, delay P95 = 75 months), not guesses.
- **Risk tier:** CRITICAL ≥ 60, WARNING ≥ 30, NORMAL below.
- **SHAP-style drivers** — heuristic, picked from a fixed cause list based
  on that project's real delay/overrun/disparity/sector values, **not
  random and not real SHAP** — explicitly a placeholder for §3.8.
- **Sector** canonicalized to a clean 16-value set (garbage like `"COAL
  1378NLCIL"` fixed, `"ROAD TRANSPORT"` / `"ROAD TRANSPORT AND HIGHWAYS"`
  merged).

Output: `frontend/src/mocks/real_projects.json` (300 real projects). The frontend
has zero fake/random project data left in it.

`pipeline/build_state_dots.py` places one scatter point per project inside
its real state polygon (shapely, seeded) for the map. Known limitation:
the boundary file predates Telangana's split from Andhra Pradesh and
Ladakh's split from J&K, so those dots land in the pre-split parent
polygon.

### 5.3 Frontend features

| Feature | Status |
|---|---|
| Home / landing page | Real — KPI ribbon, map, alert inbox |
| India choropleth map | Real — dot-density (one dot/project), hover-fills state by avg risk, click drills into Command Center pre-filtered, zoom locked to +/− buttons only |
| Top states by critical count | Real, fills the layout gap beside the map |
| Early Warning Inbox | Real data · Acknowledge is local state only, no backend yet |
| Command Center (`/command`) | Real — KPI ribbon, Urgency Matrix, Triage Register |
| Portfolio Urgency Matrix | Real — Recharts gradient-area chart, colored by risk tier, 300 points sorted by runway |
| Triage Register | Real — sector/state/project-type filters, all from real data |
| Project Studio | Real financial/date data, real S-Curve. **SHAP waterfall is heuristic, not real SHAP** |
| Data-confidence badge | Real — shows sector/state provenance tier with tooltip |
| Prescriptive What-If Sandbox | **Not wired** — mock surrogate coefficients |
| Audit Suite (benchmark + CUF) | **Not wired** — mock rows, waiting on §3.5/§3.7 real results |
| Chat assistant widget | Real but rule-based — keyword/filter engine over real data, not an LLM yet |
| Role-based login | **Not built** |
| AI workers (Auditor/Forecaster/Scout/Analyst/Dispatcher) | **Not built** |
| Worker Console | **Not built** |

`riskPalette.ts` is the single source of truth for risk-tier colors,
shared by the map and the Urgency Matrix.

---

## 6. Data reality — know this before training anything

- **2005-06 to 2009-10** (Monthly): sector 85–96% populated; state **0%**.
  Twenty years stale, only useful as long-run base rate.
- **2021-22 to 2023-24** (Quarterly, hex-hash IDs): extraction mostly
  failed — sector/state 0%, most financials under 15% filled.
- **2024-25** (Quarterly, N-code IDs): best slice — 100% cost, 100%
  physical progress, 91% dates. Current modelling backbone.
- **2025-26** (mostly Flash Reports): financials sparser (33–36%); only
  one PDF available locally to re-parse.
- **2026-27** (Flash Reports): sector 0% populated.
- **No stable project ID across fiscal years** — format changes per era
  (hex hash → `N########` → bare numeric). Multi-year history needs
  fuzzy name-matching (§8), not built yet.
- Real percentiles used for the current heuristic formula (2024-25,
  cleaned): `cost_overrun_pct` P95 = 81.4%, `delay_months` P95 = 75.

---

## 7. The presentation (6 slides, SIH 2026 fixed template)

### 7.1 The one line to memorize

> "PAIMANA shows which projects are already in trouble. Radar finds why —
> including causes the CUF can't see — tells MoSPI which fields to add,
> honestly benchmarks AI against conventional statistics, and routes every
> AI-drafted action through the right official for approval."

### 7.2 Slide-by-slide

1. **Title** — SIH26103, Smart Automation, Software, team.
2. **Proposed Solution** — the pitch line + the three pillars (§1) + a short
   "what already exists elsewhere vs. what Radar adds" strip. Do **not**
   put "predicts before it's reported" as a uniqueness card — lead with the
   three pillars instead.
3. **Technical Approach** — see §7.3, the redesigned flow diagram is the
   hero element.
4. **Feasibility & Viability** — what's already built (§5): sector fix
   70–100%→0–26%, 300 real projects live. Then risks + mitigations: no
   final outcomes → next-slip labels need only consecutive reports;
   hallucination → LLM never produces numbers, every tag sourced, human
   approves; noisy news → Scout runs on top-50 only, cached.
5. **Impact** — 1,981 projects, 17 ministries, 22 sectors, ₹37.13L Cr →
   ₹42.78L Cr (≈₹5.65L Cr, ~15%, escalation). Plus: the CUF-gap
   recommendation MoSPI can act on directly.
6. **References** — PS + PAIMANA reports; Flyvbjerg on reference-class
   forecasting; LightGBM; SHAP; conformal prediction; earned schedule.

### 7.3 Slide 3 — the flow diagram to build

Replace the current four-paragraph-box layout with one operating pipeline,
technology pills attached to each stage, and the RBAC gate given the most
visual weight (this is the single biggest visual upgrade to make):

```
        MoSPI / PAIMANA (CSV · QPISR · Flash)
                     │
                     ▼
              ┌─────────────┐
              │   AUDITOR   │  Python · pdfplumber · Pandera
              │ Validate ·  │
              │ Data conf.  │
              └──────┬──────┘
                     ▼
         Bronze → Silver → Gold          DuckDB · Parquet · RapidFuzz
         (point-in-time-safe panel)
                     │
                     ▼
              ┌─────────────┐
              │ FORECASTER  │  LightGBM · scikit-learn · lifelines
              │ Slip % ·    │
              │ P50/P80     │
              └──┬───────┬──┘
                 ▼       ▼
           ┌─────────┐ ┌─────────┐
           │  SHAP   │ │  SCOUT  │  SHAP · MLflow  |  GDELT/RSS · Ollama
           │ model   │ │ external│
           │  WHY    │ │  WHY    │
           └────┬────┘ └────┬────┘
                 └────┬─────┘
                       ▼
              ┌─────────────┐
              │   ANALYST   │  LangGraph · Ollama · Pydantic
              │ Brief ·     │
              │ Bottlenecks │
              └──────┬──────┘
                     ▼
              ┌─────────────┐
              │ DISPATCHER  │
              │ Draft memo  │
              └──────┬──────┘
                     ▼
        ╔═══════════════════════╗
        ║  🔐 RBAC + HUMAN      ║   FastAPI · PostgreSQL · JWT/OAuth2
        ║     APPROVAL          ║
        ╚═══════════╤═══════════╝
                     ▼
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
    IPMD          Ministry       Agency
   Analyst        Official       Official
       └─────────────┼─────────────┘
                     ▼
           ACTION + FOLLOW-UP + DASHBOARD      React · Recharts
                     │
             next reporting cycle
                     │
                     └──────────────► back to AUDITOR
```

Design notes carried over from the review of this slide:

- Color by responsibility, not one flat blue: data=blue, prediction=purple,
  intelligence/Scout=orange, action=coral, human-approval=green,
  backend=navy.
- Give SHAP and Scout equal visual weight as a branch that **converges** at
  Analyst — one answers "why did the model say so", the other "what does
  the CUF not capture" — don't collapse them into one box.
- Small badge somewhere on the slide: **"LLM never generates a prediction
  number."**
- Small badge cluster: 🕒 6-month target · 🔒 leakage-safe · ⏳ temporal
  split · 🎯 PR-AUC/Recall@50/lead-time · 🧪 3-tier ablation.
- One small screenshot of the real, working dashboard in a browser frame,
  labeled "working prototype," with a badge "300 real projects · real
  MoSPI data" — diagrams alone can look purely hypothetical next to a
  team with a live demo.
- Left rail: 6 compact tech groups (Data / ML / AI Cell / Backend /
  Security / UI+Deploy), not a 20-library laundry list — keep the full
  list in this document, not on the slide.

### 7.4 Rules — do not say these tomorrow

1. No fake numbers — never invent an accuracy/PR-AUC before the backtest
   exists. State the *metric* you'll report, not a value.
2. Never say "the LLM predicts risk." Correct sentence: "the model
   predicts; the LLM explains."
3. Don't name or attack any competing team/repo on a slide.
4. Don't say "other teams' data is wrong." Say "we validate every field
   against the source PDF with provenance" — the sector/state bug was in
   *our own* CSV extraction step, not a claim about anyone else's data.
5. Don't promise satellite monitoring or live clearance-portal
   integration as anything but future scope.
6. Don't call it "just a dashboard" — the dashboard is the surface, the
   monitoring cycle is the product.

### 7.5 Judge Q&A — the ones that matter most

**"PAIMANA already shows delayed projects. What's new?"** → PAIMANA shows
delays already reported; we predict the *next* slip before the agency
reports it, explain the cause, and route follow-up through the right
official — detection vs. prediction plus action.

**"What's your model accuracy?"** → Be honest: not trained yet this round.
State exactly how it will be measured — PR-AUC, Recall@50, lead time, on a
strict time-based split — and that the pipeline and real data already
exist.

**"Why LightGBM, not deep learning?"** → Tabular data at ~9K-row scale;
gradient boosting handles missing values and mixed types natively, trains
in seconds, explains itself via SHAP. Deep learning here would be a
buzzword, not a benefit.

**"Only five quarters of data — enough?"** → Thin, which is why the label
combines date-slip OR cost-rise for more positive examples; 2024-25 is
very complete (100% cost, 100% physical progress, ~91% dates) so training
starts there, and the archive can extend backward once cross-year linkage
(§8) is built.

**"Why should I trust an LLM's prediction?"** → You shouldn't, and it
doesn't — LightGBM produces every number; the LLM only explains, classifies
with a source link, and drafts. Delete the LLM and the predictions don't
change.

**"Which LLM, does it need the cloud?"** → A small open-weight instruct
model (Qwen or Gemma class, ~4B, quantized) run locally through Ollama.
No API keys, no data leaving the network — the PS asks for open source
tools; this is open source end to end. (Pick the current best small
Qwen/Gemma instruct model at build time — don't hard-code an old name.)

**"What's built vs. left?"** → Built: data pipeline with field-level
provenance, dashboard, Command Center, early-warning inbox — 300 real
projects. Next, in order (§9): label set + temporal split, baselines,
LightGBM + real SHAP, then the five workers, then Scout, login last.

**"What are your limitations?"** → Three, said plainly: five quarters of
history is thin (mitigated by the label design and archive extension);
causes like land disputes aren't in the form, which is exactly why Scout
exists but depends on public reporting quality; past revisions predict
future revisions but don't *explain* them — every alert pairs SHAP with
sourced Scout evidence, and a human decides.

---

## 8. What's planned but not yet built

- **Real trained models** (§3) — the single highest-priority item.
- **Gold feature layer** as its own file (`dataset/gold/features_2024-25.parquet`)
  — currently these are computed inline in `build_real_projects.py`, not
  persisted separately; training and the frontend generator should read
  one shared feature definition, not two.
- **Real SHAP** (§3.8), replacing the heuristic driver picker.
- **Scout, Analyst, Dispatcher, Worker Console** — not started.
- **FastAPI backend** — frontend is offline-first today; contracts
  (`frontend/src/contracts/*.ts`) already define the response shape a real API must
  match, so hooks swap in without frontend changes. Planned endpoints:
  `GET /api/projects`, `GET /api/projects/{id}`, `GET /api/states`,
  `GET /api/alerts`, `GET /api/projects/{id}/forecast`,
  `GET /api/projects/{id}/explanations`, `GET /api/projects/{id}/evidence`,
  `POST /api/sandbox`, `POST /api/chat`, `POST /api/auth/login`,
  `POST /api/worker-runs`, `POST /api/approvals`, `POST /api/dispatch`.
- **PostgreSQL** for application data (predictions, alerts, worker runs,
  approvals, evidence, users) — DuckDB/Parquet stays for the analytical
  Bronze/Silver/Gold side; they serve different jobs.
- **Cross-year project linkage** (§8.1) — needed for real multi-year
  trend/history features.
- **Role-based login** — deferred, not forgotten.
- **Ollama** — not installed in this environment yet; installing and
  pulling a model is a concrete next step, not a research question.

### 8.1 Cross-year linkage method (when built)

`project_name_norm` exact match first, then token-Jaccard ≥ 0.8, within
matching sector/state, for candidate lineage across the hex-ID / N-code /
numeric-ID eras. Don't auto-merge ambiguous matches.

---

## 9. Build order

Prediction foundation first — everything else depends on it existing and
being honestly evaluated before it's wrapped in a worker/UI layer.

**Phase 1 — Prediction foundation:** project-period panel → cross-year
linkage where feasible → future-slip labels → leakage-safe Gold features →
temporal train/test split → simple baselines → LightGBM → evaluate → SHAP.

**Phase 2 — Monitoring workers:** Auditor → Forecaster → Worker Console →
Analyst → Dispatcher.

**Phase 3 — External intelligence:** Scout → evidence storage → cause
tagging → the Tier-3 ablation.

**Phase 4 — Backend:** PostgreSQL → FastAPI → model serving → worker
orchestration → approval workflow.

**Phase 5 — Frontend integration:** real APIs → forecast views → SHAP
views → Worker Console UI → Approval Inbox → model report card.

**Phase 6 — Governance:** JWT → role scopes → audit logs → public/private
views.

**Phase 7 — Deployment:** Docker Compose → local Ollama → scheduled
monthly pipeline → end-to-end demo rehearsal.

---

## 10. Full tech stack (all open source)

| Layer | Tools |
|---|---|
| Data engineering | Python, pandas/Polars, pdfplumber, DuckDB, Parquet, RapidFuzz, Pandera |
| ML | LightGBM, scikit-learn, statsmodels, lifelines/scikit-survival, SHAP, MAPIE, Optuna, MLflow |
| AI workers | Ollama, current best small Qwen/Gemma instruct model, LangGraph (fixed state machine, not free-roaming agents), Pydantic-constrained JSON, GDELT/RSS |
| Backend | FastAPI, PostgreSQL, SQLAlchemy, JWT/OAuth2 + RBAC |
| Frontend | React 19, Vite, TypeScript, Tailwind, Recharts, TanStack Query (already in place) |
| Deploy | Docker Compose, fully on-prem — no project data leaves the network |

Model-size rule of thumb: ~0.6GB per billion parameters at Q4_K_M plus
20–30% headroom. A 4B instruct model is comfortable on a 6GB laptop GPU;
7–8B is tight. Keep a CPU fallback path for demo-critical steps.

---

## 11. Suggested repository structure (once backend/ML phases start)

This was the original plan. The layout in use today is described in the root `README.md`.

```
radar/
├── data/{bronze,silver,gold,external}/
├── pipeline/{ingestion,extraction,cleaning,validation,linkage,feature_engineering}/
├── ml/{labels,features,baselines,lightgbm,survival,calibration,explainability,evaluation,registry}/
├── workers/{auditor,forecaster,scout,analyst,dispatcher}/
├── backend/{api,models,schemas,services,auth,db}/
├── frontend/  (existing dashboard, extended with Worker Console + Approval Inbox)
├── tests/
├── docker/
└── configs/
```

---

## 12. Honest scorecard against the PS's expected outcomes

| PS outcome | Status |
|---|---|
| (a) Cost Overrun Prediction Model | Heuristic today — real model is Phase 1, §9 |
| (b) Time Overrun Prediction Model | Same — heuristic, not yet trained |
| (c) Project Risk Scoring Framework | **Real**, formula in §5.2 |
| (d) Early Warning Alert System | **Real** — Inbox + map, real thresholds |
| (e) Benchmarking & Comparative Analytics | Mocked — needs the real §3.5 baseline run |
| (f) Cost Escalation Driver Analysis | Heuristic — needs real SHAP, §3.8 |
| (g) AI-Powered Monitoring Dashboard | **Real** |
| (h) LLM-Enabled Project Intelligence Assistant | Rule-based today, Ollama planned |
| (i) Documentation & Deployment Framework | This document; Docker deployment not yet built |

---

## 13. Known limitations — disclosed, not hidden

- Sector/state cleaning residual error: 26% (2024-25) / 7% (2025-26) rows
  still contradict the keyword check — partly real remaining error, partly
  an imprecise checker.
- `overrunForecastCr` reads ₹0 for many projects because `cost_revised` is
  often missing and falls back to `cost_anticipated` — genuine source
  sparsity, why the Urgency Matrix plots risk score instead.
- One project (`N02000010`, KAKRAPAR) shows a `+174 month` predicted delay
  — a real but extreme outlier from date-field parsing, not manually
  corrected.
- 2025-26/2026-27 Flash Report PDFs were never supplied locally, so the
  PDF re-parse fix only reaches 2024-25 directly and a fraction of 2025-26.
- There may be a public project monitoring archive with QPISR PDFs going
  back to 2001. Worth checking manually (this environment couldn't fetch
  it) before claiming our archive is limited to five quarters on a slide.
