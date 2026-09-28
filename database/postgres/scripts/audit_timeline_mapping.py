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

PROJECT_MASTER = (
    ROOT
    / "dataset"
    / "clean"
    / "projects"
    / "project_master.csv"
)


# =========================================================
# LOAD SILVER
# =========================================================

silver = pd.read_csv(SILVER_FILE)

print("=========================================================")
print("SILVER DATASET")
print("=========================================================")
print(f"Rows: {len(silver):,}")
print(f"Unique source projects: {silver['project_id'].nunique():,}")


# Convert report_date to monthly reporting period
silver["report_period"] = (
    pd.to_datetime(silver["report_date"], errors="coerce")
    .dt.to_period("M")
    .dt.to_timestamp()
)

print(
    f"Invalid report dates: "
    f"{silver['report_period'].isna().sum():,}"
)


# =========================================================
# BUILD PROJECT MASTER LOOKUP
# =========================================================

project_master = pd.read_csv(PROJECT_MASTER)

project_master["project_key"] = (
    project_master["project_key"]
    .astype(str)
    .str.strip()
)

master_keys = set(project_master["project_key"])

print("\n=========================================================")
print("PROJECT MASTER")
print("=========================================================")
print(f"Total rows: {len(project_master):,}")
print(f"Unique project keys: {len(master_keys):,}")


# =========================================================
# NORMALIZE SILVER SOURCE ID
# =========================================================

silver["canonical_source_key"] = (
    "OCMS:"
    + silver["project_id"].astype(str).str.strip()
)


# =========================================================
# CHECK DIRECT SILVER -> PROJECT MASTER MAPPING
# =========================================================

silver["master_match"] = (
    silver["canonical_source_key"].isin(master_keys)
)

total_observations = len(silver)

matched_observations = int(
    silver["master_match"].sum()
)

unmatched_observations = (
    total_observations - matched_observations
)


print("\n=========================================================")
print("DIRECT SILVER -> PROJECT MASTER MAPPING")
print("=========================================================")

print(
    f"Total Silver observations: {total_observations:,}"
)

print(
    f"Matched observations:       {matched_observations:,}"
)

print(
    f"Unmatched observations:     {unmatched_observations:,}"
)

print(
    f"Coverage:                   "
    f"{matched_observations / total_observations * 100:.2f}%"
)


# =========================================================
# UNIQUE SOURCE PROJECT COVERAGE
# =========================================================

total_source_projects = silver["project_id"].nunique()

matched_source_projects = silver.loc[
    silver["master_match"],
    "project_id"
].nunique()


print("\n=========================================================")
print("SOURCE PROJECT COVERAGE")
print("=========================================================")

print(
    "Total Silver source projects:",
    total_source_projects,
)

print(
    "Matched source projects:",
    matched_source_projects,
)

print(
    "Unmatched source projects:",
    total_source_projects - matched_source_projects,
)


# =========================================================
# CHECK PROJECT MASTER -> CORE.PROJECTS
# =========================================================

with engine.connect() as connection:

    db_projects = pd.read_sql(
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


db_keys = set(
    db_projects["canonical_project_key"]
    .dropna()
    .astype(str)
)

silver_master_keys = set(
    silver.loc[
        silver["master_match"],
        "canonical_source_key"
    ]
)

core_matches = (
    silver_master_keys & db_keys
)


print("\n=========================================================")
print("PROJECT MASTER -> CORE.PROJECTS")
print("=========================================================")

print(
    "Silver/project-master keys:",
    len(silver_master_keys),
)

print(
    "Found in core.projects:",
    len(core_matches),
)

print(
    "Missing from core.projects:",
    len(
        silver_master_keys - db_keys
    ),
)


# =========================================================
# FINAL SAFE OBSERVATIONS
# =========================================================

safe = silver[
    silver["master_match"]
    & silver["canonical_source_key"].isin(db_keys)
].copy()


print("\n=========================================================")
print("FINAL RESULT")
print("=========================================================")

print(
    "Observations safe for timeline load:",
    len(safe),
)

print(
    "Observations requiring identity handling:",
    len(silver) - len(safe),
)

print("\nNO DATABASE DATA WAS INSERTED OR UPDATED.")