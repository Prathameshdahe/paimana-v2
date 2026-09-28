import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


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

silver = pd.read_csv(SILVER_FILE)

# Same transformations as loader
silver["report_period"] = (
    pd.to_datetime(
        silver["report_date"],
        errors="coerce",
    )
    .dt.to_period("M")
    .dt.to_timestamp()
)

silver["source_project_key"] = (
    "OCMS:"
    + silver["project_id"].astype(str).str.strip()
)

with engine.connect() as connection:
    projects = pd.read_sql(
        text(
            """
            SELECT project_id, canonical_project_key
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

silver["project_id_db"] = (
    silver["source_project_key"].map(project_lookup)
)

safe = silver[
    silver["project_id_db"].notna()
].copy()


# Same date conversion as loader
for column in [
    "doc_original",
    "doc_revised",
    "doc_anticipated",
]:
    safe[column] = pd.to_datetime(
        safe[column],
        errors="coerce",
    ).dt.date


# Find the exact project from the bad DB examples
target_keys = [
    "OCMS:N18000296",
    "OCMS:N06000195",
    "OCMS:N24000592",
]


print("=" * 70)
print("VALUES BEFORE DATABASE INSERT")
print("=" * 70)

for key in target_keys:

    rows = safe[
        safe["source_project_key"] == key
    ]

    print(f"\nPROJECT: {key}")
    print("-" * 70)

    for _, row in rows.head(3).iterrows():

        print(
            "report_period:",
            repr(row["report_period"]),
            type(row["report_period"]),
        )

        print(
            "doc_original:",
            repr(row["doc_original"]),
            type(row["doc_original"]),
        )

        print(
            "doc_revised:",
            repr(row["doc_revised"]),
            type(row["doc_revised"]),
        )

        print(
            "doc_anticipated:",
            repr(row["doc_anticipated"]),
            type(row["doc_anticipated"]),
        )

        print()