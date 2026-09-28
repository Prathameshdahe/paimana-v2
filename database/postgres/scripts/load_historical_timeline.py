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

SILVER_FILES = [
    ROOT / "dataset" / "silver" / "project_monitoring_2024-25_clean.csv",
    ROOT / "dataset" / "silver" / "project_monitoring_2025-26_clean.csv",
    ROOT / "dataset" / "silver" / "project_monitoring_2026-27_clean.csv",
]


# =========================================================
# HELPERS
# =========================================================

def python_date_or_none(value):
    """
    Convert Pandas NaT/NaN to Python None.
    Keep valid dates as Python date objects.
    """
    if pd.isna(value):
        return None

    if hasattr(value, "date"):
        return value.date()

    return value


def python_value_or_none(value):
    """
    Convert Pandas NaN/NaT to Python None.
    """
    if pd.isna(value):
        return None

    return value


def clean_number(value):
    if pd.isna(value):
        return None

    return float(value)


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
# PROCESS FILES
# =========================================================

all_records = []

total_rows = 0
total_safe = 0
total_unresolved = 0


print("=" * 70)
print("HISTORICAL PROJECT TIMELINE LOAD")
print("=" * 70)


for silver_file in SILVER_FILES:

    print("\n" + "=" * 70)
    print(f"FILE: {silver_file.name}")
    print("=" * 70)

    if not silver_file.exists():
        raise FileNotFoundError(
            f"Silver file not found: {silver_file}"
        )

    silver = pd.read_csv(silver_file)

    print(
        f"Silver rows: {len(silver):,}"
    )

    total_rows += len(silver)

    # -----------------------------------------------------
    # REPORT PERIOD
    # -----------------------------------------------------

    silver["report_period"] = (
        pd.to_datetime(
            silver["report_date"],
            errors="coerce",
        )
        .dt.to_period("M")
        .dt.to_timestamp()
    )

    invalid_periods = (
        silver["report_period"].isna().sum()
    )

    if invalid_periods:
        raise ValueError(
            f"{silver_file.name}: "
            f"{invalid_periods} invalid report periods."
        )

    # -----------------------------------------------------
    # SOURCE PROJECT KEY
    # -----------------------------------------------------

    silver["source_project_key"] = (
        "OCMS:"
        + silver["project_id"]
        .astype(str)
        .str.strip()
    )

    # -----------------------------------------------------
    # MAP TO CORE PROJECT
    # -----------------------------------------------------

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

    total_safe += len(safe)
    total_unresolved += len(unresolved)

    print(
        f"Safe observations:       {len(safe):,}"
    )

    print(
        f"Unresolved observations: {len(unresolved):,}"
    )

    # -----------------------------------------------------
    # NORMALIZE NUMBERS
    # -----------------------------------------------------

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

            safe[column] = pd.to_numeric(
                safe[column],
                errors="coerce",
            )

    # -----------------------------------------------------
    # NORMALIZE DATES
    # -----------------------------------------------------

    date_columns = [
        "doc_original",
        "doc_revised",
        "doc_anticipated",
    ]

    for column in date_columns:

        if column in safe.columns:

            safe[column] = pd.to_datetime(
                safe[column],
                errors="coerce",
            )

    # -----------------------------------------------------
    # BUILD RECORDS
    # -----------------------------------------------------

    for _, row in safe.iterrows():

        all_records.append(
            {
                "project_id": int(
                    row["project_id_db"]
                ),

                "source_project_key":
                    row["source_project_key"],

                "report_period":
                    row["report_period"].date(),

                "report_type":
                    python_value_or_none(
                        row.get("report_type")
                    ),

                "project_name":
                    python_value_or_none(
                        row.get("project_name")
                    ),

                "sector_name":
                    python_value_or_none(
                        row.get("sector")
                    ),

                "state":
                    python_value_or_none(
                        row.get("state")
                    ),

                "implementing_agency":
                    python_value_or_none(
                        row.get("agency")
                    ),

                "project_type":
                    python_value_or_none(
                        row.get("project_type")
                    ),

                "cost_original_cr":
                    clean_number(
                        row.get("cost_original")
                    ),

                "cost_revised_cr":
                    clean_number(
                        row.get("cost_revised")
                    ),

                "cost_anticipated_cr":
                    clean_number(
                        row.get("cost_anticipated")
                    ),

                "cost_overrun_cr":
                    clean_number(
                        row.get("cost_overrun")
                    ),

                "cost_overrun_pct":
                    clean_number(
                        row.get("cost_overrun_pct")
                    ),

                "cumulative_expenditure_cr":
                    clean_number(
                        row.get(
                            "cumulative_expenditure"
                        )
                    ),

                "doc_original":
                    python_date_or_none(
                        row.get("doc_original")
                    ),

                "doc_revised":
                    python_date_or_none(
                        row.get("doc_revised")
                    ),

                "doc_anticipated":
                    python_date_or_none(
                        row.get("doc_anticipated")
                    ),

                "delay_months":
                    clean_number(
                        row.get("delay_months")
                    ),

                "physical_progress_pct":
                    clean_number(
                        row.get("physical_progress")
                    ),

                "source_page":
                    (
                        int(row["page"])
                        if pd.notna(row.get("page"))
                        else None
                    ),

                "source_file":
                    python_value_or_none(
                        row.get("source_file")
                    ),

                "silver_version":
                    silver_file.stem,
            }
        )


# =========================================================
# PRE-LOAD VALIDATION
# =========================================================

print("\n" + "=" * 70)
print("PRE-LOAD VALIDATION")
print("=" * 70)

print(
    f"Total Silver rows:       {total_rows:,}"
)

print(
    f"Safe observations:       {total_safe:,}"
)

print(
    f"Unresolved observations: {total_unresolved:,}"
)

print(
    f"Records prepared:        {len(all_records):,}"
)


# Check duplicate project-period records
record_keys = [
    (
        record["project_id"],
        record["report_period"],
    )
    for record in all_records
]

duplicate_keys = (
    len(record_keys)
    - len(set(record_keys))
)

print(
    f"Duplicate project-period records: "
    f"{duplicate_keys:,}"
)

if duplicate_keys:
    raise ValueError(
        "Duplicate project-period records detected "
        "before database load."
    )


# =========================================================
# DATABASE LOAD
# =========================================================

print("\n" + "=" * 70)
print("DATABASE LOAD")
print("=" * 70)

with engine.begin() as connection:

    if all_records:

        connection.execute(
            insert_query,
            all_records,
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

    min_period, max_period = connection.execute(
        text(
            """
            SELECT
                MIN(report_period),
                MAX(report_period)
            FROM core.project_timeline
            """
        )
    ).one()


# =========================================================
# FINAL RESULT
# =========================================================

print("\n" + "=" * 70)
print("FINAL RESULT")
print("=" * 70)

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
    f"Timeline start:            {min_period}"
)

print(
    f"Timeline end:              {max_period}"
)

print(
    f"Unresolved Silver rows:     {total_unresolved:,}"
)

print("\nHistorical timeline load complete.")