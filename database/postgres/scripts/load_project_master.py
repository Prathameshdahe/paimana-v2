import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

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

PROJECT_MASTER = (
    Path(__file__).resolve().parents[3]
    / "dataset"
    / "clean"
    / "projects"
    / "project_master.csv"
)


# ---------------------------------------------------------
# Load CSV
# ---------------------------------------------------------

rows = []

with open(PROJECT_MASTER, "r", encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)

    for row in reader:
        canonical_key = row["project_key"].strip()

        if not canonical_key:
            continue

        rows.append(
            {
                "canonical_project_key": canonical_key,
                "project_name": row["project_name"].strip() or None,
                "line_ministry": row["ministry"].strip() or None,
                "sector_name": row["sector"].strip() or None,
                "implementing_agency": row["agency"].strip() or None,
                "state": row["state"].strip() or None,
            }
        )


print(f"Rows prepared: {len(rows)}")


# ---------------------------------------------------------
# Insert into PostgreSQL
# ---------------------------------------------------------

insert_query = text(
    """
    INSERT INTO core.projects (
        canonical_project_key,
        project_name,
        line_ministry,
        sector_name,
        implementing_agency,
        state,
        status,
        is_current
    )
    VALUES (
        :canonical_project_key,
        :project_name,
        :line_ministry,
        :sector_name,
        :implementing_agency,
        :state,
        NULL,
        TRUE
    )
    ON CONFLICT (canonical_project_key)
    DO UPDATE SET
        project_name = EXCLUDED.project_name,
        line_ministry = EXCLUDED.line_ministry,
        sector_name = EXCLUDED.sector_name,
        implementing_agency = EXCLUDED.implementing_agency,
        state = EXCLUDED.state,
        updated_at = CURRENT_TIMESTAMP;
    """
)


with engine.begin() as connection:
    connection.execute(insert_query, rows)


# ---------------------------------------------------------
# Verification
# ---------------------------------------------------------

with engine.connect() as connection:

    count = connection.execute(
        text("SELECT COUNT(*) FROM core.projects")
    ).scalar_one()

    canonical_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM core.projects
            WHERE canonical_project_key IS NOT NULL
            """
        )
    ).scalar_one()

print(f"PROJECTS IN DATABASE: {count}")
print(f"PROJECTS WITH CANONICAL KEY: {canonical_count}")