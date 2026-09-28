from __future__ import annotations

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
# Main
# ---------------------------------------------------------

def main():
    engine = get_engine()

    print("=" * 70)
    print("PAIMANA TIMELINE LINEAGE BACKFILL")
    print("=" * 70)

    with engine.begin() as conn:

        # -------------------------------------------------
        # Show registered source documents
        # -------------------------------------------------

        sources = conn.execute(
            text(
                """
                SELECT
                    source_document_id,
                    filename,
                    report_period,
                    report_type
                FROM ingest.source_documents
                WHERE report_type = 'project_monitoring'
                ORDER BY source_document_id
                """
            )
        ).mappings().all()

        print("REGISTERED SOURCE DOCUMENTS")
        print("-" * 70)

        for source in sources:
            print(
                f"{source['source_document_id']} | "
                f"{source['filename']} | "
                f"{source['report_period']}"
            )

        print()

        # -------------------------------------------------
        # Before
        # -------------------------------------------------

        total = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM core.project_timeline
                """
            )
        ).scalar_one()

        missing_before = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM core.project_timeline
                WHERE source_document_id IS NULL
                """
            )
        ).scalar_one()

        print(f"Timeline rows       : {total}")
        print(f"Missing source IDs  : {missing_before}")
        print()

        # -------------------------------------------------
        # 2024-25 Silver artifact
        #
        # Covers observations:
        # 2024-04
        # 2024-07
        # 2024-10
        # 2025-01
        # -------------------------------------------------

        result_2024 = conn.execute(
            text(
                """
                UPDATE core.project_timeline t
                SET source_document_id = s.source_document_id
                FROM ingest.source_documents s
                WHERE t.source_document_id IS NULL
                  AND s.filename = 'project_monitoring_2024-25_clean.csv'
                  AND t.report_period >= DATE '2024-04-01'
                  AND t.report_period <  DATE '2025-04-01'
                """
            )
        )

        updated_2024 = result_2024.rowcount

        print(
            f"Linked from 2024-25 artifact : {updated_2024}"
        )

        # -------------------------------------------------
        # 2025-26 Silver artifact
        #
        # Covers observations:
        # 2025-04
        # 2025-05
        # 2025-06
        #
        # (and any future 2025-26 periods present)
        # -------------------------------------------------

        result_2025 = conn.execute(
            text(
                """
                UPDATE core.project_timeline t
                SET source_document_id = s.source_document_id
                FROM ingest.source_documents s
                WHERE t.source_document_id IS NULL
                  AND s.filename = 'project_monitoring_2025-26_clean.csv'
                  AND t.report_period >= DATE '2025-04-01'
                  AND t.report_period <  DATE '2026-04-01'
                """
            )
        )

        updated_2025 = result_2025.rowcount

        print(
            f"Linked from 2025-26 artifact : {updated_2025}"
        )

        # -------------------------------------------------
        # 2026-27 artifact
        #
        # There are currently no trusted Core timeline
        # observations for this period, but keep the rule
        # here for future loads.
        # -------------------------------------------------

        result_2026 = conn.execute(
            text(
                """
                UPDATE core.project_timeline t
                SET source_document_id = s.source_document_id
                FROM ingest.source_documents s
                WHERE t.source_document_id IS NULL
                  AND s.filename = 'project_monitoring_2026-27_clean.csv'
                  AND t.report_period >= DATE '2026-04-01'
                  AND t.report_period <  DATE '2027-04-01'
                """
            )
        )

        updated_2026 = result_2026.rowcount

        print(
            f"Linked from 2026-27 artifact : {updated_2026}"
        )

        # -------------------------------------------------
        # After
        # -------------------------------------------------

        missing_after = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM core.project_timeline
                WHERE source_document_id IS NULL
                """
            )
        ).scalar_one()

        print()
        print(f"Still missing IDs          : {missing_after}")

        # -------------------------------------------------
        # Detailed period breakdown
        # -------------------------------------------------

        rows = conn.execute(
            text(
                """
                SELECT
                    report_period,
                    COUNT(*) AS total_rows,
                    COUNT(source_document_id) AS linked_rows,
                    COUNT(*) - COUNT(source_document_id) AS missing_rows,
                    MIN(source_document_id) AS source_document_min,
                    MAX(source_document_id) AS source_document_max
                FROM core.project_timeline
                GROUP BY report_period
                ORDER BY report_period
                """
            )
        ).mappings().all()

        print()
        print("LINEAGE BREAKDOWN")
        print("-" * 70)

        for row in rows:
            print(
                f"{row['report_period']} | "
                f"total={row['total_rows']} | "
                f"linked={row['linked_rows']} | "
                f"missing={row['missing_rows']} | "
                f"source_id={row['source_document_min']}"
            )

    print()
    print("=" * 70)
    print("LINEAGE BACKFILL COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("ERROR")
        print("-" * 70)
        print(exc)
        raise