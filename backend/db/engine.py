"""The one SQLAlchemy engine over psycopg 3 for the app's PostgreSQL (settings.database_url), shared by every thread
of the process: the request threadpool, the scheduler's job threads and the chat. A pooled connection has a 5 s
connect timeout and a 15 s statement timeout, so a hung database never holds a request. connect() is a transaction
(commit on exit, rollback on an error), read() an autocommit connection for reads, healthy() the readiness probe.
The engine is built on first use from the settings as they are then; reset() drops it (the tests repoint
DATABASE_URL).
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from backend import settings as cfg

Unavailable = (OperationalError,)      # the database cannot be reached or answered in time
CONNECT_ARGS = {"connect_timeout": 5, "options": "-c statement_timeout=15000"}
HEALTH_ARGS = {"connect_timeout": 2, "options": "-c statement_timeout=2000"}
log = logging.getLogger(__name__)
_lock = threading.Lock()
_engine: sa.Engine | None = None
_probe: sa.Engine | None = None
_url: str | None = None


def engine() -> sa.Engine:
    """The process engine, (re)built when the configured URL changed."""
    global _engine, _url
    url = cfg.settings.database_url
    if _engine is None or url != _url:
        with _lock:
            if _engine is None or url != _url:
                if _engine is not None:
                    _engine.dispose()
                _engine = sa.create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10,
                                           connect_args=CONNECT_ARGS)
                _url = url
    return _engine


def reset() -> None:
    """Dispose of the engine (a settings change, the end of a test session)."""
    global _engine, _probe, _url
    with _lock:
        for e in (_engine, _probe):
            if e is not None:
                e.dispose()
        _engine = _probe = _url = None


@contextmanager
def connect() -> Iterator[sa.Connection]:
    """A connection inside a transaction: committed on exit, rolled back when the block raises."""
    with engine().begin() as con:
        yield con


@contextmanager
def read() -> Iterator[sa.Connection]:
    """An autocommit connection for reads (no transaction to end)."""
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as con:
        yield con


def healthy() -> bool:
    """SELECT 1 within 2 s on a fresh connection; False, never an exception, when the database does not answer."""
    global _probe
    try:
        if _probe is None or _probe.url.render_as_string(hide_password=False) != cfg.settings.database_url:
            _probe = sa.create_engine(cfg.settings.database_url, poolclass=NullPool, connect_args=HEALTH_ARGS)
        with _probe.connect() as con:
            return con.execute(sa.text("SELECT 1")).scalar() == 1
    except (DBAPIError, OSError) as e:
        log.warning("database health check failed: %s", str(e).splitlines()[0])
        return False


def now() -> datetime:
    """UTC, to the second (the timestamps callers get back are ISO-8601 to the second)."""
    return datetime.now(timezone.utc).replace(microsecond=0)
