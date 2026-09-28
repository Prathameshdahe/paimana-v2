from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[3]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres.config import get_engine


CHECKS = [
    (
        "Total timeline rows",
        """
        SELECT COUNT(*)
        FROM core.project_timeline
        """,
    ),
    (
        "Unique project-periods",
        """
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT project_id, report_period
            FROM core.project_timeline
        ) x
        """,
    ),
    (
        "Duplicate project-periods",
        """
        SELECT COUNT(*)
        FROM (
            SELECT project_id, report_period
            FROM core.project_timeline
            GROUP BY project_id, report_period
            HAVING COUNT(*) > 1
        ) x
        """,
    ),
    (
        "Missing project FK",
        """
        SELECT COUNT(*)
        FROM core.project_timeline t
        LEFT JOIN core.projects p
          ON p.project_id = t.project_id
        WHERE p.project_id IS NULL
        """,
    ),
    (
        "Missing source document",
        """
        SELECT COUNT(*)
        FROM core.project_timeline t
        LEFT JOIN ingest.source_documents d
          ON d.source_document_id = t.source_document_id
        WHERE t.source_document_id IS NOT NULL
          AND d.source_document_id IS NULL
        """,
    ),
    (
        "Missing report period",
        """
        SELECT COUNT(*)
        FROM core.project_timeline
        WHERE report_period IS NULL
        """,
    ),
    (
        "Missing project name",
        """
        SELECT COUNT(*)
        FROM core.project_timeline
        WHERE project_name IS NULL
           OR BTRIM(project_name) = ''
        """,
    ),
]


def main():
    engine = get_engine()

    print("=" * 70)
    print("PAIMANA CORE TIMELINE AUDIT")
    print("=" * 70)
    print()

    passed = True

    with engine.connect() as conn:
        for name, query in CHECKS:
            value = conn.execute(text(query)).scalar_one()

            print(f"{name:30}: {value}")

            if name != "Total timeline rows" and name != "Unique project-periods":
                if value != 0:
                    passed = False

    print()

    if passed:
        print("RESULT: PASS")
    else:
        print("RESULT: REVIEW REQUIRED")

    print("=" * 70)


if __name__ == "__main__":
    main()
