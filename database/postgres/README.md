# PAIMANA Radar — PostgreSQL & Data Engineering Handoff

## Adopted into PAIMANA (Segment 9, 2026-09-28)

This folder is Manamrit's PostgreSQL handoff (`PAIMANA_Postgres_Handoff_v1`), adopted as the app's database layer.
Credit and thanks to him for the schema design (ingest / core / ml), the five migrations and the data contracts
(`contracts.md`, `ml_db_handoff_contract.md`); his text follows unchanged below this section.

What changed on adoption:

- The five migration files under `migrations/versions/` are byte-identical to the handoff (their revision ids are
  the chain's history: `001_core_identity` → `84b98df29a61` → `b704a78e671f` → `004_model_artifact_checksum` →
  `005_ingestion_staging`). PAIMANA's own migrations continue the chain after `005_ingestion_staging`:
  `1f3a9c2d7b40` (the `app` schema: alerts, watchlists, news signals, research facts, second opinions, audit log,
  briefs, job runs, ingested sources), `2c8d4e6f1a57` (`app.users`, `app.sessions`, `app.signup_requests`,
  `app.login_attempts`), `3e5f7a9b2c68` (`app.rag_chunks` with pgvector, `app.rag_meta`), `4a6b8c0d3e79` (the
  served scores as columns of `ml.predictions`, `run_id` / `entry_id` / `feature_list_json` on `ml.model_registry`).
- `migrations/env.py` reads the URL from `backend/settings.py` (`DATABASE_URL`; his `DB_USER` / `DB_PASSWORD` /
  `DB_HOST` / `DB_PORT` / `DB_NAME` stay as the fallback), creates the schemas `ingest`, `core`, `ml` and `app` if
  they are missing before the first migration runs (the first migration creates tables in `ingest` and `core`
  without creating the schemas), and takes an advisory lock so two runners never migrate at once.
- `config.py` builds its engine from the same settings. The loader, script and check files are kept as he wrote
  them; they are his silver-CSV → staging → timeline flow and are not run by the app (`pipeline/serve.py` loads
  `core.*` and `ml.*` from PAIMANA's silver and gold Parquet instead: `python -m pipeline.run serve`).
- `alembic.ini` sits at the repo root with `script_location = database/postgres/migrations`.

How to run (from the repo root, with `.env.db` in place):

```
python -m alembic upgrade head      # build or update the whole schema (the backend also runs this at start)
python -m alembic current           # where the database is
python -m alembic downgrade -1      # undo the last migration
python -m alembic revision -m "..." # a new migration after the head
```

`docs/DATABASE.md` describes what lives in each schema, the one-time copy of the old SQLite state and backups.

---

## 1. Purpose

This package contains the PostgreSQL and data-engineering foundation built for the PAIMANA Radar early-warning prototype.

It is intended to let another developer or coding agent:

1. understand the database architecture,
2. recreate the PostgreSQL schema,
3. understand the ingestion and identity-resolution flow,
4. load trusted project history,
5. load ML model outputs,
6. query the database for backend integration,
7. continue the unfinished implementation without guessing.

This is **not the complete PAIMANA Radar application**.

It does not include the complete frontend, full data lake, production ML model, Scout subsystem, alert engine, or production deployment environment.

---

# 2. Core Architecture

The overall application architecture is:

```text
SOURCE DATA
    ↓
RAW / BRONZE
    ↓
CLEAN / SILVER
    ↓
IDENTITY + DATA QUALITY
    ↓
TRUSTED CORE HISTORY
    ↓
GOLD FEATURES / LABELS
    ↓
ML
    ↓
POSTGRESQL ML SERVING
    ↓
FASTAPI
    ↓
DASHBOARD
```

The main responsibility split is:

```text
Parquet / DuckDB
    = analytical and ML truth

PostgreSQL
    = application / serving truth

FastAPI
    = controlled API access

Dashboard
    = user interface
```

PostgreSQL is not intended to become another data lake.

---

# 3. Important Data Grain

The central historical unit is:

> One canonical project observed in one reporting period.

Conceptually:

```text
Project A
├── Apr 2024
├── Jul 2024
├── Oct 2024
├── Jan 2025
├── Apr 2025
├── May 2025
└── Jun 2025
```

This allows PAIMANA Radar to model how a project changes over time rather than treating every report as an unrelated record.

The trusted Core uniqueness rule is:

```text
(project_id, report_period)
```

---

# 4. What Is Included in This Handoff

The package should contain database-related code only.

Recommended handoff contents:

```text
PAIMANA_Postgres_Handoff_v1/
│
├── README.md
├── contracts.md
├── ml_db_handoff_contract.md        # optional ML-specific supplement
├── .env.example
├── alembic.ini
│
├── database/
│   └── postgres/
│       ├── config.py
│       ├── migrations/
│       ├── loader/
│       ├── scripts/
│       ├── queries/
│       ├── seeds/
│       └── tests/
│
└── data_requirements/
    └── README.md
```

`contracts.md` should be treated as the authoritative data contract.

If `ml_db_handoff_contract.md` is also included, it should be treated only as a more detailed ML-serving supplement and must not contradict `contracts.md`.

---

# 5. What Is NOT Included

Do not include:

```text
.env
real database passwords
PostgreSQL installation files
PostgreSQL data directories
__pycache__
*.pyc
database backups unless intentionally sanitized
whole dataset/
raw PDFs
frontend/
unrelated application workers
temporary logs
personal machine paths
random debugging outputs
```

The goal is to provide a reproducible database package, not a copy of one developer's machine.

---

# 6. Current Implementation Status

## Implemented

| Component | Status |
|---|---|
| PostgreSQL connection/configuration | ✅ Implemented |
| Alembic migrations | ✅ Implemented |
| Source document registry | ✅ Implemented |
| Load-run tracking | ✅ Implemented |
| Staging observations | ✅ Implemented |
| Data-quality validation | ✅ Implemented |
| Quarantine behavior | ✅ Implemented |
| Canonical project table | ✅ Implemented |
| Project identity mapping | ✅ Implemented |
| Trusted project timeline | ✅ Implemented |
| Timeline integrity audit | ✅ Implemented |
| Gold point-in-time features | ✅ Implemented |
| Six-month target generation | ✅ Implemented |
| Chronological ML dataset preparation | ✅ Implemented |
| ML model registry | ✅ Implemented |
| Prediction loading | ✅ Implemented |
| Risk flags | ✅ Implemented |
| Forecast serving structure | ✅ Implemented |
| Agency statistics | ✅ Implemented |
| Current-predictions view | ✅ Implemented |
| ML → DB contract | ✅ Implemented |

## Partially Implemented

| Component | Status |
|---|---|
| Historical identity coverage | 🟡 Partial |
| Final Gold → serving integration | 🟡 Partial |
| Production/champion ML model integration | 🟡 Partial |

## Not Yet Implemented

| Component | Status |
|---|---|
| FastAPI endpoints | ⏳ Planned |
| Scout / external intelligence | ⏳ Planned |
| Alert workflow | ⏳ Planned |
| Full RBAC/governance | ⏳ Planned |
| Production deployment/hardening | ⏳ Planned |

---

# 7. PostgreSQL Database

Current development database:

```text
paimana_radar
```

Functional schemas used by the architecture include:

```text
ingest
core
analytics
ml
app
```

The currently important implemented serving areas are primarily:

```text
ingest
core
ml
```

Do not assume that a schema or table exists simply because it appears in the architecture.

The Alembic migrations are the authoritative source for the implemented schema.

---

# 8. Environment Configuration

Database configuration is handled through environment variables.

Example `.env.example`:

```env
DB_USER=postgres
DB_PASSWORD=YOUR_PASSWORD
DB_HOST=localhost
DB_PORT=5432
DB_NAME=paimana_radar
```

Each developer creates their own local `.env`.

Never share the actual `.env`.

Example:

```text
Developer A
DB_PASSWORD=<local-password-A>

Developer B
DB_PASSWORD=<local-password-B>
```

The database schema remains reproducible regardless of the local password.

---

# 9. PostgreSQL Setup

Basic setup:

```text
1. Install PostgreSQL
2. Create database: paimana_radar
3. Create/configure a PostgreSQL user
4. Copy .env.example → .env
5. Set local DB credentials
6. Install Python dependencies
7. Test DB connection
8. Run Alembic migrations
9. Run schema/database checks
```

Typical Alembic commands:

```powershell
python -m alembic upgrade head
```

Check migration state:

```powershell
python -m alembic current
```

Check migration head:

```powershell
python -m alembic heads
```

Create a new migration only when the schema genuinely changes:

```powershell
python -m alembic revision -m "describe_change"
```

Do not manually modify the PostgreSQL schema and then forget to create a migration.

---

# 10. Migration Chain

Current documented migration sequence:

```text
001_core_identity (0599455bde63_create_core_identity_and_ingestion)
        ↓
84b98df29a61 (create_project_timeline)
        ↓
b704a78e671f (add_ml_serving_tables)
        ↓
004_model_artifact_checksum (5adc21beedaa_add_model_artifact_checksum)
        ↓
005_ingestion_staging (86f9bf0a7891_add_ingestion_staging_layer) [head]
```

Before handoff, verify these IDs and filenames against the actual migration directory.

If code and documentation disagree:

> the migration files are authoritative.

---

# 11. Ingest Schema

## `ingest.source_documents`

Purpose:

Track exactly which source artifact was received.

Important information includes:

```text
source_document_id
filename
file_type
sha256
report_period
report_type
source_path
ingested_at
```

Why it exists:

Every trusted observation should be traceable back to a source artifact.

The SHA-256 checksum identifies the exact file version.

---

## `ingest.load_runs`

Purpose:

Track ingestion and serving executions.

Important information:

```text
load_run_id
run_type
source_document_id
report_period
pipeline_version
silver_version
gold_version
model_version
started_at
finished_at
status
rows_read
rows_loaded
rows_failed
```

The system distinguishes ingestion runs from serving/model loads.

### Ingestion identity

Conceptually:

```text
(report_checksum, report_period, pipeline_version)
```

### Serving/model-load identity

Conceptually:

```text
(report_period, silver_version, gold_version, model_version)
```

This is important because a newer model may legitimately rescore the same historical reporting period.

---

## `ingest.staging_project_observations`

Purpose:

Act as the safety boundary between Silver input files and trusted Core history.

The staging layer stores:

```text
raw source values
+
parsed values
+
validation status/errors
```

Examples:

```text
source_project_key
project_name_raw
report_date_raw

cost_original_raw
cost_revised_raw
cost_anticipated_raw

parsed_report_period
parsed_cost_original_cr
parsed_cost_revised_cr
parsed_cost_anticipated_cr

parsed_delay_months
parsed_physical_progress_pct

validation_status
validation_errors
```

Bad source values are not silently rewritten.

---

# 12. Core Schema

## `core.projects`

Purpose:

Canonical project registry.

Answers:

> What projects does the system know about?

Important fields include:

```text
project_id
canonical_project_key
project_name
line_ministry
sector_name
implementing_agency
state
status
is_current
created_at
updated_at
```

Historical/completed projects should remain represented.

`is_current` determines whether the project belongs to the currently monitored portfolio.

---

## `core.project_keys`

Purpose:

Map source-system identities to canonical projects.

Important information:

```text
project_key_id
project_id
source_system
source_project_key
source_project_name
match_method
match_score
review_status
merged_into
```

The system follows a conservative identity policy.

Preferred order:

```text
Official/exact identifier
        ↓
Approved crosswalk
        ↓
Candidate generation
        ↓
Review/approval
        ↓
Canonical identity
```

Avoid:

```text
Fuzzy project-name similarity
        ↓
automatic canonical merge
```

A false project merge is more damaging than temporarily leaving an observation unresolved.

---

## `core.project_timeline`

Purpose:

Store trusted longitudinal project history.

Conceptual grain:

```text
ONE PROJECT × ONE REPORT PERIOD
```

Important fields include:

```text
timeline_id
project_id
source_project_key
report_period
report_type

project_name
sector_name
state
implementing_agency
project_type

cost_original_cr
cost_revised_cr
cost_anticipated_cr
cost_overrun_cr
cost_overrun_pct
cumulative_expenditure_cr

doc_original
doc_revised
doc_anticipated

delay_months
physical_progress_pct

source_document_id
source_page
source_file
silver_version
loaded_at
```

Important integrity constraint:

```text
(project_id, report_period)
```

must remain unique.

---

# 13. Current Core Validation Checkpoint

Current verified development checkpoint:

```text
Total timeline rows       : 12,453
Unique project-periods    : 12,453
Duplicate project-periods : 0
Missing project FK        : 0
Missing source document   : 0
Missing report period     : 0
Missing project name      : 0

RESULT: PASS
```

This is a development-state checkpoint, not a claim of production completeness.

---

# 14. Data Quality Philosophy

The data-quality layer exists to prevent source anomalies from becoming trusted project history without review.

Known examples include:

```text
physical progress > 100%
negative cumulative expenditure
malformed dates
invalid numeric fields
```

These should be flagged/quarantined rather than silently corrected.

Negative `delay_months` is not automatically invalid.

A negative delay can represent a project being ahead of schedule.

Therefore validation must distinguish:

```text
unexpected value
```

from:

```text
genuinely impossible value
```

---

# 15. Ingestion Workflow

Preferred current ingestion flow:

```text
Silver CSV
    ↓
register_source_run.py
    ↓
ingest.source_documents
ingest.load_runs
    ↓
load_silver_to_staging.py
    ↓
ingest.staging_project_observations
    ↓
validate_staging.py
    ↓
valid observations
    ↓
identity resolution
    ↓
load_direct_identity_keys.py
    ↓
core.project_keys
    ↓
promote_staging_to_timeline.py
    ↓
core.project_timeline
    ↓
audit_core_timeline.py
```

---

# 16. Loader Scripts

## `register_source_run.py`

Purpose:

- register source artifact
- calculate/store source hash
- create load-run record
- preserve lineage

Status:

```text
IMPLEMENTED
```

---

## `load_silver_to_staging.py`

Purpose:

- parse Silver CSV
- preserve raw values
- create DB-friendly parsed values
- load staging records

Status:

```text
IMPLEMENTED
```

---

## `validate_staging.py`

Purpose:

- validate parsed fields
- mark valid/invalid observations
- record validation errors
- prevent invalid promotion

Status:

```text
IMPLEMENTED
```

---

## `load_direct_identity_keys.py`

Purpose:

Insert only safe/deterministic source-key → canonical-project mappings.

Status:

```text
IMPLEMENTED
```

---

## `promote_staging_to_timeline.py`

Purpose:

- select valid observations
- resolve project identity
- preserve provenance
- insert trusted project-period observations

Status:

```text
IMPLEMENTED
```

---

## `audit_core_timeline.py`

Purpose:

Verify:

```text
duplicate project-periods
missing project FK
missing source document
missing report period
missing project name
```

Status:

```text
IMPLEMENTED
```

---

## Supporting identity/maintenance utilities

Current package may also contain:

```text
audit_unresolved_identity.py
backfill_timeline_lineage.py
```

These are supporting/maintenance utilities rather than the primary ingestion path.

---

# 17. Current Identity Limitation

Identity coverage is intentionally incomplete.

There are unresolved source identifiers that have not been confidently mapped to canonical projects.

Do not force-match them merely to increase coverage.

Recommended continuation logic:

```text
unresolved source key
        ↓
candidate generation
        ↓
name
ministry
agency
state/location
cost
dates
official identifiers
        ↓
confidence / evidence
        ↓
review
        ↓
accepted mapping
```

Acceptance condition:

> A newly accepted mapping must not create conflicting canonical project-period history.

---

# 18. Gold Feature Layer

Gold data is generated outside PostgreSQL from trusted historical observations.

The main principle is:

> Features at report period T may only use information available at or before T.

Examples of V1 features include:

```text
previous_progress_pct
previous_expenditure_cr
previous_cost_revised_cr
previous_delay_months

physical_progress_delta
expenditure_delta_cr
cost_revision_delta_cr
delay_delta_months

days_since_previous_report

physical_progress_velocity
expenditure_velocity_cr

financial_progress_pct
physical_financial_gap_pct

months_since_first_observation
```

This prevents future-data leakage.

---

# 19. V1 Target / Labels

The current prototype uses a future deterioration target.

Conceptually:

```text
schedule deterioration
OR
cost deterioration
within the defined future horizon
```

The current six-month target is generated from future outcomes relative to the prediction cutoff.

Important rule:

```text
No sufficient future observation
        ≠
negative outcome
```

Such rows are:

```text
censored / unlabeled
```

and should not automatically be used as negative supervised-training examples.

---

# 20. ML Serving Schema

## `ml.model_registry`

Stores:

```text
model name
model version
model type
target name
feature version
Gold version

training period
validation period
test period

metrics
hyperparameters

artifact path
artifact checksum

status
champion information
```

The production model itself is owned by the ML side.

The database stores the metadata required for serving and lineage.

---

## `ml.predictions`

Stores versioned project predictions.

Prediction identity includes:

```text
project
report period
model
```

Prediction history must not be silently overwritten.

A newer model version creates a separate historical prediction.

---

## `ml.risk_flags`

Stores risk/explanation dimensions consumed by the application.

Examples may include:

```text
schedule
cost
progress
data quality
external signal
```

A flag should be traceable to:

```text
model output
deterministic rule
or documented evidence
```

---

## `ml.forecasts`

Stores prepared forecasting payloads.

This may later support:

```text
trajectory/fan chart
prediction intervals
scenarios
analogue projects
```

FastAPI should read prepared forecast output rather than rebuild the entire model result on every request.

---

## `ml.agency_stats`

Stores agency-level statistics required by portfolio/agency views.

These should be produced from the broader analytical history rather than reconstructed only from current PostgreSQL project rows.

---

## `ml.current_predictions`

This is a serving view.

Definition:

> Return the current champion model's prediction at the latest `report_period` actually available for that champion model.

It is a convenience view, not another source-of-truth table.

---

# 21. ML → Database Handoff

ML owns:

```text
model training
model evaluation
feature experiments
hyperparameter tuning
SHAP/model explanation generation
model artifact
prediction generation
```

Database/backend owns:

```text
model registration
contract validation
prediction storage
versioning
project linkage
risk/forecast serving
application querying
lineage preservation
```

The detailed dataset contracts are defined in:

```text
contracts.md
```

If included:

```text
ml_db_handoff_contract.md
```

is a supplemental implementation guide.

---

# 22. Real Model Status

The ML serving schema and test/demo prediction path are implemented.

This proves the flow:

```text
model metadata
    ↓
ml.model_registry
    ↓
prediction
    ↓
ml.predictions
    ↓
risk flags
    ↓
forecast
    ↓
current_predictions
```

However:

> The current test/demo flow must not be represented as the final production champion model.

The final ML team artifact still needs to be registered and loaded.

---

# 23. FastAPI Integration

FastAPI is currently pending.

Recommended first endpoints:

```text
GET /projects
GET /projects/{id}
GET /projects/{id}/timeline
GET /projects/{id}/forecast
GET /projects/{id}/risk
GET /agencies/matrix
GET /models
```

Recommended project-detail flow:

```text
request
    ↓
resolve project identity
    ↓
core.projects
    ↓
core.project_timeline
    ↓
ml.current_predictions
    ↓
ml.risk_flags
    ↓
ml.forecasts
```

The frontend should never query PostgreSQL directly.

---

# 24. Pending Work — FastAPI

Status:

```text
NOT IMPLEMENTED
```

Purpose:

Expose trusted project, timeline and ML-serving data to the dashboard.

Inputs:

```text
core.projects
core.project_timeline
ml.current_predictions
ml.risk_flags
ml.forecasts
ml.agency_stats
```

Recommended implementation:

Use the backend's chosen PostgreSQL/SQLAlchemy layer and build paginated/scoped APIs.

Acceptance test:

> One API call can retrieve a project, its timeline, current prediction, risk information and forecast without direct database access from the frontend.

---

# 25. Pending Work — Production ML Integration

Status:

```text
PARTIAL
```

Purpose:

Replace test/demo model outputs with the final approved model.

Inputs:

```text
model artifact
model metadata
Gold version
feature version
prediction output
```

Database objects:

```text
ml.model_registry
ml.predictions
ml.risk_flags
ml.forecasts
ml.current_predictions
```

Recommended continuation:

1. register real model metadata,
2. record model artifact checksum,
3. load real predictions,
4. verify model/project/report-period uniqueness,
5. designate champion model,
6. verify `current_predictions`.

Acceptance test:

> Every displayed prediction identifies the exact model version that produced it.

---

# 26. Pending Work — Scout / External Signals

Status:

```text
NOT IMPLEMENTED
```

Purpose:

Bring external real-world evidence into project monitoring.

Future flow:

```text
external source
    ↓
Scout/extraction
    ↓
signal
    ↓
project linkage
    ↓
structured event
    ↓
risk context
```

Potential categories:

```text
land acquisition
clearances
funding
contractor issues
litigation
utility shifting
inter-agency dependency
weather
```

Recommended future schema:

```text
signals
signal_projects
project_events
bottlenecks
bottleneck_projects
```

Every external signal should preserve:

```text
source
date
category
evidence
project/entity link
link confidence
review status
```

---

# 27. Pending Work — Alerts

Status:

```text
NOT IMPLEMENTED
```

Potential alert triggers:

```text
project enters Critical tier
new severe external signal
data stale for multiple periods
major schedule deterioration
major cost deterioration
```

Recommended design:

Separate:

```text
alert creation
```

from:

```text
notification delivery
```

Use a deterministic deduplication key so rerunning a pipeline does not create duplicate alerts.

Acceptance test:

> A qualifying event produces exactly one alert record.

---

# 28. Pending Work — RBAC / Governance

Status:

```text
NOT IMPLEMENTED
```

Planned roles include:

```text
IPMD administrator
Ministry nodal officer
Implementing agency
Read-only policymaker
```

Recommended authorization model:

```text
FastAPI authentication
        ↓
role/scope
        ↓
ministry/agency filtering
        ↓
PostgreSQL query
```

PostgreSQL Row-Level Security can later be added as defense in depth if required.

---

# 29. Data Dependencies

This package does not contain the full PAIMANA dataset.

Some scripts depend on artifacts in the main repository such as:

```text
dataset/clean/
dataset/silver/
dataset/gold/
```

Do not copy the complete `dataset/` directory into the database ZIP.

Instead document which exact files each loader/script requires.

Recommended:

```text
data_requirements/
└── README.md
```

That file should map:

```text
script
→ required input file
→ expected columns
→ output
```

---

# 30. Contracts

`contracts.md` defines the authoritative handoff format for datasets such as:

```text
project_master
observations
project identity
predictions
risk flags
forecasts
agency statistics
labels
source documents
load runs
```

The contract defines:

```text
file pattern
producer
consumer
grain
columns
types
nullable fields
primary key
version
validation rules
```

When the contract and a script disagree:

> fix the disagreement before silently changing either side.

---

# 31. Verification / Tests

Useful verification utilities currently include scripts such as:

```text
tests/test_connection.py
tests/check_staging.py
tests/check_ml_schema.py
tests/check_model_registry.py
tests/verify_timeline.py
tests/create_sample_predictions.py
```

Typical workflow:

```powershell
python database/postgres/tests/test_connection.py

python database/postgres/tests/check_staging.py

python database/postgres/tests/verify_timeline.py

python database/postgres/tests/check_ml_schema.py

python database/postgres/tests/check_model_registry.py
```

Also verify migrations:

```powershell
python -m alembic current
python -m alembic heads
```

---

# 32. Important Known Limitations

## Identity Coverage

Not every source identifier has a trusted canonical mapping.

Do not force-match unresolved observations.

---

## Development-Specific Parameters

Some scripts may still contain development-time values such as:

```text
specific load_run_id
Silver version
local file assumptions
```

Convert these to:

```text
CLI arguments
environment/config values
```

before broader reuse.

---

## Production ML

The serving schema exists, but the final approved champion model still needs integration.

---

## FastAPI

Database contracts exist, but actual backend endpoints remain pending.

---

## Scout

External evidence processing is not yet implemented.

---

## Alerts

The final alert engine is not yet implemented.

---

## RBAC

Full production access-control/governance is not yet implemented.

---

## Deployment

This is a development/handoff package.

Production concerns such as:

```text
managed PostgreSQL
secrets management
monitoring
backup automation
deployment
network security
```

remain future work.

---

# 33. Recommended Continuation Order

The recommended order after receiving this package is:

```text
1. Verify ZIP/package structure
        ↓
2. Configure PostgreSQL
        ↓
3. Run Alembic migrations
        ↓
4. Run schema/tests
        ↓
5. Verify existing ingestion flow
        ↓
6. Connect required Silver/Gold inputs
        ↓
7. Register real ML model
        ↓
8. Load real predictions
        ↓
9. Verify current_predictions
        ↓
10. Build minimum FastAPI endpoints
        ↓
11. Connect dashboard
        ↓
12. Add Scout
        ↓
13. Add alerts/RBAC
        ↓
14. Production hardening
```

For the immediate prototype, priorities should be:

```text
PostgreSQL
    ↓
Project
    ↓
Timeline
    ↓
Prediction
    ↓
Risk / Forecast
    ↓
FastAPI
    ↓
Dashboard
```

Do not block the prototype by attempting to solve every unresolved identity or future production feature.

---

# 34. Recommended Prototype Integration

For a minimum end-to-end demonstration:

```text
Dashboard
    ↓
FastAPI
    ↓
GET /projects
    ↓
select project
    ↓
GET /projects/{id}
    ↓
GET /projects/{id}/timeline
    ↓
GET /projects/{id}/risk
    ↓
GET /projects/{id}/forecast
```

This demonstrates that the database foundation is genuinely integrated rather than only existing as isolated SQL tables.

---

# 35. Handoff Checklist

## Package

- [ ] README.md present
- [ ] contracts.md present
- [ ] `.env.example` present
- [ ] Alembic configuration present
- [ ] migration files present
- [ ] loaders present
- [ ] relevant scripts present
- [ ] tests present
- [ ] no `.env`
- [ ] no passwords
- [ ] no `__pycache__`
- [ ] no large raw dataset
- [ ] no unrelated frontend/application files

## PostgreSQL

- [ ] PostgreSQL installed
- [ ] `paimana_radar` database created
- [ ] local `.env` configured
- [ ] DB connection test passes

## Schema

- [ ] Alembic upgrade succeeds
- [ ] `ingest` objects exist
- [ ] `core` objects exist
- [ ] `ml` objects exist

## Data

- [ ] source artifact can be registered
- [ ] load run can be created
- [ ] staging can be populated
- [ ] DQ validation works
- [ ] identity mapping works
- [ ] trusted timeline can be promoted
- [ ] timeline audit passes

## ML

- [ ] model metadata can be registered
- [ ] predictions can be loaded
- [ ] duplicate prediction load is idempotent
- [ ] risk flags available
- [ ] forecasts available
- [ ] `current_predictions` works

## Backend

- [ ] PostgreSQL connection configured
- [ ] project query works
- [ ] timeline query works
- [ ] prediction/risk query works
- [ ] forecast query works

---

# 36. Rules for Future Contributors

### Do not manually change schema

Use Alembic migrations.

### Do not force project identity

Preserve unresolved observations until reliable evidence exists.

### Do not destroy provenance

Trusted observations should remain traceable to their source/load context.

### Do not leak future information into ML features

Features must obey the report-period cutoff.

### Do not expose credentials

Use `.env` locally.

### Do not treat test/demo predictions as production predictions

Always preserve:

```text
model_version
feature_version
gold_version
report_period
artifact metadata
```

### Do not duplicate prediction-history tables

`ml.predictions` is the prediction history.

Views such as `ml.current_predictions` only expose convenient serving state.

---

# 37. Final Mental Model

```text
INGEST
"What did we receive?"
        ↓

STAGING
"What exactly did we parse?"
        ↓

DATA QUALITY
"Is the observation acceptable?"
        ↓

IDENTITY
"Which real project does it belong to?"
        ↓

CORE
"What is the trusted project history?"
        ↓

GOLD
"What point-in-time features/labels can we derive?"
        ↓

ML
"What future deterioration is predicted?"
        ↓

POSTGRESQL ML SERVING
"How do we store and version the prediction?"
        ↓

FASTAPI
"How does the application retrieve it?"
        ↓

DASHBOARD
"What should the user see?"
        ↓

ACTION
"What requires attention?"
```

---

# 38. Final Handoff Principle

The purpose of this package is not to claim that every PAIMANA Radar feature is complete.

The purpose is to provide:

```text
working database foundation
+
trusted project history
+
data lineage
+
ML-serving structure
+
reproducible migrations
+
clear continuation logic
```

so that the next developer or coding agent can continue integration without reconstructing the architecture from scratch.

The most important immediate goal after handoff is:

> Connect the existing PostgreSQL project/timeline/ML serving layer to the minimum FastAPI endpoints required for the prototype.