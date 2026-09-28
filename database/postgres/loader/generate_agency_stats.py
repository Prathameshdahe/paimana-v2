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

from database.postgres.config import get_engine
from sqlalchemy import text


# =========================================================
# GENERATE AGENCY STATS
# =========================================================

engine = get_engine()

print("=" * 70)
print("AGENCY STATISTICS GENERATOR")
print("=" * 70)


with engine.begin() as connection:

    rows = connection.execute(
        text(
            """
            SELECT
                p.implementing_agency AS agency_name,
                pr.report_period,
                pr.model_id,

                COUNT(*) AS project_count,

                COUNT(*) FILTER (
                    WHERE pr.risk_tier = 'GREEN'
                ) AS green_count,

                COUNT(*) FILTER (
                    WHERE pr.risk_tier = 'AMBER'
                ) AS amber_count,

                COUNT(*) FILTER (
                    WHERE pr.risk_tier = 'RED'
                ) AS red_count,

                AVG(pr.risk_score) AS avg_risk_score

            FROM ml.predictions pr

            JOIN core.projects p
                ON p.project_id = pr.project_id

            GROUP BY
                p.implementing_agency,
                pr.report_period,
                pr.model_id

            ORDER BY
                pr.report_period,
                p.implementing_agency;
            """
        )
    ).mappings().all()


print(
    f"Agency-period-model groups found: {len(rows):,}"
)


# =========================================================
# UPSERT
# =========================================================

query = text(
    """
    INSERT INTO ml.agency_stats (
        agency_name,
        report_period,
        model_id,

        project_count,
        green_count,
        amber_count,
        red_count,

        avg_risk_score,
        stats_payload
    )
    VALUES (
        :agency_name,
        :report_period,
        :model_id,

        :project_count,
        :green_count,
        :amber_count,
        :red_count,

        :avg_risk_score,
        CAST(:stats_payload AS JSONB)
    )

    ON CONFLICT (
        agency_name,
        report_period,
        model_id
    )

    DO UPDATE SET

        project_count =
            EXCLUDED.project_count,

        green_count =
            EXCLUDED.green_count,

        amber_count =
            EXCLUDED.amber_count,

        red_count =
            EXCLUDED.red_count,

        avg_risk_score =
            EXCLUDED.avg_risk_score,

        stats_payload =
            EXCLUDED.stats_payload;
    """
)


records = []


for row in rows:

    agency_name = row["agency_name"]

    if agency_name is None:
        agency_name = "UNKNOWN"

    avg_risk = row["avg_risk_score"]

    if avg_risk is not None:
        avg_risk = float(avg_risk)

    stats_payload = {
        "project_count":
            row["project_count"],

        "green_count":
            row["green_count"],

        "amber_count":
            row["amber_count"],

        "red_count":
            row["red_count"],

        "avg_risk_score":
            avg_risk,
    }

    records.append(
        {
            "agency_name":
                agency_name,

            "report_period":
                row["report_period"],

            "model_id":
                row["model_id"],

            "project_count":
                row["project_count"],

            "green_count":
                row["green_count"],

            "amber_count":
                row["amber_count"],

            "red_count":
                row["red_count"],

            "avg_risk_score":
                avg_risk,

            "stats_payload":
                json.dumps(stats_payload),
        }
    )


# =========================================================
# LOAD
# =========================================================

with engine.begin() as connection:

    if records:

        connection.execute(
            query,
            records,
        )


# =========================================================
# VERIFY
# =========================================================

with engine.connect() as connection:

    total = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ml.agency_stats;
            """
        )
    ).scalar_one()

    summary = connection.execute(
        text(
            """
            SELECT
                agency_name,
                report_period,
                model_id,
                project_count,
                green_count,
                amber_count,
                red_count,
                avg_risk_score
            FROM ml.agency_stats
            ORDER BY
                report_period,
                agency_name;
            """
        )
    ).fetchall()


# =========================================================
# RESULT
# =========================================================

print("\n" + "=" * 70)
print("AGENCY STATISTICS CREATED")
print("=" * 70)

print(
    f"Groups processed: {len(records):,}"
)

print(
    f"Total stored groups: {total:,}"
)

print("\nStatistics:")

for row in summary:

    print(
        f"  Agency={row[0]!r} | "
        f"Period={row[1]} | "
        f"Model={row[2]} | "
        f"Projects={row[3]} | "
        f"Green={row[4]} | "
        f"Amber={row[5]} | "
        f"Red={row[6]} | "
        f"AvgRisk={row[7]}"
    )

print(
    "\nAgency statistics generation complete."
)