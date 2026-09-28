from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

FILES = [
    ROOT / "dataset/silver/project_monitoring_2024-25_clean.csv",
    ROOT / "dataset/silver/project_monitoring_2025-26_clean.csv",
    ROOT / "dataset/silver/project_monitoring_2026-27_clean.csv",
]


print("=" * 80)
print("HISTORICAL REPORTING PERIOD AUDIT")
print("=" * 80)


for file in FILES:

    print("\n" + "=" * 80)
    print(file.name)
    print("=" * 80)

    df = pd.read_csv(file)

    print(f"Rows: {len(df):,}")
    print(f"Unique projects: {df['project_id'].nunique():,}")

    dates = pd.to_datetime(
        df["report_date"],
        errors="coerce",
    )

    print(f"Invalid report dates: {dates.isna().sum():,}")

    print("\nReporting periods:")

    periods = (
        dates
        .dt.to_period("M")
        .value_counts()
        .sort_index()
    )

    print(periods.to_string())

    print("\nProject-period duplicates:")

    duplicate_count = (
        df.assign(
            report_period=dates.dt.to_period("M")
        )
        .duplicated(
            subset=["project_id", "report_period"],
            keep=False,
        )
        .sum()
    )

    print(f"Duplicate rows: {duplicate_count:,}")

    print("\nColumns:")

    print(
        ", ".join(df.columns)
    )