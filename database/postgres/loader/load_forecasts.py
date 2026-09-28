import argparse
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
# LOAD INPUT
# =========================================================

def load_forecast_file(path):
    suffix = path.suffix.lower()

    if suffix == ".json":
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(payload, dict):
            payload = payload.get(
                "forecasts",
                payload,
            )

        if not isinstance(payload, list):
            raise ValueError(
                "JSON forecast input must be a list "
                "or an object containing a 'forecasts' list."
            )

        return payload

    if suffix == ".jsonl":
        records = []

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:

            for line_number, line in enumerate(
                file,
                start=1,
            ):

                line = line.strip()

                if not line:
                    continue

                try:
                    records.append(
                        json.loads(line)
                    )
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON on line {line_number}."
                    ) from exc

        return records

    raise ValueError(
        "Supported forecast files: .json or .jsonl"
    )


# =========================================================
# CLI
# =========================================================

parser = argparse.ArgumentParser(
    description="Load ML forecasts into ml.forecasts."
)

parser.add_argument(
    "forecast_file",
)

args = parser.parse_args()

forecast_path = Path(
    args.forecast_file
).resolve()

if not forecast_path.exists():
    raise FileNotFoundError(
        f"Forecast file not found: {forecast_path}"
    )


# =========================================================
# READ
# =========================================================

records = load_forecast_file(
    forecast_path
)

print("=" * 70)
print("FORECAST LOADER")
print("=" * 70)

print(
    f"Input file: {forecast_path}"
)

print(
    f"Rows: {len(records):,}"
)


# =========================================================
# VALIDATION
# =========================================================

required_fields = [
    "project_id",
    "report_period",
    "model_version",
    "forecast_payload",
]

for index, record in enumerate(records):

    if not isinstance(record, dict):
        raise ValueError(
            f"Row {index}: forecast record must be an object."
        )

    missing = [
        field
        for field in required_fields
        if field not in record
    ]

    if missing:
        raise ValueError(
            f"Row {index}: missing fields: "
            + ", ".join(missing)
        )

    if not isinstance(
        record["forecast_payload"],
        (dict, list),
    ):
        raise ValueError(
            f"Row {index}: forecast_payload "
            "must be a JSON object or list."
        )


# =========================================================
# MODEL VERSION CHECK
# =========================================================

model_versions = {
    str(record["model_version"]).strip()
    for record in records
}

if len(model_versions) != 1:

    raise ValueError(
        "Forecast file must contain exactly "
        "one model_version."
    )

model_version = next(
    iter(model_versions)
)


# =========================================================
# DATABASE
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
        "Register the model first."
    )


model_id = model["model_id"]


# =========================================================
# PROJECT VALIDATION
# =========================================================

with engine.connect() as connection:

    projects = connection.execute(
        text(
            """
            SELECT
                project_id
            FROM core.projects
            """
        )
    ).scalars().all()


valid_project_ids = set(
    projects
)


# =========================================================
# PREPARE DATABASE RECORDS
# =========================================================

db_records = []

for index, record in enumerate(records):

    try:

        project_id = int(
            record["project_id"]
        )

    except (TypeError, ValueError) as exc:

        raise ValueError(
            f"Row {index}: invalid project_id."
        ) from exc


    if project_id not in valid_project_ids:

        raise ValueError(
            f"Row {index}: project_id "
            f"{project_id} does not exist in core.projects."
        )


    report_period = record[
        "report_period"
    ]


    # Validate ISO date
    try:

        from datetime import date

        report_period = date.fromisoformat(
            str(report_period)
        )

    except ValueError as exc:

        raise ValueError(
            f"Row {index}: report_period must use "
            "YYYY-MM-DD format."
        ) from exc


    db_records.append(
        {
            "project_id":
                project_id,

            "report_period":
                report_period,

            "model_id":
                model_id,

            "forecast_payload":
                json.dumps(
                    record["forecast_payload"]
                ),
        }
    )


# =========================================================
# DUPLICATE CHECK
# =========================================================

keys = [
    (
        record["project_id"],
        record["report_period"],
        record["model_id"],
    )
    for record in db_records
]

duplicate_count = (
    len(keys)
    - len(set(keys))
)

if duplicate_count:

    raise ValueError(
        f"Found {duplicate_count} duplicate "
        "project-period-model records "
        "inside the forecast file."
    )


# =========================================================
# UPSERT
# =========================================================

query = text(
    """
    INSERT INTO ml.forecasts (
        project_id,
        report_period,
        model_id,
        forecast_payload
    )
    VALUES (
        :project_id,
        :report_period,
        :model_id,
        CAST(:forecast_payload AS JSONB)
    )

    ON CONFLICT (
        project_id,
        report_period,
        model_id
    )

    DO UPDATE SET

        forecast_payload =
            EXCLUDED.forecast_payload;
    """
)


with engine.begin() as connection:

    if db_records:

        connection.execute(
            query,
            db_records,
        )


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    loaded_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ml.forecasts
            WHERE model_id = :model_id
            """
        ),
        {
            "model_id": model_id
        },
    ).scalar_one()


# =========================================================
# RESULT
# =========================================================

print("\n" + "=" * 70)
print("FORECASTS LOADED")
print("=" * 70)

print(
    f"Model version: {model_version}"
)

print(
    f"Model ID:      {model_id}"
)

print(
    f"Rows processed: {len(db_records):,}"
)

print(
    f"Rows stored:    {loaded_count:,}"
)

print(
    "\nForecast loader complete."
)