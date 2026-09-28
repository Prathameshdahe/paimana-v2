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


with engine.connect() as c:

    print("=========================================================")
    print("QUERY 1: PERIOD DISTRIBUTION")
    print("=========================================================")

    result = c.execute(text("""
        SELECT
            report_period,
            COUNT(*) AS observations,
            COUNT(DISTINCT project_id) AS projects
        FROM core.project_timeline
        GROUP BY report_period
        ORDER BY report_period;
    """))

    df = pd.DataFrame(result.fetchall(), columns=result.keys())
    print(df.to_string(index=False))


    print("\n=========================================================")
    print("QUERY 2: DUPLICATE PROJECT-PERIOD CHECK")
    print("=========================================================")

    result = c.execute(text("""
        SELECT
            project_id,
            report_period,
            COUNT(*) AS row_count
        FROM core.project_timeline
        GROUP BY project_id, report_period
        HAVING COUNT(*) > 1;
    """))

    rows = result.fetchall()
    if rows:
        df = pd.DataFrame(rows, columns=result.keys())
        print(df.to_string(index=False))
    else:
        print("0 rows — no duplicates found. PASS")


    print("\n=========================================================")
    print("QUERY 3: BASIC COMPLETENESS")
    print("=========================================================")

    result = c.execute(text("""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT project_id) AS projects,
            COUNT(DISTINCT report_period) AS periods,
            COUNT(*) FILTER (
                WHERE physical_progress_pct IS NOT NULL
            ) AS progress_present,
            COUNT(*) FILTER (
                WHERE cumulative_expenditure_cr IS NOT NULL
            ) AS expenditure_present,
            COUNT(*) FILTER (
                WHERE cost_original_cr IS NOT NULL
            ) AS original_cost_present
        FROM core.project_timeline;
    """))

    row = result.fetchone()
    keys = result.keys()
    for k, v in zip(keys, row):
        print(f"  {k}: {v:,}")


    print("\n=========================================================")
    print("QUERY 4: SAMPLE ROWS")
    print("=========================================================")

    result = c.execute(text("""
        SELECT
            project_id,
            source_project_key,
            report_period,
            project_name,
            cost_original_cr,
            cost_revised_cr,
            cumulative_expenditure_cr,
            physical_progress_pct,
            delay_months
        FROM core.project_timeline
        ORDER BY project_id, report_period
        LIMIT 20;
    """))

    df = pd.DataFrame(result.fetchall(), columns=result.keys())
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 30)
    print(df.to_string(index=False))
