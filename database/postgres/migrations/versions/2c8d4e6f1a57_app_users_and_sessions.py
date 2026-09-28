"""app.users, app.sessions, app.signup_requests, app.login_attempts (SPEC9 section 2; the logic is backend/auth/)

Revision ID: 2c8d4e6f1a57
Revises: 1f3a9c2d7b40
Create Date: 2026-09-28

Emails are citext (case-insensitive uniqueness). The public has no users row; an ipmd_analyst with is_admin is the
administrator. sessions.id is the sha256 of the cookie token, never the token. audit_log gains the columns the
authenticated write routes fill: user_id, email, ip.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2c8d4e6f1a57"
down_revision: Union[str, Sequence[str], None] = "1f3a9c2d7b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = ("agency_official", "ministry_official", "ipmd_analyst")


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _in(col, values):
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("ministry", sa.Text()),
        sa.Column("agency", sa.Text()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _ts("locked_until"),
        _ts("password_changed_at"),
        _ts("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _ts("last_login_at"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_users_role"),
        sa.CheckConstraint(_in("status", ("active", "disabled")), name="ck_users_status"),
        schema="app",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.users.id"), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        _ts("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _ts("expires_at", nullable=False),
        _ts("last_seen_at"),
        sa.Column("ip", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        _ts("revoked_at"),
        schema="app",
    )
    op.create_index("sessions_user", "sessions", ["user_id"], schema="app")
    op.create_index("sessions_expires", "sessions", ["expires_at"], schema="app")
    op.create_table(
        "signup_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("ministry", sa.Text()),
        sa.Column("agency", sa.Text()),
        sa.Column("justification", sa.Text()),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        _ts("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("reviewed_by", sa.BigInteger(), sa.ForeignKey("app.users.id")),
        _ts("reviewed_at"),
        sa.Column("review_note", sa.Text()),
        sa.Column("ip", postgresql.INET()),
        sa.CheckConstraint(_in("role", ROLES), name="ck_signup_requests_role"),
        sa.CheckConstraint(_in("status", ("pending", "approved", "rejected")), name="ck_signup_requests_status"),
        schema="app",
    )
    op.create_index("signup_requests_email_status", "signup_requests", ["email", "status"], schema="app")
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", postgresql.CITEXT()),
        sa.Column("ip", postgresql.INET()),
        _ts("at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ok", sa.Boolean(), nullable=False),
        schema="app",
    )
    op.create_index("login_attempts_email_at", "login_attempts", ["email", "at"], schema="app")
    op.create_index("login_attempts_ip_at", "login_attempts", ["ip", "at"], schema="app")
    op.add_column("audit_log", sa.Column("user_id", sa.BigInteger()), schema="app")
    op.add_column("audit_log", sa.Column("email", sa.Text()), schema="app")
    op.add_column("audit_log", sa.Column("ip", postgresql.INET()), schema="app")


def downgrade() -> None:
    for col in ("ip", "email", "user_id"):
        op.drop_column("audit_log", col, schema="app")
    for table in ("login_attempts", "signup_requests", "sessions", "users"):
        op.drop_table(table, schema="app")
