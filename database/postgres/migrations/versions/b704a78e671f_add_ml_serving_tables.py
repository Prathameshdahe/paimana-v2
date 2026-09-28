"""add ml serving tables

Revision ID: b704a78e671f
Revises: 84b98df29a61
Create Date: 2026-09-28 01:40:30.974028

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# =========================================================
# REVISION IDENTIFIERS
# =========================================================

revision: str = "b704a78e671f"

down_revision: Union[str, Sequence[str], None] = "84b98df29a61"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


# =========================================================
# UPGRADE
# =========================================================

def upgrade() -> None:

    # -----------------------------------------------------
    # Ensure ML schema exists
    # -----------------------------------------------------

    op.execute(
        "CREATE SCHEMA IF NOT EXISTS ml"
    )

    # =====================================================
    # 1. MODEL REGISTRY
    # =====================================================

    op.create_table(
        "model_registry",

        sa.Column(
            "model_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "model_name",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "model_version",
            sa.Text(),
            nullable=False,
            unique=True,
        ),

        sa.Column(
            "model_type",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "target_name",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "feature_version",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "gold_version",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "training_start_period",
            sa.Date(),
        ),

        sa.Column(
            "training_end_period",
            sa.Date(),
        ),

        sa.Column(
            "validation_start_period",
            sa.Date(),
        ),

        sa.Column(
            "validation_end_period",
            sa.Date(),
        ),

        sa.Column(
            "test_start_period",
            sa.Date(),
        ),

        sa.Column(
            "test_end_period",
            sa.Date(),
        ),

        sa.Column(
            "metrics_json",
            postgresql.JSONB(),
        ),

        sa.Column(
            "hyperparameters_json",
            postgresql.JSONB(),
        ),

        sa.Column(
            "artifact_path",
            sa.Text(),
        ),

        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'registered'"),
        ),

        sa.Column(
            "is_champion",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),

        schema="ml",
    )

    # One champion model per target
    op.create_index(
        "uq_model_registry_target_champion",
        "model_registry",
        ["target_name"],
        unique=True,
        schema="ml",
        postgresql_where=sa.text(
            "is_champion = TRUE"
        ),
    )

    # =====================================================
    # 2. PREDICTIONS
    # =====================================================

    op.create_table(
        "predictions",

        sa.Column(
            "prediction_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "core.projects.project_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "report_period",
            sa.Date(),
            nullable=False,
        ),

        sa.Column(
            "model_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ml.model_registry.model_id"
            ),
            nullable=False,
        ),

        # -------------------------------------------------
        # Prediction outputs
        # -------------------------------------------------

        sa.Column(
            "p_risk",
            sa.Numeric(8, 6),
        ),

        sa.Column(
            "risk_score",
            sa.Numeric(6, 2),
        ),

        sa.Column(
            "risk_tier",
            sa.Text(),
        ),

        sa.Column(
            "p_schedule_deterioration",
            sa.Numeric(8, 6),
        ),

        sa.Column(
            "p_cost_deterioration",
            sa.Numeric(8, 6),
        ),

        sa.Column(
            "expected_slip_months",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "expected_cost_pct",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "slip_interval_low",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "slip_interval_high",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "cost_interval_low",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "cost_interval_high",
            sa.Numeric(10, 2),
        ),

        sa.Column(
            "risk_rank",
            sa.Integer(),
        ),

        # -------------------------------------------------
        # Explainability / raw serving payload
        # -------------------------------------------------

        sa.Column(
            "shap_top5_json",
            postgresql.JSONB(),
        ),

        sa.Column(
            "prediction_payload",
            postgresql.JSONB(),
        ),

        # -------------------------------------------------
        # Realised outcome
        #
        # Filled later from Gold labels.
        # Never generated independently here.
        # -------------------------------------------------

        sa.Column(
            "realised_target_6m",
            sa.Boolean(),
        ),

        sa.Column(
            "realised_schedule_deterioration_6m",
            sa.Boolean(),
        ),

        sa.Column(
            "realised_cost_deterioration_6m",
            sa.Boolean(),
        ),

        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
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
        # One prediction per project-period-model
        # -------------------------------------------------

        sa.UniqueConstraint(
            "project_id",
            "report_period",
            "model_id",
            name="uq_predictions_project_period_model",
        ),

        # -------------------------------------------------
        # Basic probability / score validation
        # -------------------------------------------------

        sa.CheckConstraint(
            """
            p_risk IS NULL
            OR (
                p_risk >= 0
                AND p_risk <= 1
            )
            """,
            name="ck_predictions_p_risk",
        ),

        sa.CheckConstraint(
            """
            risk_score IS NULL
            OR (
                risk_score >= 0
                AND risk_score <= 100
            )
            """,
            name="ck_predictions_risk_score",
        ),

        schema="ml",
    )

    op.create_index(
        "ix_predictions_project_period",
        "predictions",
        ["project_id", "report_period"],
        schema="ml",
    )

    # =====================================================
    # 3. RISK FLAGS
    # =====================================================

    op.create_table(
        "risk_flags",

        sa.Column(
            "risk_flag_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "core.projects.project_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "report_period",
            sa.Date(),
            nullable=False,
        ),

        sa.Column(
            "model_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ml.model_registry.model_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "dimension",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "flag_type",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "severity",
            sa.Text(),
        ),

        sa.Column(
            "evidence_json",
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

        sa.UniqueConstraint(
            "project_id",
            "report_period",
            "model_id",
            "dimension",
            name="uq_risk_flags_project_period_model_dimension",
        ),

        schema="ml",
    )

    op.create_index(
        "ix_risk_flags_project_period",
        "risk_flags",
        ["project_id", "report_period"],
        schema="ml",
    )

    # =====================================================
    # 4. FORECASTS
    # =====================================================

    op.create_table(
        "forecasts",

        sa.Column(
            "forecast_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "core.projects.project_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "report_period",
            sa.Date(),
            nullable=False,
        ),

        sa.Column(
            "model_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ml.model_registry.model_id"
            ),
            nullable=False,
        ),

        # Flexible payload for:
        # fan chart / scenarios / analogue information etc.
        sa.Column(
            "forecast_payload",
            postgresql.JSONB(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP"
            ),
        ),

        sa.UniqueConstraint(
            "project_id",
            "report_period",
            "model_id",
            name="uq_forecasts_project_period_model",
        ),

        schema="ml",
    )

    op.create_index(
        "ix_forecasts_project_period",
        "forecasts",
        ["project_id", "report_period"],
        schema="ml",
    )

    # =====================================================
    # 5. AGENCY STATS
    # =====================================================

    op.create_table(
        "agency_stats",

        sa.Column(
            "agency_stats_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),

        sa.Column(
            "agency_name",
            sa.Text(),
            nullable=False,
        ),

        sa.Column(
            "report_period",
            sa.Date(),
            nullable=False,
        ),

        sa.Column(
            "model_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "ml.model_registry.model_id"
            ),
            nullable=False,
        ),

        sa.Column(
            "project_count",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "green_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),

        sa.Column(
            "amber_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),

        sa.Column(
            "red_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),

        sa.Column(
            "avg_risk_score",
            sa.Numeric(6, 2),
        ),

        sa.Column(
            "stats_payload",
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

        sa.UniqueConstraint(
            "agency_name",
            "report_period",
            "model_id",
            name="uq_agency_stats_agency_period_model",
        ),

        schema="ml",
    )

    op.create_index(
        "ix_agency_stats_period",
        "agency_stats",
        ["report_period"],
        schema="ml",
    )

    # =====================================================
    # 6. CURRENT PREDICTIONS VIEW
    # =====================================================

    op.execute(
        """
        CREATE OR REPLACE VIEW ml.current_predictions AS

        SELECT
            p.prediction_id,
            p.project_id,
            c.canonical_project_key,
            p.report_period,
            p.model_id,

            m.model_name,
            m.model_version,
            m.target_name,

            p.p_risk,
            p.risk_score,
            p.risk_tier,

            p.p_schedule_deterioration,
            p.p_cost_deterioration,

            p.expected_slip_months,
            p.expected_cost_pct,

            p.slip_interval_low,
            p.slip_interval_high,

            p.cost_interval_low,
            p.cost_interval_high,

            p.risk_rank,

            p.shap_top5_json,
            p.prediction_payload,

            p.created_at

        FROM ml.predictions p

        JOIN ml.model_registry m
            ON m.model_id = p.model_id

        JOIN core.projects c
            ON c.project_id = p.project_id

        WHERE
            m.is_champion = TRUE

            AND p.prediction_id IN (

                SELECT DISTINCT ON (
                    project_id,
                    model_id
                )
                    prediction_id

                FROM ml.predictions

                ORDER BY
                    project_id,
                    model_id,
                    report_period DESC,
                    created_at DESC,
                    prediction_id DESC
            );
        """
    )


# =========================================================
# DOWNGRADE
# =========================================================

def downgrade() -> None:

    op.execute(
        "DROP VIEW IF EXISTS ml.current_predictions"
    )

    op.drop_index(
        "ix_agency_stats_period",
        table_name="agency_stats",
        schema="ml",
    )

    op.drop_index(
        "ix_forecasts_project_period",
        table_name="forecasts",
        schema="ml",
    )

    op.drop_index(
        "ix_risk_flags_project_period",
        table_name="risk_flags",
        schema="ml",
    )

    op.drop_index(
        "ix_predictions_project_period",
        table_name="predictions",
        schema="ml",
    )

    op.drop_index(
        "uq_model_registry_target_champion",
        table_name="model_registry",
        schema="ml",
    )

    op.drop_table(
        "agency_stats",
        schema="ml",
    )

    op.drop_table(
        "forecasts",
        schema="ml",
    )

    op.drop_table(
        "risk_flags",
        schema="ml",
    )

    op.drop_table(
        "predictions",
        schema="ml",
    )

    op.drop_table(
        "model_registry",
        schema="ml",
    )