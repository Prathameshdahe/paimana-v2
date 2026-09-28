from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres.config import get_engine


LOAD_RUN_ID = 10
PIPELINE_VERSION = "phase4_core_promotion_v1"
SILVER_VERSION = "project_monitoring_2025-26_clean"


def main():
    engine = get_engine()

    print("=" * 70)
    print("PAIMANA STAGING -> CORE TIMELINE PROMOTION")
    print("=" * 70)
    print(f"Source load_run_id : {LOAD_RUN_ID}")
    print(f"Pipeline version   : {PIPELINE_VERSION}")
    print(f"Silver version     : {SILVER_VERSION}")
    print()

    with engine.begin() as conn:

        # ---------------------------------------------------------
        # Count trusted observations available for promotion
        # ---------------------------------------------------------

        trusted_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM ingest.staging_project_observations s
                JOIN core.project_keys k
                  ON k.source_system = 'OCMS'
                 AND k.source_project_key = s.source_project_key
                 AND k.review_status = 'approved'
                 AND k.match_method = 'direct_canonical_key'
                WHERE s.load_run_id = :load_run_id
                  AND s.validation_status = 'valid'
                """
            ),
            {"load_run_id": LOAD_RUN_ID},
        ).scalar_one()

        print(f"Trusted observations available : {trusted_count}")

        # ---------------------------------------------------------
        # Promote trusted observations into Core timeline
        # ---------------------------------------------------------

        result = conn.execute(
            text(
                """
                INSERT INTO core.project_timeline (
                    project_id,
                    source_project_key,
                    report_period,
                    report_type,
                    project_name,
                    sector_name,
                    state,
                    implementing_agency,
                    project_type,

                    cost_original_cr,
                    cost_revised_cr,
                    cost_anticipated_cr,
                    cost_overrun_cr,
                    cost_overrun_pct,
                    cumulative_expenditure_cr,

                    doc_original,
                    doc_revised,
                    doc_anticipated,
                    delay_months,
                    physical_progress_pct,

                    source_document_id,
                    source_page,
                    source_file,
                    silver_version,
                    loaded_at
                )
                SELECT
                    k.project_id,
                    s.source_project_key,
                    s.parsed_report_period,
                    s.report_type_raw,
                    s.project_name_raw,
                    s.sector_raw,
                    s.state_raw,
                    s.agency_raw,
                    s.project_type_raw,

                    s.parsed_cost_original_cr,
                    s.parsed_cost_revised_cr,
                    s.parsed_cost_anticipated_cr,
                    s.parsed_cost_overrun_cr,
                    s.parsed_cost_overrun_pct,
                    s.parsed_cumulative_expenditure_cr,

                    s.parsed_doc_original,
                    s.parsed_doc_revised,
                    s.parsed_doc_anticipated,
                    s.parsed_delay_months,
                    s.parsed_physical_progress_pct,

                    s.source_document_id,
                    s.source_page,
                    s.source_file,
                    :silver_version,
                    NOW()

                FROM ingest.staging_project_observations s

                JOIN core.project_keys k
                  ON k.source_system = 'OCMS'
                 AND k.source_project_key = s.source_project_key
                 AND k.review_status = 'approved'
                 AND k.match_method = 'direct_canonical_key'

                WHERE s.load_run_id = :load_run_id
                  AND s.validation_status = 'valid'

                ON CONFLICT (project_id, report_period)
                DO NOTHING
                """
            ),
            {
                "load_run_id": LOAD_RUN_ID,
                "silver_version": SILVER_VERSION,
            },
        )

        print(f"Inserted timeline rows          : {result.rowcount}")

        # ---------------------------------------------------------
        # Verify Core timeline count
        # ---------------------------------------------------------

        timeline_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM core.project_timeline
                """
            )
        ).scalar_one()

        print(f"Total core.timeline rows        : {timeline_count}")

    print()
    print("=" * 70)
    print("CORE TIMELINE PROMOTION COMPLETE")
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