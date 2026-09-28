"""App state in PostgreSQL (the app schema of database/postgres/migrations; docs/DATABASE.md): alerts, watchlist,
news signals and their links, job runs, ingested sources, briefs, research facts and judgements, second opinions,
audit log. `from backend import db` as before: every helper of the Segment 8 SQLite module keeps its name, signature
and return shape (dicts; timestamps as ISO-8601 strings, dates as YYYY-MM-DD strings, the 0/1 flags as ints), and no
module outside this package runs SQL against the database: callers that used raw connections have helpers here.

engine.py holds the one pooled engine (connect / read / healthy), migrate.py runs Alembic (init() brings the schema
to the head at every start), app.py the helpers, serve.py the loaders of pipeline/serve.py (the serving tables
core.* and ml.*), migrate_sqlite.py the one-time copy of an old database/paimana.db.
"""
from .app import *  # noqa: F401,F403 - the public helpers, listed in app.__all__
from .app import __all__ as _helpers
from .engine import Unavailable, connect, engine, healthy, read, reset
from .migrate import current, downgrade, head, truncate, upgrade

__all__ = [*_helpers, "Unavailable", "connect", "engine", "healthy", "read", "reset", "current", "downgrade", "head",
           "truncate", "upgrade"]
