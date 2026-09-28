import argparse
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

DATABASE_URL = URL.create(
    "postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME"),
)

engine = create_engine(DATABASE_URL)


# =========================================================
# VALIDATION
# =========================================================

REQUIRED_FIELDS = [
    "model_name",
    "model_version",
    "model_type",
    "target_name",
    "feature_version",
    "gold_version",
    "training_start_period",
    "training_end_period",
    "metrics",
    "artifact_path",
]


def validate_metadata(metadata):
    missing = [
        field
        for field in REQUIRED_FIELDS
        if field not in metadata
        or metadata[field] in (None, "")
    ]

    if missing:
        raise ValueError(
            "Missing required fields: "
            + ", ".join(missing)
        )

    metrics = metadata["metrics"]

    if not isinstance(metrics, dict):
        raise ValueError(
            "'metrics' must be a JSON object."
        )

    periods = [
        "training_start_period",
        "training_end_period",
        "validation_start_period",
        "validation_end_period",
        "test_start_period",
        "test_end_period",
    ]

    for field in periods:

        value = metadata.get(field)

        if value:
            try:
                from datetime import date

                date.fromisoformat(value)

            except ValueError as exc:
                raise ValueError(
                    f"{field} must use YYYY-MM-DD format."
                ) from exc


# =========================================================
# ARTIFACT HASH
# =========================================================

def calculate_sha256(path):

    sha256 = hashlib.sha256()

    with open(path, "rb") as file:

        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest()


# =========================================================
# CLI
# =========================================================

parser = argparse.ArgumentParser(
    description="Load ML model metadata into PostgreSQL."
)

parser.add_argument(
    "metadata_file",
)

parser.add_argument(
    "--dry-run",
    action="store_true",
)

args = parser.parse_args()


# =========================================================
# READ METADATA
# =========================================================

metadata_file = Path(
    args.metadata_file
).resolve()

if not metadata_file.exists():
    raise FileNotFoundError(
        f"Metadata file not found: {metadata_file}"
    )

metadata = json.loads(
    metadata_file.read_text(
        encoding="utf-8"
    )
)

validate_metadata(metadata)


# =========================================================
# ARTIFACT
# =========================================================

artifact_path = metadata["artifact_path"]

artifact_sha256 = metadata.get(
    "artifact_sha256"
)

artifact_file = Path(
    artifact_path
)

if artifact_sha256 is None and artifact_file.exists():

    artifact_sha256 = calculate_sha256(
        artifact_file
    )


# =========================================================
# PREPARE RECORD
# =========================================================

record = {
    "model_name":
        metadata["model_name"],

    "model_version":
        metadata["model_version"],

    "model_type":
        metadata["model_type"],

    "target_name":
        metadata["target_name"],

    "feature_version":
        metadata["feature_version"],

    "gold_version":
        metadata["gold_version"],

    "training_start_period":
        metadata["training_start_period"],

    "training_end_period":
        metadata["training_end_period"],

    "validation_start_period":
        metadata.get(
            "validation_start_period"
        ),

    "validation_end_period":
        metadata.get(
            "validation_end_period"
        ),

    "test_start_period":
        metadata.get(
            "test_start_period"
        ),

    "test_end_period":
        metadata.get(
            "test_end_period"
        ),

    "metrics_json":
        json.dumps(
            metadata["metrics"]
        ),

    "hyperparameters_json":
        json.dumps(
            metadata.get(
                "hyperparameters",
                {},
            )
        ),

    "artifact_path":
        artifact_path,

    "artifact_sha256":
        artifact_sha256,

    "status":
        metadata.get(
            "status",
            "registered",
        ),

    "is_champion":
        metadata.get(
            "is_champion",
            False,
        ),
}


# =========================================================
# DISPLAY
# =========================================================

print("=" * 70)
print("MODEL REGISTRY LOADER")
print("=" * 70)

print(
    f"Model:     {record['model_name']}"
)

print(
    f"Version:   {record['model_version']}"
)

print(
    f"Type:      {record['model_type']}"
)

print(
    f"Target:    {record['target_name']}"
)

print(
    f"Features:  {record['feature_version']}"
)

print(
    f"Gold:      {record['gold_version']}"
)

print(
    f"Status:    {record['status']}"
)

print(
    f"Champion:  {record['is_champion']}"
)


# =========================================================
# DRY RUN
# =========================================================

if args.dry_run:

    print("\nDRY RUN: validation passed.")
    print("No database changes made.")

    raise SystemExit(0)


# =========================================================
# UPSERT
# =========================================================

query = text(
    """
    INSERT INTO ml.model_registry (
        model_name,
        model_version,
        model_type,
        target_name,
        feature_version,
        gold_version,

        training_start_period,
        training_end_period,

        validation_start_period,
        validation_end_period,

        test_start_period,
        test_end_period,

        metrics_json,
        hyperparameters_json,

        artifact_path,
        artifact_sha256,

        status,
        is_champion
    )
    VALUES (
        :model_name,
        :model_version,
        :model_type,
        :target_name,
        :feature_version,
        :gold_version,

        :training_start_period,
        :training_end_period,

        :validation_start_period,
        :validation_end_period,

        :test_start_period,
        :test_end_period,

        CAST(:metrics_json AS JSONB),
        CAST(:hyperparameters_json AS JSONB),

        :artifact_path,
        :artifact_sha256,

        :status,
        :is_champion
    )

    ON CONFLICT (model_version)
    DO UPDATE SET

        model_name = EXCLUDED.model_name,
        model_type = EXCLUDED.model_type,
        target_name = EXCLUDED.target_name,
        feature_version = EXCLUDED.feature_version,
        gold_version = EXCLUDED.gold_version,

        training_start_period =
            EXCLUDED.training_start_period,

        training_end_period =
            EXCLUDED.training_end_period,

        validation_start_period =
            EXCLUDED.validation_start_period,

        validation_end_period =
            EXCLUDED.validation_end_period,

        test_start_period =
            EXCLUDED.test_start_period,

        test_end_period =
            EXCLUDED.test_end_period,

        metrics_json =
            EXCLUDED.metrics_json,

        hyperparameters_json =
            EXCLUDED.hyperparameters_json,

        artifact_path =
            EXCLUDED.artifact_path,

        artifact_sha256 =
            EXCLUDED.artifact_sha256,

        status =
            EXCLUDED.status,

        is_champion =
            EXCLUDED.is_champion;
    """
)


with engine.begin() as connection:

    connection.execute(
        query,
        record,
    )


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    result = connection.execute(
        text(
            """
            SELECT
                model_id,
                model_name,
                model_version,
                target_name,
                feature_version,
                gold_version,
                status,
                is_champion
            FROM ml.model_registry
            WHERE model_version = :model_version
            """
        ),
        {
            "model_version":
                record["model_version"]
        },
    ).mappings().one()


print("\n" + "=" * 70)
print("MODEL REGISTERED")
print("=" * 70)

print(
    f"model_id:        {result['model_id']}"
)

print(
    f"model_version:   {result['model_version']}"
)

print(
    f"target_name:     {result['target_name']}"
)

print(
    f"feature_version: {result['feature_version']}"
)

print(
    f"gold_version:    {result['gold_version']}"
)

print(
    f"status:          {result['status']}"
)

print(
    f"is_champion:     {result['is_champion']}"
)