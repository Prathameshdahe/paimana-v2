from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

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

def sha256_file(path: Path) -> str:
    """Calculate SHA-256 without loading the whole file into memory."""
    digest = hashlib.sha256()

    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    """Count data rows, excluding the header."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header

        return sum(1 for _ in reader)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register a Silver source artifact and create an ingest load run."
    )

    parser.add_argument(
        "source_file",
        help="Path to the Silver CSV file."
    )

    parser.add_argument(
        "--report-period",
        required=True,
        help="Report period start date, e.g. 2025-04-01."
    )

    parser.add_argument(
        "--report-type",
        default="project_monitoring",
        help="Report/source type."
    )

    parser.add_argument(
        "--pipeline-version",
        default="phase4_ingest_v1",
        help="Pipeline version."
    )

    parser.add_argument(
        "--silver-version",
        default=None,
        help="Silver version. Defaults to source filename stem."
    )

    parser.add_argument(
        "--run-type",
        default="source_registration",
        help="Type of ingest run."
    )

    return parser.parse_args()


# ---------------------------------------------------------
# Main registration logic
# ---------------------------------------------------------

def register_source_and_run(args: argparse.Namespace) -> None:
    source_path = Path(args.source_file).resolve()

    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file does not exist:\n{source_path}"
        )

    if not source_path.is_file():
        raise ValueError(
            f"Source path is not a file:\n{source_path}"
        )

    if source_path.suffix.lower() != ".csv":
        raise ValueError(
            f"Expected a CSV file, got: {source_path.suffix}"
        )

    silver_version = args.silver_version or source_path.stem

    print("=" * 70)
    print("PAIMANA SOURCE + LOAD RUN REGISTRATION")
    print("=" * 70)
    print(f"Source file       : {source_path}")
    print(f"Report period     : {args.report_period}")
    print(f"Report type       : {args.report_type}")
    print(f"Pipeline version  : {args.pipeline_version}")
    print(f"Silver version    : {silver_version}")
    print(f"Run type          : {args.run_type}")
    print()

    print("Calculating SHA-256...")
    file_hash = sha256_file(source_path)

    print(f"SHA-256           : {file_hash}")

    print("Counting CSV rows...")
    row_count = count_csv_rows(source_path)

    print(f"CSV data rows     : {row_count}")
    print()

    engine = get_engine()

    with engine.begin() as conn:

        # -------------------------------------------------
        # 1. Check whether this exact source already exists
        # -------------------------------------------------

        existing_source = conn.execute(
            text(
                """
                SELECT
                    source_document_id,
                    filename,
                    file_type,
                    sha256,
                    report_period,
                    report_type,
                    source_path
                FROM ingest.source_documents
                WHERE sha256 = :sha256
                """
            ),
            {"sha256": file_hash},
        ).mappings().first()

        if existing_source:

            # Same bytes must not silently represent
            # another reporting period.
            if str(existing_source["report_period"]) != args.report_period:
                raise ValueError(
                    "SHA-256 already exists in source_documents but "
                    "with a different report_period.\n"
                    f"Existing : {existing_source['report_period']}\n"
                    f"Requested: {args.report_period}"
                )

            source_document_id = existing_source["source_document_id"]

            print(
                f"Source already registered "
                f"(source_document_id={source_document_id})"
            )

        else:

            # -------------------------------------------------
            # 2. Register new source document
            # -------------------------------------------------

            result = conn.execute(
                text(
                    """
                    INSERT INTO ingest.source_documents (
                        filename,
                        file_type,
                        sha256,
                        report_period,
                        report_type,
                        source_path,
                        ingested_at
                    )
                    VALUES (
                        :filename,
                        :file_type,
                        :sha256,
                        :report_period,
                        :report_type,
                        :source_path,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING source_document_id
                    """
                ),
                {
                    "filename": source_path.name,
                    "file_type": source_path.suffix.lower().lstrip("."),
                    "sha256": file_hash,
                    "report_period": args.report_period,
                    "report_type": args.report_type,
                    "source_path": str(source_path),
                },
            )

            source_document_id = result.scalar_one()

            print(
                f"Source registered "
                f"(source_document_id={source_document_id})"
            )

        # -------------------------------------------------
        # 3. Check for an existing successful registration
        # -------------------------------------------------

        existing_run = conn.execute(
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
                "run_type": args.run_type,
                "pipeline_version": args.pipeline_version,
                "silver_version": silver_version,
            },
        ).mappings().first()

        if existing_run:

            print()
            print("Load run already exists.")
            print(f"load_run_id       : {existing_run['load_run_id']}")
            print(f"status            : {existing_run['status']}")
            print(f"rows_read         : {existing_run['rows_read']}")
            print(f"rows_loaded       : {existing_run['rows_loaded']}")
            print(f"rows_failed       : {existing_run['rows_failed']}")

            print()
            print("IDEMPOTENCY CHECK: PASS")
            print("No duplicate source/load-run created.")

            return

        # -------------------------------------------------
        # 4. Create load run
        # -------------------------------------------------

        result = conn.execute(
            text(
                """
                INSERT INTO ingest.load_runs (
                    run_type,
                    source_document_id,
                    report_period,
                    pipeline_version,
                    silver_version,
                    gold_version,
                    model_version,
                    started_at,
                    finished_at,
                    status,
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
                    NULL,
                    NULL,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    'success',
                    :rows_read,
                    0,
                    0
                )
                RETURNING load_run_id
                """
            ),
            {
                "run_type": args.run_type,
                "source_document_id": source_document_id,
                "report_period": args.report_period,
                "pipeline_version": args.pipeline_version,
                "silver_version": silver_version,
                "rows_read": row_count,
            },
        )

        load_run_id = result.scalar_one()

        print()
        print("Load run created.")
        print(f"load_run_id       : {load_run_id}")
        print(f"source_document_id: {source_document_id}")
        print(f"rows_read         : {row_count}")
        print("rows_loaded       : 0")
        print("rows_failed       : 0")
        print("status            : success")

    print()
    print("=" * 70)
    print("REGISTRATION COMPLETE")
    print("=" * 70)


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    try:
        args = parse_args()
        register_source_and_run(args)

    except Exception as exc:
        print()
        print("ERROR")
        print("-" * 70)
        print(exc)
        sys.exit(1)