# PAIMANA Early-Warning System: Implementation Guide v2

Everything from the clean CSVs to the dashboard. Each section says what exists,
what to build and how we know it is done. Part A records the decisions taken
for the v2 build; Part B is the team guide the build follows.

---

## Part A. v2 build decisions (Sep 2026)

### A.1 Scope of this round

All four segments are in scope, built in this order:

1. **Data foundation.** Stable `PRJ-xxxxxx` keys, silver observations panel,
   quarantine, coverage audit.
2. **Gold + ML.** Point-in-time features and labels with a leakage test,
   baselines vs LightGBM with a rolling backtest, rank-based tiers.
3. **External factors.** Replaces the sandbox (see A.4).
4. **Serving + live tracking.** Paginated API, report watcher, news scout,
   alerts, prediction log.
5. **Cross-project pages.** Agency Performance Matrix, Bottleneck
   Intelligence, External Evidence Radar, Models page.

### A.2 Stack (lightweight)

| Guide says | v2 uses | Why |
|---|---|---|
| Parquet + DuckDB | same | analytics layer, unchanged |
| Postgres serving | SQLite (`database/paimana.db`) for app state, DuckDB over Parquet for reads | runs on one laptop for the demo, no Docker |
| Redis cache | in-process cache keyed by file mtime / asof | one backend process |
| arq / Celery queue | in-process background scheduler started with FastAPI | same jobs, no broker |
| MLflow | file registry: `model/registry.json` + `model/runs/<run_id>/` with params, metrics, artifacts | same fields as an MLflow run; MLflow can be added later without changing callers |
| Ollama | LM Studio (OpenAI-compatible, local, already used by `llm/`) | still no proprietary API |

### A.3 Identity layer

`pipeline/identity/` is the resolver from the identity-module handoff. Rules:

- Keys come from a persisted map (`dataset/silver/identity/projects.parquet`,
  `aliases.parquet`) that is read before every build and only appended.
- Rows are sorted by (period, report type, row id) before minting, so a
  from-scratch rebuild reproduces the same keys.
- `merge(loser, winner)` keeps the loser with `merged_into`; `canonical()`
  follows the chain. Nothing is deleted.
- A printed code is strong evidence, not identity. Code match plus
  contradicting name gives an own key flagged `code_conflict`.
- Only accepted links may fill a project's stored attributes.
- `manual_links.csv` with a key or `NEW` overrides the resolver.
- `source_row_id` must be stable under re-extraction, so it is a hash of the
  row's printed content plus an occurrence counter, not a row position.

### A.4 External factors (replaces the sandbox)

Idea from Garvit: the reason projects slip is often a hidden factor that the
PAIMANA/CUF numbers do not show until the next revision, typically land
acquisition or forest clearance. We surface those factors first.

Sources:

| Source | File | Grain | How it links to projects |
|---|---|---|---|
| Parivesh forest-clearance rules | `dataset/raw/external/parivesh_fc_scenarios.csv` | 27 approval scenarios (violation, shape, form, area band, category) with approving authority, authority level 1-4, PSC/REC/FAC/site-inspection gates and a complexity score | Rule-based: each project is mapped to the scenarios it can fall under from its sector (linear vs non-linear, mining), any forest area in its remarks, and violation mentions. Output is the expected and worst-case clearance complexity and the approving authority. |
| Bhoomi Rashi land acquisition (Maharashtra NH) | `dataset/raw/external/land_acquisition_maharashtra.csv` | 347 NH stretches: highway, chainage, districts, villages, parcels, area, notification span, acquisition complexity 0-5 | Road projects matched to stretches of their own state on NH number in the project name, then district. More states: drop Bhoomi Rashi exports into `dataset/raw/external/bhoomi_rashi/` (parsed by `pipeline/bhoomi_rashi.py`). A state with no land data is `unknown`, never `clear`. |
| Report remarks | `remarks` in the clean project rows | free text per project per report | Keyword taxonomy (land, forest/environment clearance, litigation, contractor, funding, utility shifting, R&R, inter-agency, law and order, weather) gives `project_events` with first seen, last seen and open/closed status. |
| News scout | Google News RSS, PIB RSS | articles | Entity-linked to projects by name tokens plus location; ambiguous links go to an unlinked pool. |

The External Factors page shows, per factor, the projects where the factor is
flagged and the CUF numbers do not show a slip yet. That is the early notice.

### A.5 Git workflow

Work happens on branch `v2-early-warning`, one commit per unit of work, about
30 commits in total. The team pushes manually after each segment:

```
git push -u origin v2-early-warning
```

Merge into `main` with a merge commit (not squash) so the history is kept.

---

## Part B. Team guide

### 0. What changes with the new dataset

| Before | After |
|---|---|
| One snapshot (April 2026), labels derived from the same fields as features | 20-year panel, features at period t, labels from period t+h |
| Rule-heavy risk score, 60-90% of portfolio red | Calibrated LightGBM vs statistical baseline, tiers sized to officer capacity |
| Sandbox sliders (add money / add time) | AI prediction panel + risk-profile checklist + three cross-project pages |
| CSVs read straight into the app | Parquet + DuckDB for analytics, serving store for the app, background jobs for batch and scouting |
| "We improved the AI" | Prediction log + backtests that prove it |

The corrections from the second review are accepted: `clean/` is parsed data,
not trusted Silver; entity resolution is the gate between them; split years
come from the coverage audit, not from a guess; velocity is a feature, not a
label; LightGBM is the primary model; the "8,435 projects" figure is quoted
only after resolution.

```
raw/ PDFs + portal CSVs
  -> clean/ parsed CSVs
  -> entity resolution + DQ gate
  -> silver/ Parquet observations panel   (+ silver/quarantine)
  -> gold/ features, labels, benchmarks
  -> baselines vs LightGBM, backtests
  -> gold/predictions
  -> serving store -> API -> dashboard
scout workers (news, PIB, Parliament, Parivesh) -> signals -> serving store
```

### 1. Data layers

#### 1.1 Folders and rules

```
dataset/
  raw/        Bronze. PDFs, portal CSVs, external CSVs. sources.csv lists
              filename, report_type, period, sha256, pages. Never edited.
  clean/      Parsed output of the extractors. Read-only after each build.
              Contains dq_flags but not entity resolution.
  silver/     Trusted. Parquet only. Entity-resolved, quarantined, one panel.
  gold/       Derived. Features, labels, benchmarks, predictions. Versioned.
```

Only `silver/` and `gold/` are read by training and the app. `clean/` exists so
extraction bugs and resolution bugs can be fixed independently.

#### 1.2 Silver build (one command)

**Step 1. Type and convert.** Every clean CSV to Parquet with explicit dtypes
(dates as dates, money as float64 in Rs Cr, progress as float 0-100). Anything
that fails to parse becomes null plus a dq flag, never a silent zero.

**Step 2. Entity resolution** to `silver/identity/`.

| column | meaning |
|---|---|
| source_report_type, source_period, source_row_id | where the row came from |
| source_name, source_code | as printed |
| canonical_project_key | PRJ-xxxxxx, stable across reports |
| match_score | 0-1 |
| match_method | code_exact, name_attrs, code_conflict, manual, new, alias_cache |
| review_status | accepted, review |

Thresholds: >= 0.92 accepted, 0.75-0.92 review, < 0.75 new project. Never
auto-merge a review row.

**Step 3. Quarantine** to `silver/quarantine/<rule_id>.parquet`. Rules:
progress > 100 or < 0, negative cost/expenditure, expenditure > 3x revised
cost, completion before sanction, placeholder dates (01/1999), duplicate
(key, period). Quarantined rows keep reason and source_row_id. They are
excluded from training and shown in the app as a data-quality note, never
deleted.

**Step 4. The panel** to `silver/observations.parquet`. One row per
canonical_project_key x quarter.

| column | rule |
|---|---|
| period | quarter start date |
| period_type | monthly, quarterly, flash (source cadence) |
| source_doc_id, source_page | provenance |
| original_cost_cr, anticipated_cost_cr, expenditure_cr | last valid observation in the quarter, not the mean |
| physical_progress_pct | last valid observation in the quarter |
| scheduled_completion, anticipated_completion | last valid |
| status, agency, ministry, sector, state | last valid; sector/state via the reference mapping tables |
| obs_count_in_quarter | 0-3 |
| months_since_last_obs | freshness |
| dq_score | 1 - (flags / max flags) |

Also `silver/project_master.parquet` (one row per key: first_seen, last_seen,
n_obs, sanction date, last status, agency, ministry, sector, state) and
`silver/sector_context.parquet` from performance_sector_monthly (per sector x
quarter: target/actual ratio, YoY output change, 4-quarter trend).

**Step 5. Coverage audit** to `silver/coverage.parquet` plus
`silver_manifest.json`. Period x field completeness, row counts, quarantine
counts, resolution stats (accepted / review / new). This table decides the
train/validate/test windows in section 3.

Done when: every current portal project maps to exactly one key; no key has
two rows in one quarter; the coverage table exists; the manifest carries
silver_version and run_id.

### 2. Gold: features and labels

#### 2.1 Point-in-time rule

`build_features(cutoff)` may read only observations with period <= cutoff.
`build_labels(cutoff, h)` reads period == cutoff + h for the same key. A unit
test asserts the feature frame's max period <= cutoff. Agency and sector
statistics are recomputed per cutoff from history <= cutoff, so a 2019 row
never sees 2024 agency behaviour.

#### 2.2 Feature groups (at project x t)

| Group | Features | Source |
|---|---|---|
| State (CUF) | progress %, elapsed ratio, cost variation % (anticipated/original - 1), expenditure ratio, burn gap (exp ratio - progress), SPI, months to scheduled completion, revisions so far, months since last revision, cost band | observations |
| Dynamics | progress velocity 2q / 4q, spend velocity, acceleration, stagnation quarters (velocity ~ 0), velocity vs sector median (flag) | observations |
| Context | expected progress from the sector S-curve at this elapsed ratio (fitted on completed projects <= cutoff), deviation from it, sector_context, agency slip rate and cost-optimism (shrunk toward sector mean), ministry, state | silver |
| Freshness | obs_count_in_quarter, months_since_last_obs, dq_score | silver |
| External | open event counts by category (land, forest, litigation, ...), forest-clearance complexity, land-acquisition complexity, open signal counts in last 2 quarters, days since first negative signal | project_events, external tables, signals |

The groups are the ablation for PS dimension (c): CUF-only, then +Dynamics,
then +Context, then +External.

#### 2.3 Labels at horizon h (2 and 4 quarters)

| label | definition |
|---|---|
| y_date_push | anticipated_completion(t+h) - anticipated_completion(t) >= 3 months |
| y_cost_rev | anticipated_cost(t+h) >= 1.05 x anticipated_cost(t) |
| y_months | months slipped by t+h (regression) |
| y_cost_pct | cost change % by t+h (regression) |

Rows without an observation at t+h are unlabelled and excluded.

#### 2.4 Gold files

```
gold/
  features.parquet          labels_h1.parquet .. labels_h6.parquet   (one per quarter ahead to 18 months)
  sector_scurve.parquet     agency_stats.parquet
  predictions_<model_version>_<asof>.parquet
  manifest.json             gold_version, silver_version, cutoffs, row counts, feature list
```

Done when: the leakage test passes; the feature list is in the manifest; a
labelled row count per cutoff is printed and roughly stable.

### 3. Models and evaluation

#### 3.1 Windows

Read `silver/coverage.parquet`. Train on the earliest periods where sector,
cost, progress and completion fields are >= 80% complete; validate on the next
block; hold out the newest reliable block. Write the chosen cutoffs into
`gold/manifest.json`. Never hard-code years.

#### 3.2 Models

| Role | Model | Why |
|---|---|---|
| Naive baseline | "slipped last period, slips next" | the floor everything must beat |
| Statistical baseline | logistic regression (classification), OLS / quantile regression (regression), same features, standardised | PS dimension (b) |
| Current rule score | the existing composite | shows what the ML adds over rules |
| Primary | LightGBM classifier per label; LightGBM regressor for months and cost %; quantile (5/50/95) intervals | tabular, missing values, small data |

#### 3.3 Backtest

Rolling origin: for each cutoff quarter in the validation block, train on
<= cutoff, predict cutoff+h, score. Metrics: PR-AUC, Brier, calibration error;
Recall@50 and Recall@100; lead time; MAE (months, cost %) and interval
coverage; deltas vs each baseline (the (b) table) and across feature groups
(the (c) table).

#### 3.4 Registry

One run per (model, gold_version, cutoff) with params (feature list,
hyperparameters, silver/gold versions), metrics, and artifacts (model file,
SHAP summary, calibration table, backtest table). Champion/challenger: a
candidate replaces the champion only when it beats it on the same folds on
PR-AUC and calibration; the decision is recorded in the registry. A run on a
new gold version or new folds first re-scores the champion's own configuration
(type, feature list, params) as `<type>_incumbent`, and a new configuration has
to beat that; nothing else takes over across gold versions or folds.
`python -m ml.registry revert <target>` undoes a promotion that a corrected rule
no longer supports.

#### 3.5 Scoring the current portfolio

`score(asof)` builds features at the latest period, loads the champion, writes
`gold/predictions_<mv>_<asof>.parquet`: probabilities, expected months and
cost %, intervals, SHAP top-5 with values, and a risk tier. Tiers by rank, not
by threshold: Critical = top 5%, High = next 15%, Medium = next 30%, Low =
rest. The rule-based stagnation flag (no progress 2+ quarters) is a badge
only: in the backtest flagged projects slipped at or below the base rate, and
lifting them made every tier less precise. A project with no anticipated
completion date has no date-based score and sits in the Watch tier, ordered
by flagged checklist rows and then P(cost revision); that order is not
validated.

Validation and promotion (ml/backtest.py, ml/registry.py): besides the
quarterly-era validation folds (all before 2025-07), every cutoff from 2025-07
with 100+ labelled rows forms a flash block (the report format live scoring
uses; for the 2-quarter targets it includes the test cutoff). The two blocks
share no cutoff. A challenger is promoted only when its within-cutoff PR-AUC
(each fold's own, averaged: a score is only ranked within its as-of date) is
not lower on either block and beats the champion on one by twice that block's
measured seed sd. Each pooled metric also has a not-yet-due slice
(anticipated completion after t + h). Only the cost revision is
Platt-calibrated; calibrating the date targets and training h4 from 2014 both
lost on the flash block and were reverted.

Model upgrades (Sep 2026, docs/MODEL_UPGRADES_2026-09.md): candidates are
measured with `python -m ml.experiment <candidate>`: 3 seeds, the validation
and flash blocks, a paired project bootstrap CI, and the promotion rule plus a
CI-above-0 guard. Of 19 candidates one shipped, through
`backtest.TARGET_PARAMS`: y_cost_rev_h2 trains with regularised params
(learning rate 0.02, 63 leaves, lambda 20, 150 trees; within-cutoff PR-AUC
0.175 -> 0.182 validation, 0.123 -> 0.160 flash, 3 seeds), provisionally, with
a pre-registered check at the 2026-04 fold. An 8-quarter half-life for y_any_h4
shipped first and was reverted: its pooled gain came from score levels
following each fold's base rate, while it ranked worse inside 4 of 6
validation folds. y_any_h2, y_date_push_h2 and y_any_h4 keep their champions:
no feature family, tuning, weighting or ensemble beat them on both blocks. Every train
run writes `intervals.csv`, the p05-p95 coverage and pinball loss of the
served intervals (months: 0.915 validation, 0.883 flash). The served
model_version names every champion run, e.g.
`lgbm-any2q-20260927-222602+20260928-072744`.

### 4. Serving

#### 4.1 Tables (SQLite + Parquet)

| Table | Content |
|---|---|
| projects_current | latest report's projects, joined to canonical key |
| project_timeline | quarterly rows for current projects (from silver) |
| project_scores | tier, probabilities, months, cost %, intervals, SHAP JSON, asof |
| portfolio_aggregates | KPIs and tier counts by ministry / sector / state / asof |
| agency_stats | schedule and cost optimism bias, n, CI, trend |
| prediction_log | every scored (project, asof, model_version, outputs); realised outcome filled when the next report lands |
| model_registry | version, gold_version, metrics, champion flag, promoted_at |
| signals, signal_projects | scouted items, category, severity, source, date, link |
| project_events | delay reasons from report text and signals, category, authority, geography, status |
| bottlenecks | clustered events: category x authority x state, member projects, capital exposed |
| alerts, watchlists, audit_log | app state |

#### 4.2 Jobs

| Job | Trigger | Output |
|---|---|---|
| ingest_report | new PDF/CSV in raw/inbox | clean rows + sources entry |
| build_silver, build_gold | after ingest | parquet + manifests |
| score | after gold | predictions parquet |
| load_serving | after score | serving tables, cache purge, prediction_log realised outcomes |
| scout | nightly, or on demand | signals |
| classify_signal | after scout | category, severity, project link |
| cluster_bottlenecks | after classify | bottlenecks table |
| generate_brief | on project open, cached per (project, asof, model_version) | text with citations |

#### 4.3 API

```
GET  /api/portfolio?asof=&ministry=&sector=&state=     aggregates + top 20
GET  /api/projects?filters&sort=risk&page=&size=50      paginated slice
GET  /api/projects/{key}                                current row + scores + risk profile
GET  /api/projects/{key}/timeline                       quarterly history
GET  /api/projects/{key}/forecast                       fan chart + scenarios + analogues
GET  /api/projects/{key}/signals                        external evidence
GET  /api/projects/{key}/brief                          LLM brief (cached)
GET  /api/external/summary                              hidden-factor rollup
GET  /api/bottlenecks?category=&state=                  cross-project clusters
GET  /api/signals/feed?since=&category=                 radar feed + state heat
GET  /api/agencies/matrix                               optimism scatter
GET  /api/models                                        registry + backtest metrics
GET  /api/alerts                                        live alert feed
POST /api/alerts/{id}/ack, /api/watchlist               officer state
```

No screen ever requests more than one page.

### 5. Project page (replaces the sandbox)

#### 5.1 AI prediction panel

Tier, P(date push, 2q), P(cost revision, 2q), expected slip in months and
cost % with 90% intervals. Trajectory fan chart: progress and expenditure
history, forecast band for the next 4-8 quarters, sector S-curve as reference.
Three scenarios instead of sliders: continue current velocity; recover to
sector-median velocity; follow the agency's historical pattern. Analogue
projects: nearest 10 historical projects at the same stage and what happened
to them by t+4.

#### 5.2 Risk profile checklist

One row per risk dimension; each row has a state (flagged / clear / unknown),
one line of evidence, the source, and the date.

| Dimension | State from | Evidence line |
|---|---|---|
| Schedule slip | model P(date push) >= tier threshold | "P = 0.71; velocity 0.8%/q vs sector 2.1%" |
| Cost escalation | model P(cost rev) | "P = 0.44; cost variation already +18%" |
| Execution stagnation | rule: SPI < 0.1 at >= 30% elapsed, or the stagnation override's rule (no progress 2+ quarters) | "12% progress at 64% elapsed; no progress for 3 quarters" |
| Expenditure lag | burn gap < -15 or > +25 | "spent 61%, built 38%" |
| Repeated revisions | >= 2 revisions in history | "3 date revisions since 2021" |
| Sector headwind | sector_context trend negative | "sector output 9% below target, 3q declining" |
| Agency optimism | agency schedule bias > 25% | "agency timelines run 41% long on average, n=37" |
| Land acquisition | project_events / land table / signals | "NH-161: 1,699 parcels, notifications over 5 years" |
| Environment / forest clearance | project_events / Parivesh rules / signals | "linear >40 ha: MoEFCC, PSC + FAC + site inspection" |
| Litigation | project_events / signals | "court case mentioned in remarks, Mar 2026" |
| Contractor stress | project_events / signals | "contractor terminated, re-tendering" |
| Data staleness | months_since_last_obs > 3, dq_score < 0.7 | "no update for 2 quarters" |

Unknown is a valid state and is shown as such; an empty signal search is not
"clear".

#### 5.3 Brief

The LLM writes two paragraphs from the panel's numbers, the checklist, and
cited signals. A validator rejects any figure not present in the API payload.

### 6. Cross-project pages

#### 6.1 Bottleneck Intelligence

Group open events by (category, authority, state). A cluster becomes a
bottleneck when it holds >= 3 projects. Store member projects, capital exposed
(sum of anticipated cost), mean predicted slip, and the earliest first_seen.
Wording: "Blocking 14 projects worth Rs 42,000 Cr" is supported by the data;
"fixing it will speed up 14 projects" is a causal claim. Show "projects that
would be affected".

#### 6.2 External Evidence Radar

Alias generation, fetch (Google News RSS, PIB RSS), dedupe by URL and text
hash, entity-link (fuzzy name + location; ambiguous goes to an unlinked pool),
classify (category, severity 1-3), store. Feed cards on the left, state heat
on the right. For each signal show "external source date" next to "date the
CUF row changed"; a positive gap is the lead-time claim demonstrated.

#### 6.3 Agency Performance Matrix

Schedule bias = anticipated (or actual) duration / originally scheduled
duration - 1; cost bias = anticipated cost / original cost - 1. Per agency:
median and IQR, n projects, trend, capital under management. Shrink toward the
sector mean for n < 10; hide agencies with n < 5. Scatter with quadrants, n
and CI on hover.

### 7. Monthly run

A new report detected in `dataset/raw/inbox/` (sha256 not in sources) runs:
extract, clean, entity-resolve, quarantine, silver, gold, backtest champion
and challengers, score, load serving, fill realised outcomes in
prediction_log, raise alerts on tier changes. Idempotent on (report checksum,
period, pipeline_version).

### 8. Build order

| # | Milestone | Done when |
|---|---|---|
| 1 | Parquet + entity resolution + observations panel | portal projects map 1:1 to keys; coverage table exists |
| 2 | Gold features/labels with leakage test | test passes; manifest lists features and cutoffs |
| 3 | Baselines vs LightGBM, rolling backtest, registry | (b) and (c) tables exist; champion registered |
| 4 | Serving + jobs + cache; paginated API | portfolio, list, detail load under 300 ms |
| 5 | Project page: prediction panel, fan chart, scenarios, analogues, checklist | sandbox removed |
| 6 | Scout pipeline + Evidence Radar | linked signals; lead-time comparison visible |
| 7 | Agency Matrix + Bottleneck Intelligence | both pages read from serving tables only |
| 8 | LLM brief | validator rejects invented numbers |
| 9 | Models page | "improved since v3" is a screenshot, not a sentence |

### 9. Guardrails

- The frontend never receives a full table. Aggregates, one page, or one project.
- No proprietary LLM API. Numbers come from DuckDB/SQLite, language from the local model.
- Tiers by rank, not by fixed thresholds.
- Quarantine, don't delete. Unknown is a state, not "clear".
- Every number on screen can be traced: asof, model_version, gold_version, silver_version, source_doc_id, page.
