import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
import math

import pandas as pd
from sqlalchemy import text

from database.postgres.config import get_engine


# =========================================================
# CONFIG
# =========================================================

REQUIRED_COLUMNS = [
    "report_period",
    "model_version",
    "p_risk",
    "risk_score",
    "risk_tier",
]

OPTIONAL_COLUMNS = [
    "project_id",
    "canonical_project_key",
    "p_schedule_deterioration",
    "p_cost_deterioration",
    "expected_slip_months",
    "expected_cost_pct",
    "slip_interval_low",
    "slip_interval_high",
    "cost_interval_low",
    "cost_interval_high",
    "risk_rank",
    "shap_top5",
    "prediction_payload",
]


# =========================================================
# HELPERS
# =========================================================

def clean_value(value):
    if pd.isna(value):
        return None

    if isinstance(value, float) and math.isnan(value):
        return None

    return value


def clean_probability(value, field_name):
    value = clean_value(value)

    if value is None:
        return None

    value = float(value)

    if not 0 <= value <= 1:
        raise ValueError(
            f"{field_name} must be between 0 and 1. "
            f"Received: {value}"
        )

    return value


def clean_risk_score(value):
    value = clean_value(value)

    if value is None:
        return None

    value = float(value)

    if not 0 <= value <= 100:
        raise ValueError(
            f"risk_score must be between 0 and 100. "
            f"Received: {value}"
        )

    return value


def parse_json_value(value):
    value = clean_value(value)

    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return None

        return json.loads(value)

    raise ValueError(
        f"Unsupported JSON value type: {type(value)}"
    )


def load_file(path):
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path)

    if suffix == ".parquet":
        try:
            return pd.read_parquet(path)
        except ImportError as exc:
            raise RuntimeError(
                "Parquet support requires pyarrow. "
                "Install it with: pip install pyarrow"
            ) from exc

    raise ValueError(
        "Supported prediction files: .csv or .parquet"
    )


# =========================================================
# CLI
# =========================================================

parser = argparse.ArgumentParser(
    description="Load ML predictions into ml.predictions."
)

parser.add_argument(
    "prediction_file",
)

args = parser.parse_args()

prediction_path = Path(
    args.prediction_file
).resolve()

if not prediction_path.exists():
    raise FileNotFoundError(
        f"Prediction file not found: {prediction_path}"
    )


# =========================================================
# LOAD
# =========================================================

df = load_file(prediction_path)

print("=" * 70)
print("PREDICTION LOADER")
print("=" * 70)

print(
    f"Input file: {prediction_path}"
)

print(
    f"Rows:        {len(df):,}"
)


# =========================================================
# COLUMN VALIDATION
# =========================================================

missing = [
    column
    for column in REQUIRED_COLUMNS
    if column not in df.columns
]

if missing:
    raise ValueError(
        "Missing required prediction columns: "
        + ", ".join(missing)
    )


has_project_id = (
    "project_id" in df.columns
)

has_canonical_key = (
    "canonical_project_key" in df.columns
)

if not has_project_id and not has_canonical_key:
    raise ValueError(
        "Prediction file must contain either "
        "'project_id' or 'canonical_project_key'."
    )


# =========================================================
# NORMALIZE PERIOD
# =========================================================

df["report_period"] = pd.to_datetime(
    df["report_period"],
    errors="coerce",
)

if df["report_period"].isna().any():
    raise ValueError(
        "Invalid report_period detected."
    )

df["report_period"] = (
    df["report_period"]
    .dt.to_period("M")
    .dt.to_timestamp()
)


# =========================================================
# MODEL VERSION CONSISTENCY
# =========================================================

model_versions = (
    df["model_version"]
    .dropna()
    .astype(str)
    .unique()
    .tolist()
)

if len(model_versions) != 1:
    raise ValueError(
        "Prediction file must contain exactly "
        "one model_version. Found: "
        + ", ".join(model_versions)
    )

model_version = model_versions[0]


# =========================================================
# MODEL LOOKUP
# =========================================================

engine = get_engine()

with engine.connect() as connection:

    model = connection.execute(
        text(
            """
            SELECT
                model_id,
                model_version
            FROM ml.model_registry
            WHERE model_version = :model_version
            """
        ),
        {
            "model_version": model_version
        },
    ).mappings().first()

if model is None:
    raise ValueError(
        f"Unknown model_version: {model_version}. "
        "Register the model before loading predictions."
    )

model_id = model["model_id"]

print(
    f"Model: {model_version}"
)

print(
    f"model_id: {model_id}"
)


# =========================================================
# PROJECT LOOKUP
# =========================================================

with engine.connect() as connection:

    projects = pd.read_sql(
        text(
            """
            SELECT
                project_id,
                canonical_project_key
            FROM core.projects
            """
        ),
        connection,
    )


project_by_key = dict(
    zip(
        projects["canonical_project_key"],
        projects["project_id"],
    )
)

project_ids = set(
    projects["project_id"].tolist()
)


# =========================================================
# BUILD RECORDS
# =========================================================

records = []

for index, row in df.iterrows():

    # -----------------------------------------------------
    # Resolve project
    # -----------------------------------------------------

    project_id_from_file = clean_value(
        row.get("project_id")
    )

    canonical_key = clean_value(
        row.get("canonical_project_key")
    )

    if canonical_key is not None:

        canonical_key = str(
            canonical_key
        ).strip()

        resolved_project_id = (
            project_by_key.get(
                canonical_key
            )
        )

        if resolved_project_id is None:
            raise ValueError(
                f"Row {index}: unknown "
                f"canonical_project_key: "
                f"{canonical_key}"
            )

        if project_id_from_file is not None:

            if int(project_id_from_file) != int(
                resolved_project_id
            ):
                raise ValueError(
                    f"Row {index}: project_id and "
                    f"canonical_project_key disagree."
                )

        project_id = resolved_project_id

    else:

        if project_id_from_file is None:
            raise ValueError(
                f"Row {index}: no project identity."
            )

        project_id = int(
            project_id_from_file
        )

        if project_id not in project_ids:
            raise ValueError(
                f"Row {index}: project_id "
                f"{project_id} does not exist "
                f"in core.projects."
            )


    # -----------------------------------------------------
    # Probabilities / score
    # -----------------------------------------------------

    p_risk = clean_probability(
        row["p_risk"],
        "p_risk",
    )

    risk_score = clean_risk_score(
        row["risk_score"]
    )

    p_schedule = clean_probability(
        row.get(
            "p_schedule_deterioration"
        ),
        "p_schedule_deterioration",
    )

    p_cost = clean_probability(
        row.get(
            "p_cost_deterioration"
        ),
        "p_cost_deterioration",
    )


    # -----------------------------------------------------
    # Risk tier
    # -----------------------------------------------------

    risk_tier = clean_value(
        row["risk_tier"]
    )

    if risk_tier is not None:

        risk_tier = str(
            risk_tier
        ).strip().upper()

        if risk_tier not in {
            "GREEN",
            "AMBER",
            "RED",
        }:
            raise ValueError(
                f"Row {index}: invalid risk_tier "
                f"{risk_tier}"
            )


    # -----------------------------------------------------
    # JSON payloads
    # -----------------------------------------------------

    shap_top5 = parse_json_value(
        row.get("shap_top5")
    )

    prediction_payload = parse_json_value(
        row.get("prediction_payload")
    )


    # -----------------------------------------------------
    # Record
    # -----------------------------------------------------

    records.append(
        {
            "project_id": int(project_id),

            "report_period":
                row["report_period"].date(),

            "model_id":
                int(model_id),

            "p_risk":
                p_risk,

            "risk_score":
                risk_score,

            "risk_tier":
                risk_tier,

            "p_schedule_deterioration":
                p_schedule,

            "p_cost_deterioration":
                p_cost,

            "expected_slip_months":
                clean_value(
                    row.get(
                        "expected_slip_months"
                    )
                ),

            "expected_cost_pct":
                clean_value(
                    row.get(
                        "expected_cost_pct"
                    )
                ),

            "slip_interval_low":
                clean_value(
                    row.get(
                        "slip_interval_low"
                    )
                ),

            "slip_interval_high":
                clean_value(
                    row.get(
                        "slip_interval_high"
                    )
                ),

            "cost_interval_low":
                clean_value(
                    row.get(
                        "cost_interval_low"
                    )
                ),

            "cost_interval_high":
                clean_value(
                    row.get(
                        "cost_interval_high"
                    )
                ),

            "risk_rank":
                (
                    int(row["risk_rank"])
                    if pd.notna(
                        row.get("risk_rank")
                    )
                    else None
                ),

            "shap_top5_json":
                json.dumps(shap_top5)
                if shap_top5 is not None
                else None,

            "prediction_payload":
                json.dumps(
                    prediction_payload
                )
                if prediction_payload is not None
                else None,
        }
    )


# =========================================================
# DUPLICATE CHECK BEFORE DATABASE
# =========================================================

keys = [
    (
        r["project_id"],
        r["report_period"],
        r["model_id"],
    )
    for r in records
]

duplicates = (
    len(keys)
    - len(set(keys))
)

if duplicates:
    raise ValueError(
        f"Found {duplicates} duplicate "
        "project-period-model records "
        "inside prediction file."
    )


# =========================================================
# DATABASE LOAD
# =========================================================

insert_query = text(
    """
    INSERT INTO ml.predictions (
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

        slip_interval_low,
        slip_interval_high,

        cost_interval_low,
        cost_interval_high,

        risk_rank,

        shap_top5_json,
        prediction_payload
    )
    VALUES (
        :project_id,
        :report_period,
        :model_id,

        :p_risk,
        :risk_score,
        :risk_tier,

        :p_schedule_deterioration,
        :p_cost_deterioration,

        :expected_slip_months,
        :expected_cost_pct,

        :slip_interval_low,
        :slip_interval_high,

        :cost_interval_low,
        :cost_interval_high,

        :risk_rank,

        CAST(:shap_top5_json AS JSONB),
        CAST(:prediction_payload AS JSONB)
    )

    ON CONFLICT (
        project_id,
        report_period,
        model_id
    )
    DO UPDATE SET

        p_risk =
            EXCLUDED.p_risk,

        risk_score =
            EXCLUDED.risk_score,

        risk_tier =
            EXCLUDED.risk_tier,

        p_schedule_deterioration =
            EXCLUDED.p_schedule_deterioration,

        p_cost_deterioration =
            EXCLUDED.p_cost_deterioration,

        expected_slip_months =
            EXCLUDED.expected_slip_months,

        expected_cost_pct =
            EXCLUDED.expected_cost_pct,

        slip_interval_low =
            EXCLUDED.slip_interval_low,

        slip_interval_high =
            EXCLUDED.slip_interval_high,

        cost_interval_low =
            EXCLUDED.cost_interval_low,

        cost_interval_high =
            EXCLUDED.cost_interval_high,

        risk_rank =
            EXCLUDED.risk_rank,

        shap_top5_json =
            EXCLUDED.shap_top5_json,

        prediction_payload =
            EXCLUDED.prediction_payload;
    """
)


with engine.begin() as connection:

    if records:

        connection.execute(
            insert_query,
            records,
        )


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    loaded_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ml.predictions
            WHERE model_id = :model_id
            """
        ),
        {
            "model_id": model_id
        },
    ).scalar_one()

    file_count = len(records)


# =========================================================
# FINAL
# =========================================================

print("\n" + "=" * 70)
print("PREDICTIONS LOADED")
print("=" * 70)

print(
    f"Rows processed:       {file_count:,}"
)

print(
    f"Model ID:              {model_id}"
)

print(
    f"Model version:         {model_version}"
)

print(
    f"Rows stored for model: {loaded_count:,}"
)

print(
    "\nPrediction loader complete."
)