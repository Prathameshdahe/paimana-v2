import os
from datetime import date

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


with engine.begin() as connection:

    result = connection.execute(
        text(
            """
            SELECT
                CAST(:valid_date AS DATE) AS valid_date,
                CAST(:missing_date AS DATE) AS missing_date
            """
        ),
        {
            "valid_date": date(2025, 4, 1),
            "missing_date": None,
        },
    )

    row = result.fetchone()

    print("=" * 70)
    print("DATE BINDING TEST")
    print("=" * 70)

    print("Valid:", row[0], type(row[0]))
    print("Missing:", row[1], type(row[1]))
