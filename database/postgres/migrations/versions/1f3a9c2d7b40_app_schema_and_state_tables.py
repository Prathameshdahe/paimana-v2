"""app schema: the application state that lived in SQLite (backend/db.py of Segment 8)

Revision ID: 1f3a9c2d7b40
Revises: 005_ingestion_staging
Create Date: 2026-09-28

The tables keep the names and columns of the SQLite SCHEMA: sources, job_runs, alerts, watchlist, signals,
signal_projects, scouted, audit_log, briefs, research_facts, researched, signal_judgements, second_opinions, with
PostgreSQL types (timestamptz for *_at, date for asof and the fact dates, boolean for the 0/1 flags, jsonb for the
*_json and json columns, bigserial ids) and the same CHECK constraints (the alert kinds, severity 1..3). audit_log
gains an id (SQLite ordered it by rowid). sources.period stays text: it is a month, YYYY-MM.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1f3a9c2d7b40"
down_revision: Union[str, Sequence[str], None] = "005_ingestion_staging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALERT_KINDS = ("tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice", "pipeline_error")
TABLES = ("second_opinions", "signal_judgements", "researched", "research_facts", "briefs", "audit_log", "scouted",
          "signal_projects", "signals", "watchlist", "alerts", "job_runs", "sources")


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.create_table(
        "sources",
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text()),
        sa.Column("kind", sa.Text()),
        sa.Column("period", sa.Text()),
        sa.Column("rows", sa.Integer()),
        _ts("ingested_at"),
        sa.Column("status", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("archived_as", sa.Text()),
        sa.PrimaryKeyConstraint("sha256", "pipeline_version"),
        schema="app",
    )
    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job", sa.Text(), nullable=False),
        _ts("started_at"),
        _ts("finished_at"),
        sa.Column("status", sa.Text()),
        sa.Column("summary_json", postgresql.JSONB()),
        schema="app",
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _ts("created_at", nullable=False),
        sa.Column("project_key", sa.Text()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("asof", sa.Date()),
        sa.Column("model_version", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("acked_by", sa.Text()),
        _ts("acked_at"),
        sa.CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in ALERT_KINDS) + ")", name="ck_alerts_kind"),
        sa.CheckConstraint("severity BETWEEN 1 AND 3", name="ck_alerts_severity"),
        schema="app",
    )
    op.create_index("alerts_created", "alerts", ["created_at"], schema="app")
    op.create_index("alerts_project", "alerts", ["project_key"], schema="app")
    op.create_table(
        "watchlist",
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("project_key", sa.Text(), nullable=False),
        _ts("added_at"),
        sa.PrimaryKeyConstraint("role", "project_key"),
        schema="app",
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.Text(), unique=True),
        sa.Column("url_hash", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("source", sa.Text()),
        _ts("published_at"),
        _ts("fetched_at"),
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.Text()),
        sa.Column("severity", sa.Integer()),
        sa.Column("text_hash", sa.Text()),
        schema="app",
    )
    op.create_index("signals_text", "signals", ["text_hash"], schema="app")
    op.create_index("signals_published", "signals", ["published_at"], schema="app")
    op.create_table(
        "signal_projects",
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signals.id"), nullable=False),
        sa.Column("project_key", sa.Text(), nullable=False),
        sa.Column("link_score", sa.Float()),
        sa.Column("method", sa.Text()),
        sa.PrimaryKeyConstraint("signal_id", "project_key"),
        schema="app",
    )
    op.create_index("signal_projects_key", "signal_projects", ["project_key"], schema="app")
    op.create_table(
        "scouted",
        sa.Column("project_key", sa.Text(), primary_key=True),
        _ts("scouted_at", nullable=False),
        sa.Column("n_items", sa.Integer()),
        schema="app",
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        _ts("at", nullable=False),
        sa.Column("role", sa.Text()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target", sa.Text()),
        sa.Column("detail", sa.Text()),
        schema="app",
    )
    op.create_index("audit_log_at", "audit_log", ["at"], schema="app")
    op.create_table(
        "briefs",
        sa.Column("project_key", sa.Text(), nullable=False),
        sa.Column("asof", sa.Date(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        _ts("generated_at"),
        sa.Column("text", sa.Text()),
        sa.Column("n_numbers_checked", sa.Integer()),
        sa.Column("attempts", sa.Integer()),
        sa.PrimaryKeyConstraint("project_key", "asof", "model_version"),
        schema="app",
    )
    op.create_table(
        "research_facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("project_key", sa.Text(), nullable=False),
        sa.Column("category", sa.Text()),
        sa.Column("taxonomy", sa.Text()),
        sa.Column("direction", sa.Text()),
        sa.Column("severity", sa.Integer()),
        sa.Column("event_date", sa.Date()),
        sa.Column("date_precision", sa.Text()),
        sa.Column("published_date", sa.Date()),
        sa.Column("status", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("headline", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("domain", sa.Text()),
        sa.Column("match", sa.Text()),
        sa.Column("match_reason", sa.Text()),
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'agent'")),
        sa.Column("researched_on", sa.Date()),
        sa.Column("live", sa.Boolean()),
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signals.id")),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_version", sa.Text()),
        _ts("judged_at"),
        schema="app",
    )
    op.create_index("research_facts_key", "research_facts", ["project_key"], schema="app")
    op.create_table(
        "researched",
        sa.Column("project_key", sa.Text(), primary_key=True),
        _ts("researched_at", nullable=False),
        sa.Column("n_candidates", sa.Integer()),
        sa.Column("n_relevant", sa.Integer()),
        schema="app",
    )
    op.create_table(
        "signal_judgements",
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signals.id"), nullable=False),
        sa.Column("project_key", sa.Text(), nullable=False),
        sa.Column("relevant", sa.Boolean()),
        sa.Column("verdict_json", postgresql.JSONB()),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_version", sa.Text()),
        _ts("judged_at"),
        sa.PrimaryKeyConstraint("signal_id", "project_key"),
        schema="app",
    )
    op.create_table(
        "second_opinions",
        sa.Column("project_key", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text()),
        sa.Column("asof", sa.Date()),
        _ts("generated_at"),
        sa.Column("json", postgresql.JSONB()),
        sa.PrimaryKeyConstraint("project_key", "evidence_hash", "model"),
        schema="app",
    )


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table, schema="app")
