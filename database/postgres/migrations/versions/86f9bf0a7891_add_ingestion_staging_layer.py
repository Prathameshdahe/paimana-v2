"""add ingestion staging layer

Revision ID: 005_ingestion_staging
Revises: b704a78e671f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "005_ingestion_staging"

down_revision: Union[str, Sequence[str], None] = "004_model_artifact_checksum"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # =====================================================
    # STAGING TABLE
    # =====================================================

    op.create_table(
        "staging_project_observations",

        sa.Column(
            "staging_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        # -------------------------------------------------
        # Lineage
        # -------------------------------------------------

        sa.Column(
            "load_run_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ingest.load_runs.load_run_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ingest.source_documents.source_document_id"
            ),
        ),

        sa.Column(
            "source_row_number",
            sa.Integer(),
            nullable=False,
        ),

        # -------------------------------------------------
        # Source identity
        # -------------------------------------------------

        sa.Column(
            "source_project_key",
            sa.Text(),
        ),

        sa.Column(
            "project_name_raw",
            sa.Text(),
        ),

        # -------------------------------------------------
        # Raw source values
        #
        # Keep these as TEXT so staging preserves what
        # extraction produced before trusted conversion.
        # -------------------------------------------------

        sa.Column(
            "report_date_raw",
            sa.Text(),
        ),

        sa.Column(
            "report_type_raw",
            sa.Text(),
        ),

        sa.Column(
            "fiscal_year_raw",
            sa.Text(),
        ),

        sa.Column(
            "sector_raw",
            sa.Text(),
        ),

        sa.Column(
            "state_raw",
            sa.Text(),
        ),

        sa.Column(
            "project_type_raw",
            sa.Text(),
        ),

        sa.Column(
            "agency_raw",
            sa.Text(),
        ),

        sa.Column(
            "cost_original_raw",
            sa.Text(),
        ),

        sa.Column(
            "cost_revised_raw",
            sa.Text(),
        ),

        sa.Column(
            "cost_anticipated_raw",
            sa.Text(),
        ),

        sa.Column(
            "cost_overrun_raw",
            sa.Text(),
        ),

        sa.Column(
            "cost_overrun_pct_raw",
            sa.Text(),
        ),

        sa.Column(
            "cumulative_expenditure_raw",
            sa.Text(),
        ),

        sa.Column(
            "doc_original_raw",
            sa.Text(),
        ),

        sa.Column(
            "doc_revised_raw",
            sa.Text(),
        ),

        sa.Column(
            "doc_anticipated_raw",
            sa.Text(),
        ),

        sa.Column(
            "delay_months_raw",
            sa.Text(),
        ),

        sa.Column(
            "physical_progress_raw",
            sa.Text(),
        ),

        sa.Column(
            "source_file",
            sa.Text(),
        ),

        sa.Column(
            "source_page",
            sa.Integer(),
        ),

        # -------------------------------------------------
        # Optional parsed values
        #
        # These let validation happen without destroying
        # the original extracted representation.
        # -------------------------------------------------

        sa.Column(
            "parsed_report_period",
            sa.Date(),
        ),

        sa.Column(
            "parsed_cost_original_cr",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_cost_revised_cr",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_cost_anticipated_cr",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_cost_overrun_cr",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_cost_overrun_pct",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_cumulative_expenditure_cr",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_doc_original",
            sa.Date(),
        ),

        sa.Column(
            "parsed_doc_revised",
            sa.Date(),
        ),

        sa.Column(
            "parsed_doc_anticipated",
            sa.Date(),
        ),

        sa.Column(
            "parsed_delay_months",
            sa.Numeric(),
        ),

        sa.Column(
            "parsed_physical_progress_pct",
            sa.Numeric(),
        ),

        # -------------------------------------------------
        # Validation state
        # -------------------------------------------------

        sa.Column(
            "validation_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),

        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),

        # -------------------------------------------------
        # One source row should occur once per load run
        # -------------------------------------------------

        sa.UniqueConstraint(
            "load_run_id",
            "source_row_number",
            name="uq_staging_load_row",
        ),

        schema="ingest",
    )

    # =====================================================
    # INDEXES
    # =====================================================

    op.create_index(
        "ix_staging_project_key",
        "staging_project_observations",
        ["source_project_key"],
        schema="ingest",
    )

    op.create_index(
        "ix_staging_report_period",
        "staging_project_observations",
        ["parsed_report_period"],
        schema="ingest",
    )

    op.create_index(
        "ix_staging_validation_status",
        "staging_project_observations",
        ["validation_status"],
        schema="ingest",
    )

    op.create_index(
        "ix_staging_load_run",
        "staging_project_observations",
        ["load_run_id"],
        schema="ingest",
    )


def downgrade() -> None:

    op.drop_index(
        "ix_staging_load_run",
        table_name="staging_project_observations",
        schema="ingest",
    )

    op.drop_index(
        "ix_staging_validation_status",
        table_name="staging_project_observations",
        schema="ingest",
    )

    op.drop_index(
        "ix_staging_report_period",
        table_name="staging_project_observations",
        schema="ingest",
    )

    op.drop_index(
        "ix_staging_project_key",
        table_name="staging_project_observations",
        schema="ingest",
    )

    op.drop_table(
        "staging_project_observations",
        schema="ingest",
    )