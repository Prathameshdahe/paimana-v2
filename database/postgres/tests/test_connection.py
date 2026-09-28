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

    print("--- core.projects ---")

    result = connection.execute(
        text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'projects'
            ORDER BY ordinal_position;
        """)
    )

    for row in result:
        print(row)

    print("\n--- core.project_keys ---")

    result = connection.execute(
        text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'project_keys'
            ORDER BY ordinal_position;
        """)
    )

    for row in result:
        print(row)