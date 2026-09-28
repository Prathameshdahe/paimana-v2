"""Test session setup: no background loops, and the app database is paimana_test.

DATABASE_URL is pointed at the test database before any backend module is imported: TEST_DATABASE_URL when set (the
CI's Postgres service), else the configured DATABASE_URL with its database name swapped for paimana_test. The
session fixture brings that database to the migration head once (a Postgres that cannot be reached fails every
test with one clear message; the database tests are never skipped); every app table is emptied before each test
module, and a test that needs an empty database of its own takes the fresh_db fixture.
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
assert "test" in cfg.settings.database_name, cfg.settings.database_name

from backend import db  # noqa: E402


def alembic_config():
    return db.migrate.config()


@pytest.fixture(scope="session", autouse=True)
def database():
    """The test database at the migration head."""
    try:
        db.upgrade()
    except db.Unavailable as e:
        raise RuntimeError(f"PostgreSQL is not reachable at {cfg.settings.database_host} (DATABASE_URL / "
                           f"TEST_DATABASE_URL, .env.db): {str(e).splitlines()[0]}") from e
    yield
    db.reset()


@pytest.fixture(scope="module", autouse=True)
def _empty_app_tables(database):
    db.truncate()


@pytest.fixture()
def fresh_db(database):
    """An empty app schema for this test (the tests of a module otherwise share one)."""
    db.truncate()
