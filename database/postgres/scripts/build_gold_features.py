import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

DATABASE_URL = URL.create(
    "postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME"),
)

engine = create_engine(DATABASE_URL)

ROOT = Path(__file__).resolve().parents[3]

OUTPUT_DIR = (
    ROOT
    / "dataset"
    / "gold"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "features_v1.csv"
)


# =========================================================
# LOAD TIMELINE
# =========================================================

query = """
SELECT
    project_id,
    source_project_key,
    report_period,
    report_type,
    project_name,
    sector_name,
    state,
    implementing_agency,
    project_type,
    cost_original_cr,
    cost_revised_cr,
    cost_anticipated_cr,
    cost_overrun_cr,
    cost_overrun_pct,
    cumulative_expenditure_cr,
    doc_original,
    doc_revised,
    doc_anticipated,
    delay_months,
    physical_progress_pct,
    source_page,
    source_file,
    silver_version
FROM core.project_timeline
ORDER BY project_id, report_period;
"""

with engine.connect() as connection:
    df = pd.read_sql(text(query), connection)


print("=========================================================")
print("GOLD FEATURE ENGINEERING")
print("=========================================================")

print(f"Timeline rows loaded: {len(df):,}")


# =========================================================
# SORT
# =========================================================

df["report_period"] = pd.to_datetime(
    df["report_period"]
)

df = df.sort_values(
    ["project_id", "report_period"]
).reset_index(drop=True)


# =========================================================
# PREVIOUS PERIOD VALUES
# =========================================================

grouped = df.groupby("project_id")

df["previous_progress_pct"] = grouped[
    "physical_progress_pct"
].shift(1)

df["previous_expenditure_cr"] = grouped[
    "cumulative_expenditure_cr"
].shift(1)

df["previous_cost_revised_cr"] = grouped[
    "cost_revised_cr"
].shift(1)

df["previous_delay_months"] = grouped[
    "delay_months"
].shift(1)

df["previous_report_period"] = grouped[
    "report_period"
].shift(1)


# =========================================================
# CHANGE FEATURES
# =========================================================

df["physical_progress_delta"] = (
    df["physical_progress_pct"]
    - df["previous_progress_pct"]
)

df["expenditure_delta_cr"] = (
    df["cumulative_expenditure_cr"]
    - df["previous_expenditure_cr"]
)

df["cost_revision_delta_cr"] = (
    df["cost_revised_cr"]
    - df["previous_cost_revised_cr"]
)

df["delay_delta_months"] = (
    df["delay_months"]
    - df["previous_delay_months"]
)


# =========================================================
# REPORTING INTERVAL
# =========================================================

df["days_since_previous_report"] = (
    df["report_period"]
    - df["previous_report_period"]
).dt.days


# =========================================================
# VELOCITY FEATURES
# =========================================================

df["physical_progress_velocity"] = (
    df["physical_progress_delta"]
    / df["days_since_previous_report"]
    * 30.4375
)

df["expenditure_velocity_cr"] = (
    df["expenditure_delta_cr"]
    / df["days_since_previous_report"]
    * 30.4375
)


# =========================================================
# PHYSICAL VS FINANCIAL GAP
# =========================================================
#
# expenditure / original cost gives approximate
# financial completion.
#
# Example:
#   physical progress = 40%
#   financial progress = 65%
#   gap = 25 percentage points
#
# Positive value means spending progress is ahead
# of physical progress.
# =========================================================

df["financial_progress_pct"] = (
    df["cumulative_expenditure_cr"]
    / df["cost_original_cr"]
    * 100
)

df["physical_financial_gap_pct"] = (
    df["financial_progress_pct"]
    - df["physical_progress_pct"]
)


# =========================================================
# PROJECT AGE
# =========================================================

first_period = grouped[
    "report_period"
].transform("min")

df["months_since_first_observation"] = (
    (
        df["report_period"].dt.year
        - first_period.dt.year
    ) * 12
    +
    (
        df["report_period"].dt.month
        - first_period.dt.month
    )
)


# =========================================================
# CLEAN NUMERIC INFINITIES
# =========================================================

numeric_columns = [
    "physical_progress_delta",
    "expenditure_delta_cr",
    "cost_revision_delta_cr",
    "delay_delta_months",
    "physical_progress_velocity",
    "expenditure_velocity_cr",
    "financial_progress_pct",
    "physical_financial_gap_pct",
]

for column in numeric_columns:
    df[column] = df[column].replace(
        [float("inf"), float("-inf")],
        pd.NA,
    )


# =========================================================
# FEATURE VERSION
# =========================================================

df["feature_version"] = "gold_v1"


# =========================================================
# SAVE GOLD DATASET
# =========================================================

df.to_csv(
    OUTPUT_FILE,
    index=False,
)

print("\n=========================================================")
print("GOLD DATASET CREATED")
print("=========================================================")

print(
    f"Rows:    {len(df):,}"
)

print(
    f"Columns: {len(df.columns):,}"
)

print(
    f"Output:  {OUTPUT_FILE}"
)


# =========================================================
# FEATURE SUMMARY
# =========================================================

feature_columns = [
    "physical_progress_delta",
    "expenditure_delta_cr",
    "physical_progress_velocity",
    "expenditure_velocity_cr",
    "financial_progress_pct",
    "physical_financial_gap_pct",
    "cost_revision_delta_cr",
    "delay_delta_months",
    "months_since_first_observation",
]

print("\n=========================================================")
print("FEATURE NULL COUNTS")
print("=========================================================")

print(
    df[feature_columns]
    .isna()
    .sum()
    .to_string()
)


print("\n=========================================================")
print("FEATURE SAMPLE")
print("=========================================================")

print(
    df[
        [
            "project_id",
            "report_period",
            "physical_progress_pct",
            "cumulative_expenditure_cr",
            "physical_progress_delta",
            "expenditure_delta_cr",
            "physical_progress_velocity",
            "expenditure_velocity_cr",
            "financial_progress_pct",
            "physical_financial_gap_pct",
            "delay_months",
            "delay_delta_months",
        ]
    ]
    .head(15)
    .to_string(index=False)
)