from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text


# =========================================================
# PROJECT ROOT / IMPORTS
# =========================================================

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres.config import get_engine


# =========================================================
# CONSTANTS
# =========================================================

PIPELINE_VERSION = "phase4_ingest_v2"
RUN_TYPE = "silver_to_staging"


# =========================================================
# HELPERS
# =========================================================

def clean_text(value):
    if value is None:
        return None

    value = str(value).strip()

    return value if value else None


def is_blank_row(row):
    """
    True when the CSV row contains no meaningful data.
    """
    return not any(clean_text(value) for value in row.values())


def normalize_column_name(value):
    """
    Normalize CSV header names so harmless differences in case,
    whitespace, BOM, or separators do not break the loader.
    """
    if value is None:
        return ""

    value = str(value).replace("\ufeff", "").strip().lower()

    for char in (" ", "-", "/", "\\", "."):
        value = value.replace(char, "_")

    while "__" in value:
        value = value.replace("__", "_")

    return value.strip("_")


def normalize_row_keys(row):
    """
    Return a DictReader row with normalized column names.
    """
    normalized = {}

    for key, value in row.items():
        normalized[normalize_column_name(key)] = value

    return normalized


def parse_decimal(value):
    """
    Convert raw numeric text into Decimal.

    Handles:
        123
        123.45
        1,234.56
        12%
        -
        NA
        N/A
    """

    value = clean_text(value)

    if value is None:
        return None

    if value.upper() in {
        "NA",
        "N/A",
        "NULL",
        "NONE",
        "-",
        "--",
        "NOT AVAILABLE",
    }:
        return None

    value = value.replace(",", "")
    value = value.replace("%", "")
    value = value.strip()

    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_date(value):
    """
    Convert common date formats to Python date.
    """

    value = clean_text(value)

    if value is None:
        return None

    formats = [
        "%Y-%m",
        "%Y-%m-%d",
        "%Y/%m",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_args():

    parser = argparse.ArgumentParser(
        description="Load Silver CSV into staging."
    )

    parser.add_argument(
        "source_file",
        help="Path to Silver CSV."
    )

    return parser.parse_args()


# =========================================================
# SOURCE DOCUMENT
# =========================================================

def get_source_document(conn, filename):

    return conn.execute(
        text(
            """
            SELECT
                source_document_id,
                filename,
                report_period,
                report_type
            FROM ingest.source_documents
            WHERE filename = :filename
            ORDER BY source_document_id DESC
            LIMIT 1
            """
        ),
        {
            "filename": filename
        },
    ).mappings().first()


# =========================================================
# EXISTING RUN
# =========================================================

def get_existing_run(
    conn,
    source_document_id,
    silver_version,
):

    return conn.execute(
        text(
            """
            SELECT
                load_run_id,
                status,
                rows_read,
                rows_loaded,
                rows_failed
            FROM ingest.load_runs
            WHERE source_document_id = :source_document_id
              AND run_type = :run_type
              AND pipeline_version = :pipeline_version
              AND silver_version = :silver_version
              AND status = 'success'
            ORDER BY load_run_id DESC
            LIMIT 1
            """
        ),
        {
            "source_document_id": source_document_id,
            "run_type": RUN_TYPE,
            "pipeline_version": PIPELINE_VERSION,
            "silver_version": silver_version,
        },
    ).mappings().first()


# =========================================================
# CREATE LOAD RUN
# =========================================================

def create_load_run(
    conn,
    source_document_id,
    report_period,
    silver_version,
):

    result = conn.execute(
        text(
            """
            INSERT INTO ingest.load_runs (
                run_type,
                source_document_id,
                report_period,
                pipeline_version,
                silver_version,
                status,
                started_at,
                rows_read,
                rows_loaded,
                rows_failed
            )
            VALUES (
                :run_type,
                :source_document_id,
                :report_period,
                :pipeline_version,
                :silver_version,
                'running',
                CURRENT_TIMESTAMP,
                0,
                0,
                0
            )
            RETURNING load_run_id
            """
        ),
        {
            "run_type": RUN_TYPE,
            "source_document_id": source_document_id,
            "report_period": report_period,
            "pipeline_version": PIPELINE_VERSION,
            "silver_version": silver_version,
        },
    )

    return result.scalar_one()


# =========================================================
# INSERT ONE STAGING ROW
# =========================================================

def insert_staging_row(
    conn,
    load_run_id,
    source_document_id,
    source_row_number,
    row,
):

    # -----------------------------------------------------
    # RAW VALUES
    # -----------------------------------------------------

    report_date_raw = clean_text(
        row.get("report_date")
    )

    report_type_raw = clean_text(
        row.get("report_type")
    )

    fiscal_year_raw = clean_text(
        row.get("fiscal_year")
    )

    project_id_raw = clean_text(
        row.get("project_id")
    )

    project_name_raw = clean_text(
        row.get("project_name")
    )

    sector_raw = clean_text(
        row.get("sector")
    )

    state_raw = clean_text(
        row.get("state")
    )

    project_type_raw = clean_text(
        row.get("project_type")
    )

    agency_raw = clean_text(
        row.get("agency")
    )

    cost_original_raw = clean_text(
        row.get("cost_original")
    )

    cost_revised_raw = clean_text(
        row.get("cost_revised")
    )

    cost_anticipated_raw = clean_text(
        row.get("cost_anticipated")
    )

    cost_overrun_raw = clean_text(
        row.get("cost_overrun")
    )

    cost_overrun_pct_raw = clean_text(
        row.get("cost_overrun_pct")
    )

    cumulative_expenditure_raw = clean_text(
        row.get("cumulative_expenditure")
    )

    doc_original_raw = clean_text(
        row.get("doc_original")
    )

    doc_revised_raw = clean_text(
        row.get("doc_revised")
    )

    doc_anticipated_raw = clean_text(
        row.get("doc_anticipated")
    )

    delay_months_raw = clean_text(
        row.get("delay_months")
    )

    physical_progress_raw = clean_text(
        row.get("physical_progress")
    )

    source_file = clean_text(
        row.get("source_file")
    )

    source_page = clean_text(
        row.get("page")
    )

    # -----------------------------------------------------
    # PARSED VALUES
    # -----------------------------------------------------

    parsed_report_period = parse_date(
        report_date_raw
    )

    parsed_cost_original = parse_decimal(
        cost_original_raw
    )

    parsed_cost_revised = parse_decimal(
        cost_revised_raw
    )

    parsed_cost_anticipated = parse_decimal(
        cost_anticipated_raw
    )

    parsed_cost_overrun = parse_decimal(
        cost_overrun_raw
    )

    parsed_cost_overrun_pct = parse_decimal(
        cost_overrun_pct_raw
    )

    parsed_cumulative_expenditure = parse_decimal(
        cumulative_expenditure_raw
    )

    parsed_doc_original = parse_date(
        doc_original_raw
    )

    parsed_doc_revised = parse_date(
        doc_revised_raw
    )

    parsed_doc_anticipated = parse_date(
        doc_anticipated_raw
    )

    parsed_delay_months = parse_decimal(
        delay_months_raw
    )

    parsed_physical_progress = parse_decimal(
        physical_progress_raw
    )

     # -----------------------------------------------------
    # INSERT
    # -----------------------------------------------------

    conn.execute(
        text(
            """
            INSERT INTO ingest.staging_project_observations (

                load_run_id,
                source_document_id,
                source_row_number,

                source_project_key,
                project_name_raw,

                report_date_raw,
                report_type_raw,
                fiscal_year_raw,

                sector_raw,
                state_raw,
                project_type_raw,
                agency_raw,

                cost_original_raw,
                cost_revised_raw,
                cost_anticipated_raw,
                cost_overrun_raw,
                cost_overrun_pct_raw,

                cumulative_expenditure_raw,

                doc_original_raw,
                doc_revised_raw,
                doc_anticipated_raw,

                delay_months_raw,
                physical_progress_raw,

                source_file,
                source_page,

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
                parsed_physical_progress_pct,

                validation_status,
                validation_errors
            )

            VALUES (

                :load_run_id,
                :source_document_id,
                :source_row_number,

                :source_project_key,
                :project_name_raw,

                :report_date_raw,
                :report_type_raw,
                :fiscal_year_raw,

                :sector_raw,
                :state_raw,
                :project_type_raw,
                :agency_raw,

                :cost_original_raw,
                :cost_revised_raw,
                :cost_anticipated_raw,
                :cost_overrun_raw,
                :cost_overrun_pct_raw,

                :cumulative_expenditure_raw,

                :doc_original_raw,
                :doc_revised_raw,
                :doc_anticipated_raw,

                :delay_months_raw,
                :physical_progress_raw,

                :source_file,
                :source_page,

                :parsed_report_period,

                :parsed_cost_original,
                :parsed_cost_revised,
                :parsed_cost_anticipated,
                :parsed_cost_overrun,
                :parsed_cost_overrun_pct,

                :parsed_cumulative_expenditure,

                :parsed_doc_original,
                :parsed_doc_revised,
                :parsed_doc_anticipated,

                :parsed_delay_months,
                :parsed_physical_progress,

                'pending',
                NULL
            )

            ON CONFLICT (
                load_run_id,
                source_row_number
            )

            DO NOTHING
            """
        ),
        {
            "load_run_id": load_run_id,
            "source_document_id": source_document_id,
            "source_row_number": source_row_number,

            "source_project_key": project_id_raw,
            "project_name_raw": project_name_raw,

            "report_date_raw": report_date_raw,
            "report_type_raw": report_type_raw,
            "fiscal_year_raw": fiscal_year_raw,

            "sector_raw": sector_raw,
            "state_raw": state_raw,
            "project_type_raw": project_type_raw,
            "agency_raw": agency_raw,

            "cost_original_raw": cost_original_raw,
            "cost_revised_raw": cost_revised_raw,
            "cost_anticipated_raw": cost_anticipated_raw,
            "cost_overrun_raw": cost_overrun_raw,
            "cost_overrun_pct_raw": cost_overrun_pct_raw,

            "cumulative_expenditure_raw":
                cumulative_expenditure_raw,

            "doc_original_raw": doc_original_raw,
            "doc_revised_raw": doc_revised_raw,
            "doc_anticipated_raw": doc_anticipated_raw,

            "delay_months_raw": delay_months_raw,
            "physical_progress_raw":
                physical_progress_raw,

            "source_file": source_file,
            "source_page": source_page,

            "parsed_report_period":
                parsed_report_period,

            # Actual DB column: parsed_cost_original_cr
            "parsed_cost_original":
                parsed_cost_original,

            # Actual DB column: parsed_cost_revised_cr
            "parsed_cost_revised":
                parsed_cost_revised,

            # Actual DB column: parsed_cost_anticipated_cr
            "parsed_cost_anticipated":
                parsed_cost_anticipated,

            # Actual DB column: parsed_cost_overrun_cr
            "parsed_cost_overrun":
                parsed_cost_overrun,

            # Actual DB column: parsed_cost_overrun_pct
            "parsed_cost_overrun_pct":
                parsed_cost_overrun_pct,

            # Actual DB column: parsed_cumulative_expenditure_cr
            "parsed_cumulative_expenditure":
                parsed_cumulative_expenditure,

            "parsed_doc_original":
                parsed_doc_original,

            "parsed_doc_revised":
                parsed_doc_revised,

            "parsed_doc_anticipated":
                parsed_doc_anticipated,

            "parsed_delay_months":
                parsed_delay_months,

            # Actual DB column: parsed_physical_progress_pct
            "parsed_physical_progress":
                parsed_physical_progress,
        },
    )   

# =========================================================
# MAIN
# =========================================================

def main():

    args = parse_args()

    source_path = Path(
        args.source_file
    ).resolve()

    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file does not exist:\n{source_path}"
        )

    if source_path.suffix.lower() != ".csv":
        raise ValueError(
            "Source must be a CSV file."
        )

    filename = source_path.name
    silver_version = source_path.stem

    print("=" * 70)
    print("PAIMANA SILVER → STAGING LOADER")
    print("=" * 70)

    print(f"Source file      : {source_path}")
    print(f"Silver version   : {silver_version}")
    print(f"Pipeline version : {PIPELINE_VERSION}")
    print(f"Run type         : {RUN_TYPE}")
    print()

    engine = get_engine()

    # One outer transaction for the whole load.
    # Each individual row gets its own SAVEPOINT.
    with engine.begin() as conn:

        # -------------------------------------------------
        # SOURCE DOCUMENT
        # -------------------------------------------------

        source = get_source_document(
            conn,
            filename,
        )

        if not source:
            raise RuntimeError(
                f"""
Source document is not registered:

{filename}

Run register_source_run.py first.
"""
            )

        source_document_id = source[
            "source_document_id"
        ]

        report_period = source[
            "report_period"
        ]

        print(
            f"source_document_id : "
            f"{source_document_id}"
        )

        print(
            f"source report period: "
            f"{report_period}"
        )

        # -------------------------------------------------
        # IDEMPOTENCY
        # -------------------------------------------------

        existing_run = get_existing_run(
            conn,
            source_document_id,
            silver_version,
        )

        if existing_run:

            print()
            print(
                "Existing successful staging run found."
            )

            print(
                f"load_run_id : "
                f"{existing_run['load_run_id']}"
            )

            print(
                f"rows_loaded : "
                f"{existing_run['rows_loaded']}"
            )

            print()
            print(
                "IDEMPOTENCY CHECK: PASS"
            )

            return

        # -------------------------------------------------
        # CREATE RUN
        # -------------------------------------------------

        load_run_id = create_load_run(
            conn,
            source_document_id,
            report_period,
            silver_version,
        )

        print(
            f"Created load_run_id: "
            f"{load_run_id}"
        )

        # -------------------------------------------------
        # PROCESS CSV
        # -------------------------------------------------

        rows_read = 0
        rows_loaded = 0
        rows_failed = 0
        blank_rows = 0

        first_error = None

        print()
        print("Loading CSV into staging...")

        with source_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:

            # -------------------------------------------------
            # Find the first non-empty line and use it as the
            # actual CSV header. Some Silver files contain a
            # blank line before the header.
            # -------------------------------------------------
            leading_blank_lines = 0

            while True:
                header_line = f.readline()

                if header_line == "":
                    raise RuntimeError(
                        "Silver CSV does not contain a header."
                    )

                if header_line.strip():
                    break

                leading_blank_lines += 1

            # Detect the delimiter from the real header plus
            # a sample of the following data.
            sample = header_line + f.read(8192)

            try:
                dialect = csv.Sniffer().sniff(
                    sample,
                    delimiters=",;\\t|",
                )
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","

            # Parse the header ourselves so leading blank lines
            # cannot be interpreted as CSV column names.
            header_values = next(
                csv.reader(
                    [header_line],
                    delimiter=delimiter,
                )
            )

            normalized_fieldnames = [
                normalize_column_name(name)
                for name in header_values
            ]

            expected_columns = {
                "project_id",
                "project_name",
                "report_date",
            }

            missing_columns = sorted(
                expected_columns - set(normalized_fieldnames)
            )

            if missing_columns:
                raise RuntimeError(
                    "Silver CSV header does not contain the required "
                    f"columns: {missing_columns}. "
                    f"Detected columns: {normalized_fieldnames}"
                )

            print(f"CSV delimiter      : {repr(delimiter)}")
            print(f"Leading blank lines: {leading_blank_lines}")
            print(
                "Detected columns   : "
                f"{len(normalized_fieldnames)}"
            )

            # Rewind to the first data row. The file pointer is
            # currently after the 8192-byte sample, so reopen the
            # file and position it immediately after the header.
            f.seek(0)

            for _ in range(leading_blank_lines):
                f.readline()

            f.readline()  # consume the actual header

            reader = csv.DictReader(
                f,
                fieldnames=normalized_fieldnames,
                delimiter=delimiter,
            )

            for source_row_number, raw_row in enumerate(
                reader,
                start=leading_blank_lines + 2,
            ):

                # Normalize headers before any row.get(...) calls.
                row = normalize_row_keys(raw_row)

                # -----------------------------------------
                # Ignore completely blank trailing rows
                # -----------------------------------------

                if is_blank_row(row):
                    blank_rows += 1
                    continue

                rows_read += 1

                # Fail loudly if the mandatory identity/time fields
                # disappear due to another CSV/header regression.
                if (
                    not clean_text(row.get("project_id"))
                    or not clean_text(row.get("project_name"))
                    or not clean_text(row.get("report_date"))
                ):
                    raise RuntimeError(
                        "Mandatory Silver fields are missing in "
                        f"CSV row {source_row_number}: "
                        "project_id/project_name/report_date"
                    )

                # -----------------------------------------
                # Per-row SAVEPOINT
                # -----------------------------------------

                savepoint = conn.begin_nested()

                try:

                    insert_staging_row(
                        conn,
                        load_run_id,
                        source_document_id,
                        source_row_number,
                        row,
                    )

                    savepoint.commit()

                    rows_loaded += 1

                except Exception as exc:

                    savepoint.rollback()

                    rows_failed += 1

                    error_text = str(exc)

                    if first_error is None:
                        first_error = (
                            source_row_number,
                            error_text,
                        )

                    # Don't print thousands of lines.
                    if rows_failed <= 10:

                        print()
                        print(
                            f"FAILED row "
                            f"{source_row_number}"
                        )

                        print(
                            error_text[:1000]
                        )

        # -------------------------------------------------
        # FINAL STATUS
        # -------------------------------------------------

        if rows_failed == 0:
            final_status = "success"
        elif rows_loaded > 0:
            final_status = "partial"
        else:
            final_status = "failed"

        # -------------------------------------------------
        # UPDATE LOAD RUN
        # -------------------------------------------------

        conn.execute(
            text(
                """
                UPDATE ingest.load_runs
                SET
                    finished_at = CURRENT_TIMESTAMP,
                    status = :status,
                    rows_read = :rows_read,
                    rows_loaded = :rows_loaded,
                    rows_failed = :rows_failed
                WHERE load_run_id = :load_run_id
                """
            ),
            {
                "status": final_status,
                "rows_read": rows_read,
                "rows_loaded": rows_loaded,
                "rows_failed": rows_failed,
                "load_run_id": load_run_id,
            },
        )

        # -------------------------------------------------
        # VERIFY STAGING
        # -------------------------------------------------

        staging_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM ingest.staging_project_observations
                WHERE load_run_id = :load_run_id
                """
            ),
            {
                "load_run_id": load_run_id,
            },
        ).scalar_one()

        # -------------------------------------------------
        # RESULT
        # -------------------------------------------------

        print()
        print("=" * 70)
        print("LOAD RESULT")
        print("=" * 70)

        print(f"CSV rows read       : {rows_read}")
        print(f"Blank rows skipped  : {blank_rows}")
        print(f"Rows loaded         : {rows_loaded}")
        print(f"Rows failed         : {rows_failed}")
        print(f"Staging rows        : {staging_count}")
        print(f"Load run status     : {final_status}")
        print(f"load_run_id         : {load_run_id}")

        if first_error:

            print()
            print("FIRST DATABASE ERROR")
            print("-" * 70)
            print(
                f"Row: {first_error[0]}"
            )
            print(
                first_error[1][:2000]
            )

    print()
    print("=" * 70)
    print("SILVER → STAGING COMPLETE")
    print("=" * 70)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print()
        print("FATAL ERROR")
        print("-" * 70)
        print(exc)

        sys.exit(1)