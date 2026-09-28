"""app.briefs keyed by view as well: the numbers policy's two briefs of one project

Revision ID: 6c8e0a2b4d91
Revises: 5b7c9d1e4f80
Create Date: 2026-09-28

The project brief (backend/brief.py) is written in two views: 'numbers' for the developer (the model's probabilities,
intervals and SHAP drivers) and 'plain' for everyone else (the outlook in words). Each is cached on its own, so
app.briefs gains a view column (the briefs already stored were written from the numbers payload: 'numbers') and its
primary key becomes (project_key, asof, model_version, view). The downgrade drops the plain briefs and the column.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6c8e0a2b4d91"
down_revision: Union[str, Sequence[str], None] = "5b7c9d1e4f80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("briefs", sa.Column("view", sa.Text(), nullable=False, server_default="numbers"), schema="app")
    op.create_check_constraint("ck_briefs_view", "briefs", "view IN ('numbers', 'plain')", schema="app")
    op.drop_constraint("briefs_pkey", "briefs", schema="app", type_="primary")
    op.create_primary_key("briefs_pkey", "briefs", ["project_key", "asof", "model_version", "view"], schema="app")


def downgrade() -> None:
    op.execute("DELETE FROM app.briefs WHERE view <> 'numbers'")
    op.drop_constraint("briefs_pkey", "briefs", schema="app", type_="primary")
    op.create_primary_key("briefs_pkey", "briefs", ["project_key", "asof", "model_version"], schema="app")
    op.drop_constraint("ck_briefs_view", "briefs", schema="app", type_="check")
    op.drop_column("briefs", "view", schema="app")
