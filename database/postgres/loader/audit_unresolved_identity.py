from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres.config import get_engine


LOAD_RUN_ID = 10


def main():
    engine = get_engine()

    print("=" * 70)
    print("PAIMANA UNRESOLVED IDENTITY AUDIT")
    print("=" * 70)
    print(f"Load run : {LOAD_RUN_ID}")
    print()

    with engine.connect() as conn:

        # ---------------------------------------------------------
        # Overall unresolved count
        # ---------------------------------------------------------

        q = text(
            """
            SELECT COUNT(*)
            FROM ingest.staging_project_observations s
            LEFT JOIN core.project_keys k
              ON k.source_system = 'OCMS'
             AND k.source_project_key = s.source_project_key
            WHERE s.load_run_id = :load_run_id
              AND s.validation_status = 'valid'
              AND k.project_key_id IS NULL
            """
        )

        unresolved = conn.execute(
            q,
            {"load_run_id": LOAD_RUN_ID},
        ).scalar_one()

        print(f"Unresolved valid observations : {unresolved}")
        print()

        # ---------------------------------------------------------
        # Unique unresolved source keys
        # ---------------------------------------------------------

        q = text(
            """
            SELECT COUNT(DISTINCT s.source_project_key)
            FROM ingest.staging_project_observations s
            LEFT JOIN core.project_keys k
              ON k.source_system = 'OCMS'
             AND k.source_project_key = s.source_project_key
            WHERE s.load_run_id = :load_run_id
              AND s.validation_status = 'valid'
              AND k.project_key_id IS NULL
            """
        )

        unique_keys = conn.execute(
            q,
            {"load_run_id": LOAD_RUN_ID},
        ).scalar_one()

        print(f"Unique unresolved source keys : {unique_keys}")
        print()

        # ---------------------------------------------------------
        # Source-key prefix distribution
        # ---------------------------------------------------------

        print("Source-key prefixes")
        print("-" * 70)

        q = text(
            """
            SELECT
                CASE
                    WHEN POSITION(':' IN s.source_project_key) > 0
                    THEN SPLIT_PART(s.source_project_key, ':', 1)
                    ELSE 'NO_PREFIX'
                END AS prefix,
                COUNT(*) AS observations,
                COUNT(DISTINCT s.source_project_key) AS unique_keys
            FROM ingest.staging_project_observations s
            LEFT JOIN core.project_keys k
              ON k.source_system = 'OCMS'
             AND k.source_project_key = s.source_project_key
            WHERE s.load_run_id = :load_run_id
              AND s.validation_status = 'valid'
              AND k.project_key_id IS NULL
            GROUP BY 1
            ORDER BY observations DESC
            """
        )

        rows = conn.execute(
            q,
            {"load_run_id": LOAD_RUN_ID},
        ).mappings().all()

        for row in rows:
            print(
                f"{row['prefix']:20} "
                f"observations={row['observations']:6} "
                f"unique_keys={row['unique_keys']:6}"
            )

        print()

        # ---------------------------------------------------------
        # Period distribution
        # ---------------------------------------------------------

        print("Reporting-period distribution")
        print("-" * 70)

        q = text(
            """
            SELECT
                s.parsed_report_period,
                COUNT(*) AS observations,
                COUNT(DISTINCT s.source_project_key) AS unique_keys
            FROM ingest.staging_project_observations s
            LEFT JOIN core.project_keys k
              ON k.source_system = 'OCMS'
             AND k.source_project_key = s.source_project_key
            WHERE s.load_run_id = :load_run_id
              AND s.validation_status = 'valid'
              AND k.project_key_id IS NULL
            GROUP BY s.parsed_report_period
            ORDER BY s.parsed_report_period
            """
        )

        rows = conn.execute(
            q,
            {"load_run_id": LOAD_RUN_ID},
        ).mappings().all()

        for row in rows:
            print(
                f"{row['parsed_report_period']} "
                f"observations={row['observations']:6} "
                f"unique_keys={row['unique_keys']:6}"
            )

        print()

        # ---------------------------------------------------------
        # Sample unresolved records
        # ---------------------------------------------------------

        print("Sample unresolved observations")
        print("-" * 70)

        q = text(
            """
            SELECT
                s.source_project_key,
                s.project_name_raw,
                s.sector_raw,
                s.state_raw,
                s.agency_raw,
                s.parsed_report_period
            FROM ingest.staging_project_observations s
            LEFT JOIN core.project_keys k
              ON k.source_system = 'OCMS'
             AND k.source_project_key = s.source_project_key
            WHERE s.load_run_id = :load_run_id
              AND s.validation_status = 'valid'
              AND k.project_key_id IS NULL
            ORDER BY s.parsed_report_period, s.source_project_key
            LIMIT 25
            """
        )

        rows = conn.execute(
            q,
            {"load_run_id": LOAD_RUN_ID},
        ).mappings().all()

        for row in rows:
            print(dict(row))

    print()
    print("=" * 70)
    print("UNRESOLVED IDENTITY AUDIT COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
