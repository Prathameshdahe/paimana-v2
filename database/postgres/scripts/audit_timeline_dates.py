import os

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


query = """
SELECT
    timeline_id,
    project_id,
    source_project_key,
    report_period::text,
    doc_original::text,
    doc_revised::text,
    doc_anticipated::text,
    source_file,
    source_page
FROM core.project_timeline
WHERE
       EXTRACT(YEAR FROM doc_original) > 2100
    OR EXTRACT(YEAR FROM doc_revised) > 2100
    OR EXTRACT(YEAR FROM doc_anticipated) > 2100
    OR EXTRACT(YEAR FROM doc_original) < 1900
    OR EXTRACT(YEAR FROM doc_revised) < 1900
    OR EXTRACT(YEAR FROM doc_anticipated) < 1900
ORDER BY timeline_id;
"""


with engine.connect() as connection:
    rows = connection.execute(
        text(query)
    ).fetchall()


print("=" * 70)
print("OUT-OF-RANGE TIMELINE DATES")
print("=" * 70)

print(f"Bad rows: {len(rows)}")

for row in rows[:50]:
    print(row)