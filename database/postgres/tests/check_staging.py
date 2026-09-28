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
    print("INGEST STAGING CHECK")
    print("=" * 70)

    columns = connection.execute(
        text(
            """
            SELECT
                column_name,
                data_type
            FROM information_schema.columns
            WHERE
                table_schema = 'ingest'
                AND table_name =
                    'staging_project_observations'
            ORDER BY ordinal_position;
            """
        )
    ).fetchall()

    print("\nCOLUMNS:")

    for column_name, data_type in columns:
        print(
            f"{column_name:<40} {data_type}"
        )

    count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ingest.staging_project_observations;
            """
        )
    ).scalar_one()

    print(
        f"\nRows currently staged: {count}"
    )

    version = connection.execute(
        text(
            """
            SELECT version_num
            FROM alembic_version;
            """
        )
    ).scalar_one()

    print(
        f"Alembic version: {version}"
    )