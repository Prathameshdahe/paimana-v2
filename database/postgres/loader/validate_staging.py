from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date

from sqlalchemy import text


# ---------------------------------------------------------
# Project root / imports
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres.config import get_engine


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def is_missing(value) -> bool:
    return value is None or str(value).strip() == ""


def to_float(value):
    if is_missing(value):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_row(row):
    """
    Validate one staging observation.

    Important:
    - This validates the observation itself.
    - It does NOT require successful project identity resolution.
    - Unresolved project identity is handled later by the
      identity-resolution layer.
    """

    errors = []

    # -----------------------------------------------------
    # Required lineage fields
    # -----------------------------------------------------

    if row["load_run_id"] is None:
        errors.append({
            "field": "load_run_id",
            "code": "missing_load_run_id",
            "message": "Load run ID is missing."
        })

    if row["source_document_id"] is None:
        errors.append({
            "field": "source_document_id",
            "code": "missing_source_document_id",
            "message": "Source document ID is missing."
        })

    if row["source_row_number"] is None:
        errors.append({
            "field": "source_row_number",
            "code": "missing_source_row_number",
            "message": "Source row number is missing."
        })

    # -----------------------------------------------------
    # Project information
    # -----------------------------------------------------

    if is_missing(row["source_project_key"]):
        errors.append({
            "field": "source_project_key",
            "code": "missing_project_key",
            "message": "Source project key is missing."
        })

    if is_missing(row["project_name_raw"]):
        errors.append({
            "field": "project_name_raw",
            "code": "missing_project_name",
            "message": "Project name is missing."
        })

    # -----------------------------------------------------
    # Report period
    # -----------------------------------------------------

    if row["parsed_report_period"] is None:
        errors.append({
            "field": "parsed_report_period",
            "code": "missing_report_period",
            "message": "Parsed report period is missing."
        })
    else:
        if not isinstance(row["parsed_report_period"], date):
            errors.append({
                "field": "parsed_report_period",
                "code": "invalid_report_period",
                "message": "Report period is not a valid date."
            })

    # -----------------------------------------------------
    # Numeric fields
    # -----------------------------------------------------

    numeric_fields = [
        "parsed_cost_original_cr",
        "parsed_cost_revised_cr",
        "parsed_cost_anticipated_cr",
        "parsed_cumulative_expenditure_cr",
        "parsed_delay_months",
        "parsed_physical_progress_pct",
    ]

    numeric_values = {}

    for field in numeric_fields:
        value = row[field]

        if is_missing(value):
            numeric_values[field] = None
            continue

        parsed = to_float(value)

        if parsed is None:
            errors.append({
                "field": field,
                "code": "invalid_numeric_value",
                "message": f"{field} is not numeric."
            })
        else:
            numeric_values[field] = parsed

    # -----------------------------------------------------
    # Non-negative financial values
    # -----------------------------------------------------

    financial_fields = [
        "parsed_cost_original_cr",
        "parsed_cost_revised_cr",
        "parsed_cost_anticipated_cr",
        "parsed_cumulative_expenditure_cr",
    ]

    for field in financial_fields:
        value = numeric_values.get(field)

        if value is not None and value < 0:
            errors.append({
                "field": field,
                "code": "negative_value",
                "message": f"{field} cannot be negative."
            })

    # -----------------------------------------------------
    # Physical progress
    # -----------------------------------------------------

    progress = numeric_values.get("parsed_physical_progress_pct")

    if progress is not None:

        if progress < 0 or progress > 100:
            errors.append({
                "field": "parsed_physical_progress_pct",
                "code": "physical_progress_out_of_range",
                "message": (
                    "Physical progress must be between 0 and 100."
                ),
                "value": progress
            })

    # -----------------------------------------------------
    # Cost consistency
    # -----------------------------------------------------

    original = numeric_values.get("parsed_cost_original_cr")
    revised = numeric_values.get("parsed_cost_revised_cr")
    anticipated = numeric_values.get("parsed_cost_anticipated_cr")

    if (
        original is not None
        and revised is not None
        and original > 0
        and revised < 0
    ):
        errors.append({
            "field": "parsed_cost_revised_cr",
            "code": "invalid_cost_revision",
            "message": "Revised cost cannot be negative."
        })

    if (
        anticipated is not None
        and anticipated < 0
    ):
        errors.append({
            "field": "parsed_cost_anticipated_cr",
            "code": "invalid_anticipated_cost",
            "message": "Anticipated cost cannot be negative."
        })

    return errors


# ---------------------------------------------------------
# Main validation
# ---------------------------------------------------------

def main(load_run_id: int):

    engine = get_engine()

    print("=" * 70)
    print("PAIMANA STAGING DATA QUALITY GATE")
    print("=" * 70)

    with engine.begin() as conn:

        # -------------------------------------------------
        # Check staging count
        # -------------------------------------------------

        total_rows = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM ingest.staging_project_observations
                WHERE load_run_id = :load_run_id
                """
            ),
            {"load_run_id": load_run_id},
        ).scalar_one()

        print(f"Staging rows       : {total_rows}")

        if total_rows == 0:
            print()
            print("WARNING: staging table is currently empty.")
            print()
            print(
                "The validation engine is ready, but there are no "
                "staging observations to validate."
            )
            print()
            print(
                "Next step will be loading the Silver observations "
                "into staging before running this gate."
            )
            return

        # -------------------------------------------------
        # Reset only pending rows
        # -------------------------------------------------

        conn.execute(
            text(
                """
                UPDATE ingest.staging_project_observations
                SET
                    validation_status = 'pending',
                    validation_errors = NULL
                WHERE load_run_id = :load_run_id
                  AND (
                      validation_status IS NULL
                      OR validation_status = 'pending'
                  )
                """
            ),
            {"load_run_id": load_run_id},
        )

        # -------------------------------------------------
        # Read staging observations
        # -------------------------------------------------

        rows = conn.execute(
            text(
                """
                SELECT
                    staging_id,
                    load_run_id,
                    source_document_id,
                    source_row_number,
                    source_project_key,
                    project_name_raw,

                    parsed_report_period,

                    parsed_cost_original_cr,
                    parsed_cost_revised_cr,
                    parsed_cost_anticipated_cr,
                    parsed_cost_overrun_cr,
                    parsed_cost_overrun_pct,

                    parsed_cumulative_expenditure_cr,

                    parsed_doc_original,
                    parsed_doc_revised,
                    parsed_doc_anticipated,

                    parsed_delay_months,
                    parsed_physical_progress_pct

                FROM ingest.staging_project_observations
                WHERE load_run_id = :load_run_id
                ORDER BY staging_id
                """
            ),
            {"load_run_id": load_run_id},
        ).mappings().all()

        print(f"Rows loaded        : {len(rows)}")
        print()

        valid_count = 0
        invalid_count = 0

        # -------------------------------------------------
        # Validate every observation
        # -------------------------------------------------

        for row in rows:

            errors = validate_row(row)

            if errors:
                status = "invalid"
                invalid_count += 1
            else:
                status = "valid"
                valid_count += 1

            conn.execute(
                text(
                    """
                    UPDATE ingest.staging_project_observations
                    SET
                        validation_status = :status,
                        validation_errors =
                            CAST(:errors AS jsonb)
                    WHERE staging_id = :staging_id
                    """
                ),
                {
                    "status": status,
                    "errors": json.dumps(errors),
                    "staging_id": row["staging_id"],
                },
            )

        # -------------------------------------------------
        # Summary
        # -------------------------------------------------

        print("VALIDATION RESULT")
        print("-" * 70)
        print(f"Valid rows         : {valid_count}")
        print(f"Invalid rows       : {invalid_count}")
        print(f"Total rows         : {len(rows)}")

        # -------------------------------------------------
        # Error distribution
        # -------------------------------------------------

        error_rows = conn.execute(
            text(
                """
                SELECT
                    validation_errors
                FROM ingest.staging_project_observations
                WHERE load_run_id = :load_run_id
                  AND validation_status = 'invalid'
                """
            ),
            {"load_run_id": load_run_id},
        ).mappings().all()

        error_counts = {}

        for row in error_rows:

            errors = row["validation_errors"]

            if not errors:
                continue

            for error in errors:

                code = error.get(
                    "code",
                    "unknown_error"
                )

                error_counts[code] = (
                    error_counts.get(code, 0) + 1
                )

        print()
        print("ERROR DISTRIBUTION")
        print("-" * 70)

        if not error_counts:
            print("No validation errors.")

        else:
            for code, count in sorted(
                error_counts.items(),
                key=lambda x: (-x[1], x[0])
            ):
                print(f"{code:<40} {count}")

        # -------------------------------------------------
        # Final database summary
        # -------------------------------------------------

        summary = conn.execute(
            text(
                """
                SELECT
                    validation_status,
                    COUNT(*) AS count
                FROM ingest.staging_project_observations
                WHERE load_run_id = :load_run_id
                GROUP BY validation_status
                ORDER BY validation_status
                """
            ),
            {"load_run_id": load_run_id},
        ).mappings().all()

        print()
        print("DATABASE VALIDATION STATUS")
        print("-" * 70)

        for row in summary:
            print(
                f"{row['validation_status']:<15}"
                f"{row['count']}"
            )

    print()
    print("=" * 70)
    print("STAGING VALIDATION COMPLETE")
    print("=" * 70)


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            print("Usage:")
            print(
                "  python database/postgres/loader/validate_staging.py "
                "<load_run_id>"
            )
            sys.exit(1)

        load_run_id = int(sys.argv[1])

        print(f"Validating load_run_id : {load_run_id}")
        print()

        main(load_run_id)

    except Exception as exc:
        print()
        print("ERROR")
        print("-" * 70)
        print(exc)
        sys.exit(1)