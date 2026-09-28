# PAIMANA Radar — Data Contracts

## 1. Purpose

This document defines the data contracts between the Data Engineering,
Database, Analytics and ML teams.

It specifies:

- what data is exchanged
- expected file names/patterns
- producer and consumer
- columns and data types
- nullability
- primary/unique keys
- versioning
- important validation rules

The contract is intentionally limited to data shape and handoff rules.

---

# 2. Source-of-Truth Definition

- Bronze preserves the original source data and provenance.
- Silver is the trusted standardized historical data layer.
- Gold is the trusted analytical and ML feature/label layer.
- PostgreSQL is the application/serving source of truth.

PostgreSQL must retain sufficient lineage to trace important records
back to their source document and reporting period.

---

# 3. General Conventions

## 3.1 Project Identity

The stable internal project identifier is:

`canonical_project_key`

Source-specific identifiers must not replace the canonical project key.

---

## 3.2 Reporting Period

`report_period` uses:

`DATE`

Standard representation:

`YYYY-MM-DD`

Example:

`2026-04-01`

The value represents the reporting period start date.

---

## 3.3 Timestamps

System timestamps use:

`TIMESTAMP WITH TIME ZONE`

---

## 3.4 Currency / Cost

Financial values use:

`NUMERIC`

Values must preserve the source unit.

For PAIMANA project cost data, the standard unit is:

`₹ crore`

---

## 3.5 Percentages

Percentages use:

`NUMERIC`

unless otherwise specified.

Example:

`72.5`

means `72.5%`, not `0.725`.

---

## 3.6 Versions

The following versions are tracked independently:

- `silver_version`
- `gold_version`
- `model_version`
- `pipeline_version`

A newer model may rescore an existing reporting period.

Therefore prediction identity must include `model_version`.

---

# 4. Project Master

## Dataset

`project_master`

## File Pattern

`project_master.parquet`

## Producer

Silver / identity-resolution pipeline

## Consumer

PostgreSQL loader / ML / API

## Grain

One canonical project.

## Primary Key

`canonical_project_key`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Stable internal project identity |
| project_name | TEXT | NO | Canonical project name |
| ministry | TEXT | YES | Line ministry |
| sector | TEXT | YES | Project sector |
| implementing_agency | TEXT | YES | Implementing agency |
| state | TEXT | YES | State/location |
| status | TEXT | YES | Current project status |
| is_current | BOOLEAN | NO | Whether project belongs to current monitored portfolio |

## Rules

- `canonical_project_key` must be stable.
- Historical/completed projects must remain represented.
- `is_current` identifies whether the project belongs to the currently monitored portfolio.
- Reported source values must not be silently replaced by inferred values.

---

# 5. Project Observations

## Dataset

`observations`

## File Pattern

`observations.parquet`

## Producer

Silver pipeline

## Consumer

PostgreSQL loader / Gold feature pipeline / ML

## Grain

One canonical project observed in one reporting period.

## Primary Key

`(canonical_project_key, report_period)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Canonical project identity |
| report_period | DATE | NO | Reporting period |
| original_cost | NUMERIC | YES | Reported original cost in ₹ crore |
| revised_cost | NUMERIC | YES | Reported revised cost in ₹ crore |
| expenditure | NUMERIC | YES | Reported expenditure in ₹ crore |
| physical_progress | NUMERIC | YES | Reported physical progress (%) |
| scheduled_completion | DATE | YES | Scheduled/revised completion date |
| anticipated_completion | DATE | YES | Anticipated completion date |
| status | TEXT | YES | Reported project status |
| source_document_id | TEXT | NO | Source document lineage |
| source_page | INTEGER | YES | Source page where applicable |
| silver_version | TEXT | NO | Silver pipeline version |
| loaded_at | TIMESTAMP WITH TIME ZONE | NO | Load timestamp |

## Rules

- One row represents one project-period observation.
- No duplicate `(canonical_project_key, report_period)` rows.
- Future information must not be inserted into historical observations.
- Reported values are preserved separately from derived analytical values.

---

# 6. Project Identity / Source Keys

## Dataset

`project_keys`

## File Pattern

`project_identity_map.parquet`

## Producer

Identity-resolution pipeline

## Consumer

PostgreSQL loader / all downstream consumers

## Grain

One source-specific project identifier mapped to a canonical project.

## Unique Key

`(source_system, source_project_key)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Canonical project |
| source_system | TEXT | NO | Source system, e.g. PAIMANA / OCMS |
| source_project_key | TEXT | NO | Source-specific identifier |
| source_project_name | TEXT | YES | Name as reported by source |
| match_method | TEXT | YES | Exact / approved / other |
| match_score | NUMERIC | YES | Matching confidence/score where applicable |
| review_status | TEXT | NO | accepted / review / rejected |
| merged_into | TEXT | YES | Winning canonical key when this key is merged |

## Rules

- Source identifiers must not be automatically treated as canonical identity.
- Fuzzy matching may generate candidates but must not automatically establish identity.
- `review_status = accepted` is required for a confirmed mapping.
- `merged_into` identifies the winning canonical project when a project identity is merged.

---

# 7. Predictions

## Dataset

`predictions`

## File Pattern

`predictions_<model_version>_<report_period>.parquet` (or `.csv` / `.json`)

## Producer

ML scoring pipeline

## Consumer

PostgreSQL loader / API / dashboard

## Grain

One project prediction for one reporting period and model version.

## Primary Key

`(canonical_project_key, report_period, model_version)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Project identifier / key |
| report_period | DATE | NO | Prediction as-of period |
| model_version | TEXT | NO | Model version |
| p_risk | NUMERIC | YES | Probability of overall project risk |
| risk_score | NUMERIC | YES | Overall risk score (0 to 100) |
| risk_tier | TEXT | YES | Risk tier (GREEN / AMBER / RED) |
| p_schedule_deterioration | NUMERIC | YES | Probability of schedule deterioration |
| p_cost_deterioration | NUMERIC | YES | Probability of cost deterioration |
| expected_slip_months | NUMERIC | YES | Expected schedule slip in months |
| expected_cost_pct | NUMERIC | YES | Expected cost escalation percentage |
| slip_interval_low | NUMERIC | YES | Lower prediction interval for schedule slip |
| slip_interval_high | NUMERIC | YES | Upper prediction interval for schedule slip |
| cost_interval_low | NUMERIC | YES | Lower prediction interval for cost escalation |
| cost_interval_high | NUMERIC | YES | Upper prediction interval for cost escalation |
| risk_rank | INTEGER | YES | Portfolio risk ranking |
| shap_top5_json | JSONB | YES | Top 5 SHAP model feature attributions |
| prediction_payload | JSONB | YES | Full prediction payload object |
| created_at | TIMESTAMP WITH TIME ZONE | NO | Prediction creation timestamp |

## Rules

- Prediction history must never be overwritten.
- A newer `model_version` creates a new prediction record.
- Prediction features must only use information available at or before `report_period`.
- `shap_top5_json` contains model attribution information and is not the source of truth for the underlying features.

---

# 8. Risk Flags

## Dataset

`risk_flags`

## File Pattern

Generated automatically or passed as `risk_flags_<model_version>_<report_period>.parquet`

## Producer

Analytics / ML / risk flag generator engine

## Consumer

PostgreSQL / API / dashboard / alert system

## Grain

One risk dimension for one project, reporting period, and model version.

## Primary Key

`(canonical_project_key, report_period, model_version, dimension)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Project identifier |
| report_period | DATE | NO | Reporting period |
| model_version | TEXT | NO | Model version |
| dimension | TEXT | NO | Risk dimension (`overall`, `schedule`, `cost`) |
| flag_type | TEXT | NO | Flag type (`elevated_risk`, `high_risk`, `schedule_deterioration_risk`, `cost_deterioration_risk`) |
| severity | TEXT | YES | Flag severity level (`medium`, `high`) |
| evidence_json | JSONB | YES | Structured evidence JSON payload |
| created_at | TIMESTAMP WITH TIME ZONE | NO | Creation timestamp |

## Examples of `dimension`

- `overall`
- `schedule`
- `cost`

## Rules

Risk flags must be traceable to either:

- model predictions (`ml.predictions`)
- deterministic rules/thresholds
- documented evidence in `evidence_json`

---

# 9. Forecasts

## Dataset

`forecasts`

## File Pattern

`forecasts_<model_version>_<report_period>.json` (or `.jsonl` / `.parquet`)

## Producer

ML forecasting pipeline

## Consumer

PostgreSQL / API / dashboard

## Grain

One forecast payload for one project, reporting period, and model version.

## Primary Key

`(canonical_project_key, report_period, model_version)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Project identifier |
| report_period | DATE | NO | As-of period |
| model_version | TEXT | NO | Model version |
| forecast_payload | JSONB | NO | Forecast payload object containing trajectories and intervals |
| created_at | TIMESTAMP WITH TIME ZONE | NO | Creation timestamp |

## Rules

- `forecast_payload` holds flexible fan chart, scenario, or time-series forecast structures.
- One forecast record exists per project-period-model combination.

---

# 10. Agency Statistics

## Dataset

`agency_stats`

## File Pattern

`agency_stats_<report_period>.parquet` (or generated via `generate_agency_stats.py`)

## Producer

Gold / agency stats generator pipeline

## Consumer

PostgreSQL / API / dashboard / ML

## Grain

One agency for one reporting period and model version.

## Primary Key

`(agency_name, report_period, model_version)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| agency_name | TEXT | NO | Implementing agency name |
| report_period | DATE | NO | Reporting period |
| model_version | TEXT | NO | Model version |
| project_count | INTEGER | NO | Total number of projects monitored for agency |
| green_count | INTEGER | NO | Count of low-risk (GREEN) projects |
| amber_count | INTEGER | NO | Count of medium-risk (AMBER) projects |
| red_count | INTEGER | NO | Count of high-risk (RED) projects |
| avg_risk_score | NUMERIC | YES | Average risk score across agency projects |
| stats_payload | JSONB | YES | Detailed agency statistics JSON breakdown |
| created_at | TIMESTAMP WITH TIME ZONE | NO | Creation timestamp |

## Rules

Agency statistics are generated across project portfolio predictions for each reporting period and model version.

---

# 11. Labels

## Dataset

`labels`

## File Pattern

`labels_h<horizon>.parquet`

Example:

`labels_h2.parquet`

## Producer

Gold label-generation pipeline

## Consumer

ML training pipeline

## Grain

One project, one as-of reporting period and one prediction horizon.

## Primary Key

`(canonical_project_key, report_period, horizon_quarters)`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| canonical_project_key | TEXT | NO | Project |
| report_period | DATE | NO | Prediction/as-of period |
| horizon_quarters | INTEGER | NO | Future prediction horizon |
| date_push_label | BOOLEAN | YES | Whether schedule/date push occurred within horizon |
| cost_revision_label | BOOLEAN | YES | Whether cost revision occurred within horizon |
| realised_slip_months | NUMERIC | YES | Realised schedule slip |
| realised_cost_pct | NUMERIC | YES | Realised cost escalation |
| gold_version | TEXT | NO | Gold label version |

## Rules

- Labels are future outcomes relative to `report_period`.
- Features must not use information from the label horizon.
- Projects without sufficient future observation may be treated as censored/unavailable rather than automatically labelled negative.
- Label-generation logic must be versioned.

---

# 12. Source Documents

## Dataset

`source_documents`

## File Pattern

Source files themselves retain their original names.

## Producer

Ingestion pipeline

## Consumer

PostgreSQL / lineage / audit processes

## Grain

One received source document.

## Primary Key

`source_document_id`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| source_document_id | TEXT | NO | Unique source ID |
| filename | TEXT | NO | Original filename |
| file_type | TEXT | NO | PDF / CSV / etc. |
| sha256 | TEXT | NO | File checksum |
| report_period | DATE | YES | Reporting period |
| report_type | TEXT | YES | Flash / Quarterly / etc. |
| source_path | TEXT | YES | Original source location |
| ingested_at | TIMESTAMP WITH TIME ZONE | NO | Ingestion timestamp |

## Rules

- Original source files must remain preserved.
- SHA-256 identifies the exact received file.
- A changed source file must produce a different checksum.

---

# 13. Load Runs

## Dataset

`load_runs`

## File Pattern

Internal database record; no external file required.

## Producer

Ingestion / serving pipeline

## Consumer

PostgreSQL / monitoring / audit

## Grain

One pipeline execution.

## Primary Key

`load_run_id`

## Columns

| Column | Type | Nullable | Description |
|---|---|---:|---|
| load_run_id | TEXT | NO | Unique pipeline run |
| run_type | TEXT | NO | INGEST / SERVING / MODEL_LOAD |
| source_document_id | TEXT | YES | Source document |
| report_period | DATE | YES | Reporting period |
| pipeline_version | TEXT | NO | Pipeline version |
| silver_version | TEXT | YES | Silver version |
| gold_version | TEXT | YES | Gold version |
| model_version | TEXT | YES | Model version |
| started_at | TIMESTAMP WITH TIME ZONE | NO | Start time |
| finished_at | TIMESTAMP WITH TIME ZONE | YES | Finish time |
| status | TEXT | NO | RUNNING / SUCCESS / FAILED |
| rows_read | INTEGER | YES | Input rows |
| rows_loaded | INTEGER | YES | Successfully loaded rows |
| rows_failed | INTEGER | YES | Failed rows |

## Rules

Ingestion and model-serving runs must remain distinguishable.

The same reporting period may legitimately have multiple model-serving runs for different model versions.

---

# 14. Versioning Rules

The pipeline must distinguish:

### Source ingestion identity

`source_document + checksum + pipeline_version`

### Analytical/model serving identity

`report_period + silver_version + gold_version + model_version`

A newer model may rescore historical reporting periods without modifying the original observation.

---

# 15. Data Quality Rules

The loader must validate at minimum:

- required columns exist
- required keys are not NULL
- primary keys are unique
- reporting periods are valid
- dates are valid
- numeric fields contain valid numbers
- physical progress is within the accepted range
- source documents exist for observations
- project keys resolve where identity is required
- duplicate observations are rejected or flagged
- invalid records are not silently discarded

Failed records must remain traceable through the ingestion/load process.

---

# 16. General Handoff Rule

Every dataset handed to PostgreSQL must provide:

1. Dataset name
2. File name/pattern
3. Producer
4. Consumer
5. Grain
6. Columns
7. Data types
8. Nullable rules
9. Primary/unique key
10. Version information
11. Validation rules
12. Source/provenance information where applicable

---

# 17. Core Data Flow

```text
SOURCE
  ↓
BRONZE
  ↓
CLEAN / STAGING
  ↓
IDENTITY + DATA QUALITY
  ↓
SILVER
  ↓
GOLD
  ↓
ML
  ↓
PREDICTIONS / FORECASTS / RISK FLAGS
  ↓
POSTGRESQL
  ↓
FASTAPI
  ↓
DASHBOARD