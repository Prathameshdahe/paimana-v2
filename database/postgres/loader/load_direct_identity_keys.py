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
    print("PAIMANA DIRECT IDENTITY LOADER")
    print("=" * 70)
    print(f"Source load_run_id : {LOAD_RUN_ID}")
    print()

    with engine.begin() as conn:

        # -----------------------------------------------------
        # Insert only valid observations with direct OCMS match
        # -----------------------------------------------------

        result = conn.execute(
            text(
                """
                INSERT INTO core.project_keys (
                    project_id,
                    source_system,
                    source_project_key,
                    source_project_name,
                    match_method,
                    match_score,
                    review_status,
                    merged_into
                )
                SELECT DISTINCT
                    p.project_id,
                    'OCMS',
                    s.source_project_key,
                    s.project_name_raw,
                    'direct_canonical_key',
                    1.0,
                    'approved',
                    NULL
                FROM ingest.staging_project_observations s
                JOIN core.projects p
                  ON p.canonical_project_key =
                     'OCMS:' || s.source_project_key
                WHERE s.load_run_id = :load_run_id
                  AND s.validation_status = 'valid'
                ON CONFLICT (source_system, source_project_key)
                DO NOTHING
                """
            ),
            {"load_run_id": LOAD_RUN_ID},
        )

        print(f"Inserted identity mappings : {result.rowcount}")

        # -----------------------------------------------------
        # Summary
        # -----------------------------------------------------

        total = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM core.project_keys
                WHERE source_system = 'OCMS'
                AND match_method = 'direct_canonical_key'
                """
            )
        ).scalar_one()

        print(f"Total direct OCMS mappings: {total}")

    print()
    print("=" * 70)
    print("DIRECT IDENTITY LOAD COMPLETE")
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
