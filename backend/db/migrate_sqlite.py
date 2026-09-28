"""One-time copy of an old SQLite app database (database/paimana.db of Segment 8 and before) into PostgreSQL:

    python -m backend.db.migrate_sqlite database/paimana.db

Every table of the old SCHEMA that the file has is copied into the app schema (alerts, watchlist, signals,
signal_projects, scouted, audit_log, briefs, research_facts, researched, signal_judgements, second_opinions,
job_runs, sources), ids kept (the stream and the links refer to them) and the sequences moved past them. Idempotent:
INSERT ... ON CONFLICT DO NOTHING, so a second run copies nothing. The counts are printed per table. The schema must
be at the head (db.init() or python -m alembic upgrade head). This is the only module that still reads SQLite.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import sqlalchemy as sa

from backend import settings as cfg

from . import app, migrate
from .engine import connect, read

TABLES = ("sources", "job_runs", "alerts", "watchlist", "signals", "signal_projects", "scouted", "audit_log",
          "briefs", "research_facts", "researched", "signal_judgements", "second_opinions")
CONFLICT = {"sources": "(sha256, pipeline_version)", "job_runs": "(id)", "alerts": "(id)", "watchlist":
            "(role, project_key)", "signals": "(id)", "signal_projects": "(signal_id, project_key)",
            "scouted": "(project_key)", "audit_log": "(id)", "briefs": "(project_key, asof, model_version, view)",
            "research_facts": "(fact_id)", "researched": "(project_key)",
            "signal_judgements": "(signal_id, project_key)", "second_opinions": "(project_key, evidence_hash, model)"}
SERIAL = ("job_runs", "alerts", "signals", "audit_log")
CHUNK = 500


def _columns(con, table: str) -> set[str]:
    return {r[0] for r in con.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE "
                                              "table_schema = 'app' AND table_name = :t"), {"t": table})}


def _count(con, table: str) -> int:
    return con.execute(sa.text(f"SELECT count(*) FROM app.{table}")).scalar()


def copy_table(src: sqlite3.Connection, table: str) -> tuple[int, int]:
    """Copy one table; returns (rows in the file, rows now in PostgreSQL)."""
    rows = [dict(r) for r in src.execute(f"SELECT rowid AS rowid_, * FROM {table}")]
    with connect() as con:
        cols = _columns(con, table)
        if table == "audit_log":
            for r in rows:
                r["id"] = r.pop("rowid_")
        keep = [c for c in (rows[0] if rows else {}) if c in cols]
        if rows:
            values = ", ".join(f"CAST(:{c} AS jsonb)" if c in app.JSON else f":{c}" for c in keep)
            sql = sa.text(f"INSERT INTO app.{table} ({', '.join(f'\"{c}\"' for c in keep)}) VALUES ({values}) "
                          f"ON CONFLICT {CONFLICT[table]} DO NOTHING")
            for i in range(0, len(rows), CHUNK):
                con.execute(sql, [app._in({c: r.get(c) for c in keep}) for r in rows[i:i + CHUNK]])
        if table in SERIAL:
            con.execute(sa.text(f"SELECT setval(pg_get_serial_sequence('app.{table}', 'id'), "
                                f"coalesce((SELECT max(id) FROM app.{table}), 1), "
                                f"(SELECT max(id) FROM app.{table}) IS NOT NULL)"))
        return len(rows), _count(con, table)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.db.migrate_sqlite",
                                 description="copy an old SQLite app database into PostgreSQL once")
    ap.add_argument("path", help="the SQLite file, e.g. database/paimana.db")
    args = ap.parse_args(argv)
    path = Path(args.path)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    migrate.upgrade()
    print(f"{path} -> {cfg.settings.database_host}")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as src:
        src.row_factory = sqlite3.Row
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        total = 0
        for table in TABLES:
            if table not in have:
                print(f"  {table:<18} not in the file")
                continue
            with read() as con:
                before = _count(con, table)
            n, after = copy_table(src, table)
            total += after - before
            print(f"  {table:<18} {n:>7} in the file, {after - before:>7} copied, {after:>7} now in PostgreSQL")
    print(f"{total} rows copied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
