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

    print("=" * 70)
    print("ML SCHEMA CHECK")
    print("=" * 70)

    tables = connection.execute(
        text(
            """
            SELECT
                table_schema,
                table_name
            FROM information_schema.tables
            WHERE table_schema = 'ml'
            ORDER BY table_name;
            """
        )
    ).fetchall()

    print("\nTABLES:")

    for row in tables:
        print(
            f"  {row[0]}.{row[1]}"
        )

    views = connection.execute(
        text(
            """
            SELECT
                table_schema,
                table_name
            FROM information_schema.views
            WHERE table_schema = 'ml'
            ORDER BY table_name;
            """
        )
    ).fetchall()

    print("\nVIEWS:")

    for row in views:
        print(
            f"  {row[0]}.{row[1]}"
        )

    version = connection.execute(
        text(
            "SELECT version_num FROM alembic_version"
        )
    ).scalar_one()

    print(
        f"\nAlembic version: {version}"
    )