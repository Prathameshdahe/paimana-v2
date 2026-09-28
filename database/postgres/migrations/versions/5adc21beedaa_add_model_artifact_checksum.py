"""add model artifact checksum

Revision ID: 004_model_artifact_checksum
Revises: b704a78e671f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_model_artifact_checksum"

down_revision: Union[str, Sequence[str], None] = "b704a78e671f"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "model_registry",
        sa.Column(
            "artifact_sha256",
            sa.Text(),
            nullable=True,
        ),
        schema="ml",
    )


def downgrade() -> None:

    op.drop_column(
        "model_registry",
        "artifact_sha256",
        schema="ml",
    )