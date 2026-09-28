from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

SILVER_DIR = ROOT / "dataset" / "silver"


print("=" * 80)
print("HISTORICAL SILVER INVENTORY")
print("=" * 80)

files = sorted(
    SILVER_DIR.glob("project_monitoring_*_clean.csv")
)

print(f"Files found: {len(files)}")

results = []

for file in files:

    try:
        df = pd.read_csv(file)

        period = file.stem.replace(
            "project_monitoring_", ""
        ).replace(
            "_clean",
            "",
        )

        unique_projects = (
            df["project_id"]
            .nunique()
            if "project_id" in df.columns
            else 0
        )

        results.append(
            {
                "file": file.name,
                "period": period,
                "rows": len(df),
                "unique_projects": unique_projects,
                "columns": len(df.columns),
            }
        )

    except Exception as e:

        results.append(
            {
                "file": file.name,
                "period": "ERROR",
                "rows": None,
                "unique_projects": None,
                "columns": None,
                "error": str(e),
            }
        )


result_df = pd.DataFrame(results)

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if len(result_df):

    print(
        result_df.to_string(
            index=False
        )
    )

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)