"""Alembic environment of PAIMANA's PostgreSQL schema (alembic.ini at the repo root; docs/DATABASE.md).

The URL is the config's sqlalchemy.url when a caller set one (backend/db/migrate.py, the tests) and otherwise
settings.database_url (DATABASE_URL, or Manamrit's DB_* variables: backend/settings.py). Before the migrations run
the schemas ingest, core, ml and app are created if missing (the handoff's first migrations create tables in ingest
and core without creating the schemas) and a transaction-level advisory lock is taken, so two runners (the compose
migrate service and the API's own db.init()) never migrate at the same time. The logging of alembic.ini is applied
only when the config says so (the CLI); the backend keeps its own logging.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from backend import settings as cfg

SCHEMAS = ("ingest", "core", "ml", "app")
LOCK_KEY = 7264919      # one migration runner at a time (pg_advisory_xact_lock)

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

url = config.get_main_option("sqlalchemy.url") or cfg.settings.database_url
target_metadata = None


def run_migrations_offline() -> None:
    """Emit the SQL instead of running it (python -m alembic upgrade head --sql)."""
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        for schema in SCHEMAS:
            context.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool, connect_args={"connect_timeout": 10})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            connection.execute(text(f"SELECT pg_advisory_xact_lock({LOCK_KEY})"))
            for schema in SCHEMAS:
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
