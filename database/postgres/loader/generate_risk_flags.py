import json
import sys
from pathlib import Path

# =========================================================
# PROJECT ROOT
# =========================================================

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# =========================================================
# IMPORTS
# =========================================================

from sqlalchemy import text

from database.postgres.config import get_engine


# =========================================================
# CONFIG
# =========================================================

SCHEDULE_THRESHOLD = 0.50
COST_THRESHOLD = 0.50


# =========================================================
# RISK FLAG GENERATION
# =========================================================

engine = get_engine()

print("=" * 70)
print("RISK FLAG GENERATOR")
print("=" * 70)


with engine.begin() as connection:

    predictions = connection.execute(
        text(
            """
            SELECT
                prediction_id,
                project_id,
                report_period,
                model_id,

                p_risk,
                risk_score,
                risk_tier,

                p_schedule_deterioration,
                p_cost_deterioration,

                expected_slip_months,
                expected_cost_pct,

                risk_rank

            FROM ml.predictions

            ORDER BY
                report_period,
                project_id,
                prediction_id;
            """
        )
    ).mappings().all()


    print(
        f"Predictions found: {len(predictions):,}"
    )


    inserted_or_updated = 0


    for prediction in predictions:

        project_id = prediction["project_id"]
        report_period = prediction["report_period"]
        model_id = prediction["model_id"]


        # =================================================
        # 1. OVERALL RISK FLAG
        # =================================================

        risk_tier = prediction["risk_tier"]

        if risk_tier in {"AMBER", "RED"}:

            severity = (
                "high"
                if risk_tier == "RED"
                else "medium"
            )

            evidence = {
                "prediction_id":
                    prediction["prediction_id"],

                "p_risk":
                    float(prediction["p_risk"])
                    if prediction["p_risk"] is not None
                    else None,

                "risk_score":
                    float(prediction["risk_score"])
                    if prediction["risk_score"] is not None
                    else None,

                "risk_tier":
                    risk_tier,

                "risk_rank":
                    prediction["risk_rank"],
            }

            connection.execute(
                text(
                    """
                    INSERT INTO ml.risk_flags (
                        project_id,
                        report_period,
                        model_id,
                        dimension,
                        flag_type,
                        severity,
                        evidence_json
                    )
                    VALUES (
                        :project_id,
                        :report_period,
                        :model_id,
                        :dimension,
                        :flag_type,
                        :severity,
                        CAST(:evidence_json AS JSONB)
                    )

                    ON CONFLICT (
                        project_id,
                        report_period,
                        model_id,
                        dimension
                    )

                    DO UPDATE SET

                        flag_type =
                            EXCLUDED.flag_type,

                        severity =
                            EXCLUDED.severity,

                        evidence_json =
                            EXCLUDED.evidence_json;
                    """
                ),
                {
                    "project_id": project_id,
                    "report_period": report_period,
                    "model_id": model_id,
                    "dimension": "overall",
                    "flag_type": (
                        "elevated_risk"
                        if risk_tier == "AMBER"
                        else "high_risk"
                    ),
                    "severity": severity,
                    "evidence_json":
                        json.dumps(evidence),
                },
            )

            inserted_or_updated += 1


        # =================================================
        # 2. SCHEDULE FLAG
        # =================================================

        p_schedule = (
            prediction[
                "p_schedule_deterioration"
            ]
        )

        if (
            p_schedule is not None
            and float(p_schedule)
                >= SCHEDULE_THRESHOLD
        ):

            evidence = {
                "prediction_id":
                    prediction["prediction_id"],

                "p_schedule_deterioration":
                    float(p_schedule),

                "expected_slip_months":
                    (
                        float(
                            prediction[
                                "expected_slip_months"
                            ]
                        )
                        if prediction[
                            "expected_slip_months"
                        ] is not None
                        else None
                    ),
            }

            connection.execute(
                text(
                    """
                    INSERT INTO ml.risk_flags (
                        project_id,
                        report_period,
                        model_id,
                        dimension,
                        flag_type,
                        severity,
                        evidence_json
                    )
                    VALUES (
                        :project_id,
                        :report_period,
                        :model_id,
                        :dimension,
                        :flag_type,
                        :severity,
                        CAST(:evidence_json AS JSONB)
                    )

                    ON CONFLICT (
                        project_id,
                        report_period,
                        model_id,
                        dimension
                    )

                    DO UPDATE SET

                        flag_type =
                            EXCLUDED.flag_type,

                        severity =
                            EXCLUDED.severity,

                        evidence_json =
                            EXCLUDED.evidence_json;
                    """
                ),
                {
                    "project_id": project_id,
                    "report_period": report_period,
                    "model_id": model_id,
                    "dimension": "schedule",
                    "flag_type":
                        "schedule_deterioration_risk",
                    "severity":
                        (
                            "high"
                            if float(p_schedule) >= 0.70
                            else "medium"
                        ),
                    "evidence_json":
                        json.dumps(evidence),
                },
            )

            inserted_or_updated += 1


        # =================================================
        # 3. COST FLAG
        # =================================================

        p_cost = (
            prediction[
                "p_cost_deterioration"
            ]
        )

        if (
            p_cost is not None
            and float(p_cost)
                >= COST_THRESHOLD
        ):

            evidence = {
                "prediction_id":
                    prediction["prediction_id"],

                "p_cost_deterioration":
                    float(p_cost),

                "expected_cost_pct":
                    (
                        float(
                            prediction[
                                "expected_cost_pct"
                            ]
                        )
                        if prediction[
                            "expected_cost_pct"
                        ] is not None
                        else None
                    ),
            }

            connection.execute(
                text(
                    """
                    INSERT INTO ml.risk_flags (
                        project_id,
                        report_period,
                        model_id,
                        dimension,
                        flag_type,
                        severity,
                        evidence_json
                    )
                    VALUES (
                        :project_id,
                        :report_period,
                        :model_id,
                        :dimension,
                        :flag_type,
                        :severity,
                        CAST(:evidence_json AS JSONB)
                    )

                    ON CONFLICT (
                        project_id,
                        report_period,
                        model_id,
                        dimension
                    )

                    DO UPDATE SET

                        flag_type =
                            EXCLUDED.flag_type,

                        severity =
                            EXCLUDED.severity,

                        evidence_json =
                            EXCLUDED.evidence_json;
                    """
                ),
                {
                    "project_id": project_id,
                    "report_period": report_period,
                    "model_id": model_id,
                    "dimension": "cost",
                    "flag_type":
                        "cost_deterioration_risk",
                    "severity":
                        (
                            "high"
                            if float(p_cost) >= 0.70
                            else "medium"
                        ),
                    "evidence_json":
                        json.dumps(evidence),
                },
            )

            inserted_or_updated += 1


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    total_flags = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ml.risk_flags
            WHERE model_id = 1;
            """
        )
    ).scalar_one()

    by_dimension = connection.execute(
        text(
            """
            SELECT
                dimension,
                COUNT(*) AS flag_count
            FROM ml.risk_flags
            WHERE model_id = 1
            GROUP BY dimension
            ORDER BY dimension;
            """
        )
    ).fetchall()


# =========================================================
# RESULT
# =========================================================

print("\n" + "=" * 70)
print("RISK FLAGS CREATED")
print("=" * 70)

print(
    f"Processed predictions: {len(predictions):,}"
)

print(
    f"Flags inserted/updated: {inserted_or_updated:,}"
)

print(
    f"Total stored flags:     {total_flags:,}"
)

print("\nBy dimension:")

for dimension, count in by_dimension:
    print(
        f"  {dimension:<15} {count}"
    )

print(
    "\nRisk flag generation complete."
)