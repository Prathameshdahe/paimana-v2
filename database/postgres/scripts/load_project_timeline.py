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

SILVER_FILE = (
    ROOT
    / "dataset"
    / "silver"
    / "project_monitoring_2025-26_clean.csv"
)


# =========================================================
# LOAD SILVER DATA
# =========================================================

silver = pd.read_csv(SILVER_FILE)

print("=========================================================")
print("LOADING SILVER PROJECT OBSERVATIONS")
print("=========================================================")

print(f"Silver rows: {len(silver):,}")


# =========================================================
# NORMALIZE REPORT PERIOD
# =========================================================

silver["report_period"] = (
    pd.to_datetime(
        silver["report_date"],
        errors="coerce",
    )
    .dt.to_period("M")
    .dt.to_timestamp()
)


invalid_periods = silver["report_period"].isna().sum()

if invalid_periods:
    raise ValueError(
        f"Found {invalid_periods} rows with invalid report dates."
    )


# =========================================================
# BUILD SOURCE PROJECT KEY
# =========================================================

silver["source_project_key"] = (
    "OCMS:"
    + silver["project_id"]
    .astype(str)
    .str.strip()
)


# =========================================================
# LOAD CORE PROJECT LOOKUP
# =========================================================

with engine.connect() as connection:

    projects = pd.read_sql(
        text(
            """
            SELECT
                project_id,
                canonical_project_key
            FROM core.projects
            """
        ),
        connection,
    )


project_lookup = dict(
    zip(
        projects["canonical_project_key"],
        projects["project_id"],
    )
)


# =========================================================
# MAP SILVER → CORE PROJECT
# =========================================================

silver["project_id_db"] = (
    silver["source_project_key"]
    .map(project_lookup)
)


safe = silver[
    silver["project_id_db"].notna()
].copy()


unresolved = silver[
    silver["project_id_db"].isna()
].copy()


print("\n=========================================================")
print("IDENTITY RESULT")
print("=========================================================")

print(
    f"Safe observations:       {len(safe):,}"
)

print(
    f"Unresolved observations: {len(unresolved):,}"
)


# =========================================================
# PREPARE DATABASE VALUES
# =========================================================

def clean_number(series):
    return pd.to_numeric(
        series,
        errors="coerce",
    )


numeric_columns = [
    "cost_original",
    "cost_revised",
    "cost_anticipated",
    "cost_overrun",
    "cost_overrun_pct",
    "cumulative_expenditure",
    "delay_months",
    "physical_progress",
]

for column in numeric_columns:

    if column in safe.columns:
        safe[column] = clean_number(
            safe[column]
        )


date_columns = [
    "doc_original",
    "doc_revised",
    "doc_anticipated",
]

for column in date_columns:

    if column in safe.columns:
        safe[column] = (
            pd.to_datetime(
                safe[column],
                errors="coerce",
            )
            .dt.date
            .where(
                lambda s: s.notna(),
                None,
            )
        )


# =========================================================
# INSERT QUERY
# =========================================================

insert_query = text(
    """
    INSERT INTO core.project_timeline (
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
    )
    VALUES (
        :project_id,
        :source_project_key,
        :report_period,
        :report_type,
        :project_name,
        :sector_name,
        :state,
        :implementing_agency,
        :project_type,
        :cost_original_cr,
        :cost_revised_cr,
        :cost_anticipated_cr,
        :cost_overrun_cr,
        :cost_overrun_pct,
        :cumulative_expenditure_cr,
        :doc_original,
        :doc_revised,
        :doc_anticipated,
        :delay_months,
        :physical_progress_pct,
        :source_page,
        :source_file,
        :silver_version
    )
    ON CONFLICT (project_id, report_period)
    DO UPDATE SET
        source_project_key = EXCLUDED.source_project_key,
        report_type = EXCLUDED.report_type,
        project_name = EXCLUDED.project_name,
        sector_name = EXCLUDED.sector_name,
        state = EXCLUDED.state,
        implementing_agency = EXCLUDED.implementing_agency,
        project_type = EXCLUDED.project_type,
        cost_original_cr = EXCLUDED.cost_original_cr,
        cost_revised_cr = EXCLUDED.cost_revised_cr,
        cost_anticipated_cr = EXCLUDED.cost_anticipated_cr,
        cost_overrun_cr = EXCLUDED.cost_overrun_cr,
        cost_overrun_pct = EXCLUDED.cost_overrun_pct,
        cumulative_expenditure_cr = EXCLUDED.cumulative_expenditure_cr,
        doc_original = EXCLUDED.doc_original,
        doc_revised = EXCLUDED.doc_revised,
        doc_anticipated = EXCLUDED.doc_anticipated,
        delay_months = EXCLUDED.delay_months,
        physical_progress_pct = EXCLUDED.physical_progress_pct,
        source_page = EXCLUDED.source_page,
        source_file = EXCLUDED.source_file,
        silver_version = EXCLUDED.silver_version;
    """
)


# =========================================================
# BUILD RECORDS
# =========================================================

def python_date_or_none(value):
    if pd.isna(value):
        return None
    return value


records = []

for _, row in safe.iterrows():

    records.append(
        {
            "project_id": int(row["project_id_db"]),
            "source_project_key": row["source_project_key"],
            "report_period": row["report_period"].date(),
            "report_type": row.get("report_type"),
            "project_name": row.get("project_name"),
            "sector_name": row.get("sector"),
            "state": row.get("state"),
            "implementing_agency": row.get("agency"),
            "project_type": row.get("project_type"),
            "cost_original_cr": row.get("cost_original"),
            "cost_revised_cr": row.get("cost_revised"),
            "cost_anticipated_cr": row.get("cost_anticipated"),
            "cost_overrun_cr": row.get("cost_overrun"),
            "cost_overrun_pct": row.get("cost_overrun_pct"),
            "cumulative_expenditure_cr": row.get(
                "cumulative_expenditure"
            ),
            "doc_original": python_date_or_none(
                row.get("doc_original")
            ),
            "doc_revised": python_date_or_none(
                row.get("doc_revised")
            ),
            "doc_anticipated": python_date_or_none(
                row.get("doc_anticipated")
            ),
            "delay_months": row.get("delay_months"),
            "physical_progress_pct": row.get(
                "physical_progress"
            ),
            "source_page": row.get("page"),
            "source_file": row.get("source_file"),
            "silver_version": "project_monitoring_2025-26_clean",
        }
    )


# =========================================================
# LOAD
# =========================================================

print("\n=========================================================")
print("DATABASE LOAD")
print("=========================================================")

with engine.begin() as connection:

    if records:
        connection.execute(
            insert_query,
            records,
        )


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    total = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM core.project_timeline
            """
        )
    ).scalar_one()

    projects_count = connection.execute(
        text(
            """
            SELECT COUNT(DISTINCT project_id)
            FROM core.project_timeline
            """
        )
    ).scalar_one()

    periods_count = connection.execute(
        text(
            """
            SELECT COUNT(DISTINCT report_period)
            FROM core.project_timeline
            """
        )
    ).scalar_one()


print("\n=========================================================")
print("FINAL RESULT")
print("=========================================================")

print(
    f"Timeline rows in database: {total:,}"
)

print(
    f"Projects represented:      {projects_count:,}"
)

print(
    f"Reporting periods:         {periods_count:,}"
)

print(
    f"Unresolved Silver rows:     {len(unresolved):,}"
)