"""create core identity and ingestion tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_core_identity"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ---------------------------------------------------------
    # INGEST: source documents
    # ---------------------------------------------------------
    op.create_table(
        "source_documents",
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "filename",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "file_type",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "sha256",
            sa.String(64),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "report_period",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "report_type",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "source_path",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="ingest",
    )

    # ---------------------------------------------------------
    # INGEST: load runs
    # ---------------------------------------------------------
    op.create_table(
        "load_runs",
        sa.Column(
            "load_run_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "run_type",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "report_period",
            sa.Date(),
            nullable=True,
        ),
        sa.Column(
            "pipeline_version",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "silver_version",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "gold_version",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "model_version",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "rows_read",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "rows_loaded",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "rows_failed",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["ingest.source_documents.source_document_id"],
        ),
        schema="ingest",
    )

    # ---------------------------------------------------------
    # CORE: canonical project master
    # ---------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column(
            "project_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "canonical_project_key",
            sa.Text(),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "project_name",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "line_ministry",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "sector_name",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "implementing_agency",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="core",
    )

    # ---------------------------------------------------------
    # CORE: source-system → canonical-project mapping
    # ---------------------------------------------------------
    op.create_table(
        "project_keys",
        sa.Column(
            "project_key_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "source_system",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "source_project_key",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "source_project_name",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "match_method",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "match_score",
            sa.Numeric(6, 5),
            nullable=True,
        ),
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "merged_into",
            sa.Text(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["core.projects.project_id"],
        ),
        sa.UniqueConstraint(
            "source_system",
            "source_project_key",
            name="uq_project_keys_source_identity",
        ),
        schema="core",
    )


def downgrade() -> None:

    op.drop_table(
        "project_keys",
        schema="core",
    )

    op.drop_table(
        "projects",
        schema="core",
    )

    op.drop_table(
        "load_runs",
        schema="ingest",
    )

    op.drop_table(
        "source_documents",
        schema="ingest",
    )