import sys
from pathlib import Path

# ---------------------------------------------------------
# PROJECT ROOT
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

import pandas as pd
from sqlalchemy import text

from database.postgres.config import get_engine


# ---------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------

OUTPUT = (
    Path(__file__).resolve().parent
    / "sample_predictions_v1.csv"
)


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

engine = get_engine()


# ---------------------------------------------------------
# GET REAL PROJECT KEYS
# ---------------------------------------------------------

with engine.connect() as connection:

    rows = connection.execute(
        text(
            """
            SELECT
                p.canonical_project_key
            FROM core.projects p
            JOIN core.project_timeline t
                ON t.project_id = p.project_id
            WHERE t.report_period = '2025-06-01'
            ORDER BY p.project_id
            LIMIT 3;
            """
        )
    ).fetchall()


if len(rows) < 3:
    raise RuntimeError(
        "Could not find three projects "
        "for prediction fixture."
    )


# ---------------------------------------------------------
# SAMPLE PREDICTIONS
# ---------------------------------------------------------

data = [

    {
        "canonical_project_key": rows[0][0],
        "report_period": "2025-06-01",
        "model_version": "test-model-v1",

        "p_risk": 0.20,
        "risk_score": 20,
        "risk_tier": "GREEN",

        "p_schedule_deterioration": 0.15,
        "p_cost_deterioration": 0.08,

        "expected_slip_months": 1.2,
        "expected_cost_pct": 1.8,

        "slip_interval_low": 0.0,
        "slip_interval_high": 3.0,

        "cost_interval_low": 0.5,
        "cost_interval_high": 4.0,

        "risk_rank": 3,

        "shap_top5":
            '[{"feature":"delay_months","value":4,"contribution":0.12}]',

        "prediction_payload":
            '{"source":"test_fixture"}',
    },

    {
        "canonical_project_key": rows[1][0],
        "report_period": "2025-06-01",
        "model_version": "test-model-v1",

        "p_risk": 0.55,
        "risk_score": 55,
        "risk_tier": "AMBER",

        "p_schedule_deterioration": 0.48,
        "p_cost_deterioration": 0.21,

        "expected_slip_months": 3.4,
        "expected_cost_pct": 4.9,

        "slip_interval_low": 1.0,
        "slip_interval_high": 6.0,

        "cost_interval_low": 1.0,
        "cost_interval_high": 8.0,

        "risk_rank": 2,

        "shap_top5":
            '[{"feature":"physical_financial_gap_pct","value":65,"contribution":0.24}]',

        "prediction_payload":
            '{"source":"test_fixture"}',
    },

    {
        "canonical_project_key": rows[2][0],
        "report_period": "2025-06-01",
        "model_version": "test-model-v1",

        "p_risk": 0.85,
        "risk_score": 85,
        "risk_tier": "RED",

        "p_schedule_deterioration": 0.76,
        "p_cost_deterioration": 0.41,

        "expected_slip_months": 7.5,
        "expected_cost_pct": 9.2,

        "slip_interval_low": 3.0,
        "slip_interval_high": 12.0,

        "cost_interval_low": 3.0,
        "cost_interval_high": 15.0,

        "risk_rank": 1,

        "shap_top5":
            '[{"feature":"expenditure_velocity_cr","value":250,"contribution":0.31}]',

        "prediction_payload":
            '{"source":"test_fixture"}',
    },
]


# ---------------------------------------------------------
# WRITE
# ---------------------------------------------------------

output_df = pd.DataFrame(data)

output_df.to_csv(
    OUTPUT,
    index=False,
)


# ---------------------------------------------------------
# RESULT
# ---------------------------------------------------------

print("=" * 70)
print("SAMPLE PREDICTION FIXTURE CREATED")
print("=" * 70)

print(
    f"Rows: {len(output_df)}"
)

print(
    f"Output: {OUTPUT}"
)