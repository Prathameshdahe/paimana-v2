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


with engine.connect() as connection:

    rows = connection.execute(
        text(
            """
            SELECT
                column_name,
                data_type
            FROM information_schema.columns
            WHERE
                table_schema = 'ml'
                AND table_name = 'model_registry'
            ORDER BY ordinal_position;
            """
        )
    ).fetchall()

    print("=" * 70)
    print("MODEL REGISTRY COLUMNS")
    print("=" * 70)

    for row in rows:
        print(
            f"{row[0]:<35} {row[1]}"
        )