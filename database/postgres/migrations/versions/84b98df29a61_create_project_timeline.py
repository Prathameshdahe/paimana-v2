"""create project timeline

Revision ID: 84b98df29a61
Revises: 001_core_identity
Create Date: 2026-09-28 00:22:46.819225

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "84b98df29a61"
down_revision: Union[str, Sequence[str], None] = "001_core_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create project-level reporting timeline."""

    op.create_table(
        "project_timeline",

        # -----------------------------------------------------
        # Primary key
        # -----------------------------------------------------
        sa.Column(
            "timeline_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        # -----------------------------------------------------
        # Project identity
        # -----------------------------------------------------
        sa.Column(
            "project_id",
            sa.BigInteger(),
            nullable=False,
        ),

        sa.Column(
            "source_project_key",
            sa.Text(),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Reporting period
        # -----------------------------------------------------
        sa.Column(
            "report_period",
            sa.Date(),
            nullable=False,
        ),

        sa.Column(
            "report_type",
            sa.Text(),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Project snapshot information
        # -----------------------------------------------------
        sa.Column(
            "project_name",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "sector_name",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "state",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "implementing_agency",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "project_type",
            sa.Text(),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Financial information
        # Values are in ₹ crore
        # -----------------------------------------------------
        sa.Column(
            "cost_original_cr",
            sa.Numeric(18, 4),
            nullable=True,
        ),

        sa.Column(
            "cost_revised_cr",
            sa.Numeric(18, 4),
            nullable=True,
        ),

        sa.Column(
            "cost_anticipated_cr",
            sa.Numeric(18, 4),
            nullable=True,
        ),

        sa.Column(
            "cost_overrun_cr",
            sa.Numeric(18, 4),
            nullable=True,
        ),

        sa.Column(
            "cost_overrun_pct",
            sa.Numeric(10, 4),
            nullable=True,
        ),

        sa.Column(
            "cumulative_expenditure_cr",
            sa.Numeric(18, 4),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Schedule information
        # -----------------------------------------------------
        sa.Column(
            "doc_original",
            sa.Date(),
            nullable=True,
        ),

        sa.Column(
            "doc_revised",
            sa.Date(),
            nullable=True,
        ),

        sa.Column(
            "doc_anticipated",
            sa.Date(),
            nullable=True,
        ),

        sa.Column(
            "delay_months",
            sa.Numeric(10, 2),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Physical progress
        # Stored as percentage, e.g. 72.5 = 72.5%
        # -----------------------------------------------------
        sa.Column(
            "physical_progress_pct",
            sa.Numeric(7, 3),
            nullable=True,
        ),

        # -----------------------------------------------------
        # Provenance
        # -----------------------------------------------------
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            nullable=True,
        ),

        sa.Column(
            "source_page",
            sa.Integer(),
            nullable=True,
        ),

        sa.Column(
            "source_file",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "silver_version",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),

        # -----------------------------------------------------
        # Foreign keys
        # -----------------------------------------------------
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["core.projects.project_id"],
            name="fk_project_timeline_project",
        ),

        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["ingest.source_documents.source_document_id"],
            name="fk_project_timeline_source_document",
        ),

        # -----------------------------------------------------
        # One project can have only one observation
        # for a particular reporting period.
        # -----------------------------------------------------
        sa.UniqueConstraint(
            "project_id",
            "report_period",
            name="uq_project_timeline_project_period",
        ),

        schema="core",
    )


def downgrade() -> None:
    """Drop project reporting timeline."""

    op.drop_table(
        "project_timeline",
        schema="core",
    )