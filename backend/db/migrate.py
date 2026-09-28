"""Alembic run from Python: the schema of database/postgres/migrations at the configured database (docs/DATABASE.md).

upgrade() is what db.init() runs at every backend start: idempotent (a database at the head is left alone) and
logged; the second call in a process for the same URL is a no-op until downgrade() ran. The alembic.ini logging is
not applied here (the backend has its own). truncate() empties the app schema's tables for the tests and refuses
any database whose name does not say test.
"""
from __future__ import annotations

import logging
import threading

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from backend import settings as cfg

from . import engine as eng

INI = cfg.ROOT / "alembic.ini"
log = logging.getLogger(__name__)
_lock = threading.Lock()
_at_head: set[str] = set()


def config(url: str | None = None) -> Config:
    c = Config(str(INI))
    c.set_main_option("script_location", str(cfg.ROOT / "database" / "postgres" / "migrations"))
    c.set_main_option("sqlalchemy.url", (url or cfg.settings.database_url).replace("%", "%%"))
    c.attributes["configure_logging"] = False
    return c


def head() -> str:
    return ScriptDirectory.from_config(config()).get_current_head()


def current() -> str | None:
    """The database's revision, None before the first migration."""
    with eng.read() as con:
        return MigrationContext.configure(con).get_current_revision()


def upgrade(revision: str = "head") -> str:
    """Migrate the configured database up to revision (the head); returns the revision it is at."""
    url = cfg.settings.database_url
    with _lock:
        if revision == "head" and url in _at_head:
            return head()
        before = current()
        command.upgrade(config(url), revision)
        after = current()
        if revision == "head":
            _at_head.add(url)
    log.info("database %s schema at %s%s", cfg.settings.database_name, after,
             "" if before == after else f" (from {before or 'empty'})")
    return after


def downgrade(revision: str = "base") -> str | None:
    url = cfg.settings.database_url
    with _lock:
        _at_head.discard(url)
        command.downgrade(config(url), revision)
        return current()


def truncate(schemas: tuple[str, ...] = ("app", "ingest", "core", "ml")) -> list[str]:
    """Empty every table of the schemas (identities restarted); the tests' clean slate. Refuses a database whose
    name does not contain 'test'."""
    if "test" not in cfg.settings.database_name:
        raise RuntimeError(f"refusing to truncate {cfg.settings.database_name}: not a test database")
    with eng.connect() as con:
        names = [f"{s}.{n}" for s, n in con.execute(sa.text(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema = ANY(:s) "
            "AND table_type = 'BASE TABLE'"), {"s": list(schemas)})]
        if names:
            con.execute(sa.text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))
    return names
