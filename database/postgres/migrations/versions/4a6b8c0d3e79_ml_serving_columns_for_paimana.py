"""ml serving tables fitted to PAIMANA's scores and registry (pipeline/serve.py loads them)

Revision ID: 4a6b8c0d3e79
Revises: 3e5f7a9b2c68
Create Date: 2026-09-28

ml.predictions gains the served numbers as columns (the four probabilities, the slip and cost quantiles, the tier
rank percentile and the stagnation badge; SHAP, the horizon labels and the rest stay in prediction_payload) and a
CHECK that risk_tier is one of our tiers. ml.model_registry gains run_id, entry_id and feature_list_json, the
identity of an entry in model/registry.json.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a6b8c0d3e79"
down_revision: Union[str, Sequence[str], None] = "3e5f7a9b2c68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIERS = ("Critical", "High", "Medium", "Low", "Watch")
PREDICTION_COLS = ("p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "p_any_4q", "months_p05", "months_p50",
                   "months_p95", "cost_pct_p05", "cost_pct_p50", "cost_pct_p95", "tier_rank_pct")


def upgrade() -> None:
    for col in PREDICTION_COLS:
        op.add_column("predictions", sa.Column(col, sa.Float()), schema="ml")
    op.add_column("predictions", sa.Column("stagnation_override", sa.Boolean()), schema="ml")
    op.create_check_constraint("ck_predictions_risk_tier", "predictions",
                               "risk_tier IS NULL OR risk_tier IN (" + ", ".join(f"'{t}'" for t in TIERS) + ")",
                               schema="ml")
    op.add_column("model_registry", sa.Column("run_id", sa.Text()), schema="ml")
    op.add_column("model_registry", sa.Column("entry_id", sa.Text()), schema="ml")
    op.add_column("model_registry", sa.Column("feature_list_json", postgresql.JSONB()), schema="ml")
    op.create_index("model_registry_entry", "model_registry", ["entry_id"], schema="ml")


def downgrade() -> None:
    op.drop_index("model_registry_entry", table_name="model_registry", schema="ml")
    for col in ("feature_list_json", "entry_id", "run_id"):
        op.drop_column("model_registry", col, schema="ml")
    op.drop_constraint("ck_predictions_risk_tier", "predictions", schema="ml", type_="check")
    op.drop_column("predictions", "stagnation_override", schema="ml")
    for col in reversed(PREDICTION_COLS):
        op.drop_column("predictions", col, schema="ml")
