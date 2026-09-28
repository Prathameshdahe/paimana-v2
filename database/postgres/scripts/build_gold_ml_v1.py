from pathlib import Path

import pandas as pd


# =========================================================
# CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parents[3]

INPUT_FILE = (
    ROOT
    / "dataset"
    / "gold"
    / "features_v1.csv"
)

OUTPUT_FILE = (
    ROOT
    / "dataset"
    / "gold"
    / "features_ml_v1.csv"
)


# =========================================================
# LOAD
# =========================================================

df = pd.read_csv(INPUT_FILE)

print("=" * 70)
print("BUILDING ML-READY GOLD V1")
print("=" * 70)

print(f"Input rows:    {len(df):,}")
print(f"Input columns: {len(df.columns):,}")


# =========================================================
# DATA QUALITY FLAGS
# =========================================================

df["dq_physical_progress_invalid"] = (
    df["physical_progress_pct"].notna()
    & (
        (df["physical_progress_pct"] < 0)
        | (df["physical_progress_pct"] > 100)
    )
)

df["dq_negative_expenditure"] = (
    df["cumulative_expenditure_cr"].notna()
    & (df["cumulative_expenditure_cr"] < 0)
)

df["dq_negative_original_cost"] = (
    df["cost_original_cr"].notna()
    & (df["cost_original_cr"] < 0)
)

df["dq_extreme_financial_progress"] = (
    df["financial_progress_pct"].notna()
    & (df["financial_progress_pct"] > 200)
)

df["dq_extreme_progress_gap"] = (
    df["physical_financial_gap_pct"].notna()
    & (
        df["physical_financial_gap_pct"].abs() > 200
    )
)


# =========================================================
# OVERALL QUALITY FLAG
# =========================================================

dq_columns = [
    "dq_physical_progress_invalid",
    "dq_negative_expenditure",
    "dq_negative_original_cost",
]

df["dq_row_flag"] = df[dq_columns].any(axis=1)


# =========================================================
# ML FEATURE SET
# =========================================================

feature_columns = [
    # Current project state
    "physical_progress_pct",
    "cumulative_expenditure_cr",
    "cost_original_cr",
    "cost_revised_cr",
    "cost_anticipated_cr",
    "cost_overrun_cr",
    "cost_overrun_pct",
    "delay_months",

    # Derived financial / physical signals
    "financial_progress_pct",
    "physical_financial_gap_pct",

    # Longitudinal change
    "physical_progress_delta",
    "expenditure_delta_cr",
    "cost_revision_delta_cr",
    "delay_delta_months",

    # Velocity
    "physical_progress_velocity",
    "expenditure_velocity_cr",

    # Project history
    "months_since_first_observation",
]


# =========================================================
# CONTEXT COLUMNS
# =========================================================

context_columns = [
    "project_id",
    "report_period",
    "project_name",
    "sector_name",
    "state",
    "implementing_agency",
    "project_type",
]


# =========================================================
# QUALITY COLUMNS
# =========================================================

quality_columns = [
    "dq_physical_progress_invalid",
    "dq_negative_expenditure",
    "dq_negative_original_cost",
    "dq_extreme_financial_progress",
    "dq_extreme_progress_gap",
    "dq_row_flag",
]


# =========================================================
# BUILD OUTPUT
# =========================================================

available_features = [
    column
    for column in feature_columns
    if column in df.columns
]

available_context = [
    column
    for column in context_columns
    if column in df.columns
]

available_quality = [
    column
    for column in quality_columns
    if column in df.columns
]

output_columns = (
    available_context
    + ["report_period"]
    + available_features
    + available_quality
)

# Remove accidental duplicates while preserving order
output_columns = list(
    dict.fromkeys(output_columns)
)

ml = df[output_columns].copy()


# =========================================================
# SORT
# =========================================================

ml = ml.sort_values(
    [
        "project_id",
        "report_period",
    ]
).reset_index(drop=True)


# =========================================================
# SAVE
# =========================================================

ml.to_csv(
    OUTPUT_FILE,
    index=False,
)


# =========================================================
# SUMMARY
# =========================================================

print("\n" + "=" * 70)
print("ML GOLD CREATED")
print("=" * 70)

print(f"Rows:    {len(ml):,}")
print(f"Columns: {len(ml.columns):,}")

print(
    f"Rows with core DQ flags: "
    f"{ml['dq_row_flag'].sum():,}"
)

print(
    f"Physical progress invalid: "
    f"{ml['dq_physical_progress_invalid'].sum():,}"
)

print(
    f"Extreme financial progress: "
    f"{ml['dq_extreme_financial_progress'].sum():,}"
)

print(
    f"Extreme progress gap: "
    f"{ml['dq_extreme_progress_gap'].sum():,}"
)

print(f"\nOutput: {OUTPUT_FILE}")