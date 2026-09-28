from pathlib import Path

import pandas as pd


# =========================================================
# CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parents[3]

GOLD_FILE = (
    ROOT
    / "dataset"
    / "gold"
    / "features_v1.csv"
)


# =========================================================
# LOAD GOLD
# =========================================================

gold = pd.read_csv(GOLD_FILE)

print("=" * 70)
print("GOLD FEATURE QUALITY AUDIT")
print("=" * 70)

print(f"Rows:    {len(gold):,}")
print(f"Columns: {len(gold.columns):,}")


# =========================================================
# 1. DUPLICATE PROJECT-PERIOD CHECK
# =========================================================

print("\n" + "=" * 70)
print("1. DUPLICATE PROJECT-PERIOD CHECK")
print("=" * 70)

duplicates = gold.duplicated(
    subset=["project_id", "report_period"],
    keep=False,
)

print(f"Duplicate rows: {duplicates.sum():,}")

if duplicates.any():
    print(
        gold.loc[
            duplicates,
            ["project_id", "report_period"],
        ]
        .sort_values(["project_id", "report_period"])
        .head(20)
        .to_string(index=False)
    )


# =========================================================
# 2. PHYSICAL PROGRESS RANGE
# =========================================================

print("\n" + "=" * 70)
print("2. PHYSICAL PROGRESS RANGE")
print("=" * 70)

progress = pd.to_numeric(
    gold["physical_progress_pct"],
    errors="coerce",
)

invalid_progress = (
    progress.notna()
    & (
        (progress < 0)
        | (progress > 100)
    )
)

print(f"Non-null:         {progress.notna().sum():,}")
print(f"Invalid (<0/>100): {invalid_progress.sum():,}")

if invalid_progress.any():
    print(
        gold.loc[
            invalid_progress,
            [
                "project_id",
                "report_period",
                "physical_progress_pct",
            ],
        ]
        .head(20)
        .to_string(index=False)
    )


# =========================================================
# 3. FINANCIAL VALUE CHECK
# =========================================================

print("\n" + "=" * 70)
print("3. FINANCIAL VALUE CHECK")
print("=" * 70)

financial_columns = [
    "cost_original_cr",
    "cost_revised_cr",
    "cost_anticipated_cr",
    "cost_overrun_cr",
    "cumulative_expenditure_cr",
]

for column in financial_columns:

    if column not in gold.columns:
        continue

    values = pd.to_numeric(
        gold[column],
        errors="coerce",
    )

    negative = (
        values.notna()
        & (values < 0)
    )

    print(
        f"{column:<30} "
        f"negative: {negative.sum():,} "
        f"min: {values.min()} "
        f"max: {values.max()}"
    )


# =========================================================
# 4. FINANCIAL PROGRESS / GAP EXTREMES
# =========================================================

print("\n" + "=" * 70)
print("4. FINANCIAL PROGRESS / GAP EXTREMES")
print("=" * 70)

for column in [
    "financial_progress_pct",
    "physical_financial_gap_pct",
]:

    values = pd.to_numeric(
        gold[column],
        errors="coerce",
    )

    print(f"\n--- {column} ---")

    print(
        values.describe(
            percentiles=[
                0.01,
                0.05,
                0.50,
                0.95,
                0.99,
            ]
        ).to_string()
    )

    print("\nTop 10 highest:")

    print(
        gold.loc[
            values.nlargest(10).index,
            [
                "project_id",
                "report_period",
                "physical_progress_pct",
                "cumulative_expenditure_cr",
                "cost_original_cr",
                column,
            ],
        ]
        .to_string(index=False)
    )


# =========================================================
# 5. LONGITUDINAL COVERAGE
# =========================================================

print("\n" + "=" * 70)
print("5. LONGITUDINAL COVERAGE")
print("=" * 70)

period_counts = (
    gold.groupby("project_id")
    .size()
)

print(
    f"Projects:              {period_counts.shape[0]:,}"
)

print(
    f"Projects with 1 period: "
    f"{(period_counts == 1).sum():,}"
)

print(
    f"Projects with 2 periods: "
    f"{(period_counts == 2).sum():,}"
)

print(
    f"Projects with 3 periods: "
    f"{(period_counts == 3).sum():,}"
)

print(
    f"Maximum periods/project: "
    f"{period_counts.max():,}"
)


# =========================================================
# 6. FEATURE NULL SUMMARY
# =========================================================

print("\n" + "=" * 70)
print("6. FEATURE NULL SUMMARY")
print("=" * 70)

null_summary = (
    gold.isna()
    .sum()
    .sort_values(ascending=False)
)

for column, count in null_summary.items():

    if count > 0:

        pct = (
            count
            / len(gold)
            * 100
        )

        print(
            f"{column:<35} "
            f"{count:>6,} "
            f"({pct:>6.2f}%)"
        )


# =========================================================
# FINAL
# =========================================================

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)