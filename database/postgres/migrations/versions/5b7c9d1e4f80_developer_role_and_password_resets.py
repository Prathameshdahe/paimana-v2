"""The developer role, one pending sign-up per email, and the one-time password reset tokens (SPEC9 sections 2 and 7;
backend/auth)

Revision ID: 5b7c9d1e4f80
Revises: 4a6b8c0d3e79
Create Date: 2026-09-28

app.users.role may now be 'developer': the hidden account with every feature, created by the bootstrap only, so
signup_requests keeps its three roles. A partial unique index keeps one pending sign-up request per email (two
requests racing each other cannot both be pending). app.password_resets holds the one-time tokens an administrator
issues (POST /api/admin/users/{id}/reset-password): the sha256 of the token, never the token, who issued it, when it
expires and when it was used. The downgrade removes the developer accounts (their sessions and resets first) so the
old CHECK holds again.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5b7c9d1e4f80"
down_revision: Union[str, Sequence[str], None] = "4a6b8c0d3e79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ROLES = ("agency_official", "ministry_official", "ipmd_analyst")
ROLES = OLD_ROLES + ("developer",)


def _in(col, values):
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts(name, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", schema="app", type_="check")
    op.create_check_constraint("ck_users_role", "users", _in("role", ROLES), schema="app")
    op.create_index("signup_requests_one_pending", "signup_requests", ["email"], unique=True, schema="app",
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_table(
        "password_resets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app.users.id", ondelete="SET NULL")),
        _ts("created_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        _ts("expires_at", nullable=False),
        _ts("used_at"),
        schema="app",
    )
    op.create_index("password_resets_user", "password_resets", ["user_id"], schema="app")


def downgrade() -> None:
    op.drop_table("password_resets", schema="app")
    op.drop_index("signup_requests_one_pending", "signup_requests", schema="app")
    op.execute("DELETE FROM app.sessions WHERE user_id IN (SELECT id FROM app.users WHERE role = 'developer')")
    op.execute("UPDATE app.signup_requests SET reviewed_by = NULL "
               "WHERE reviewed_by IN (SELECT id FROM app.users WHERE role = 'developer')")
    op.execute("DELETE FROM app.users WHERE role = 'developer'")
    op.drop_constraint("ck_users_role", "users", schema="app", type_="check")
    op.create_check_constraint("ck_users_role", "users", _in("role", OLD_ROLES), schema="app")
