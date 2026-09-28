"""Test session setup: no background loops, and the app database is paimana_test.

DATABASE_URL is pointed at the test database before any backend module is imported: TEST_DATABASE_URL when set (the
CI's Postgres service), else the configured DATABASE_URL with its database name swapped for paimana_test. The
session fixture brings that database to the migration head once; a Postgres that cannot be reached fails every
test with one clear message (the database tests are never skipped).
"""
import os

import pytest

os.environ["LIVE_JOBS"] = "0"  # no background watcher / scout loops in tests (backend/live/scheduler.py)

from backend import settings as cfg  # noqa: E402

TEST_DB = "paimana_test"


def _test_url(url: str) -> str:
    head, name = url.rsplit("/", 1)
    return f"{head}/{TEST_DB}" + (name[name.index("?"):] if "?" in name else "")


os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or _test_url(cfg.settings.database_url)
cfg.reload()
assert cfg.settings.database_name == TEST_DB or os.environ.get("TEST_DATABASE_URL")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402


def alembic_config() -> Config:
    c = Config(str(cfg.ROOT / "alembic.ini"))
    c.set_main_option("sqlalchemy.url", cfg.settings.database_url.replace("%", "%%"))
    c.attributes["configure_logging"] = False
    return c


@pytest.fixture(scope="session", autouse=True)
def database():
    """The test database at the migration head."""
    try:
        command.upgrade(alembic_config(), "head")
    except OperationalError as e:
        raise RuntimeError(f"PostgreSQL is not reachable at {cfg.settings.database_host} (DATABASE_URL / "
                           f"TEST_DATABASE_URL, .env.db): {str(e).splitlines()[0]}") from e
