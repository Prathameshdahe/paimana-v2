from pathlib import Path

import pandas as pd


# =========================================================
# CONFIG
# =========================================================

ROOT = Path(__file__).resolve().parents[3]

FILE = (
    ROOT
    / "dataset"
    / "gold"
    / "features_ml_v1_labeled.csv"
)


# =========================================================
# LOAD
# =========================================================

df = pd.read_csv(FILE)

df["report_period"] = pd.to_datetime(
    df["report_period"],
    errors="coerce",
)

print("=" * 70)
print("TARGET V1 VALIDATION")
print("=" * 70)

print(f"Rows:     {len(df):,}")
print(f"Projects: {df['project_id'].nunique():,}")


# =========================================================
# 1. TARGET VALUES
# =========================================================

print("\n" + "=" * 70)
print("1. TARGET VALUES")
print("=" * 70)

print(
    df["target_6m"]
    .value_counts(dropna=False)
    .sort_index()
    .to_string()
)


invalid_target = ~df["target_6m"].isin(
    [0, 1]
) & df["target_6m"].notna()

print(
    f"\nInvalid non-null targets: "
    f"{invalid_target.sum():,}"
)


# =========================================================
# 2. LABELABILITY CONSISTENCY
# =========================================================

print("\n" + "=" * 70)
print("2. LABELABILITY CONSISTENCY")
print("=" * 70)

bad_labelable = (
    (
        df["target_labelable"] == True
    )
    != (
        df["target_6m"].notna()
    )
)

print(
    f"Mismatch between target_labelable "
    f"and target_6m: {bad_labelable.sum():,}"
)


# =========================================================
# 3. NEGATIVE LABEL SAFETY
# =========================================================

print("\n" + "=" * 70)
print("3. NEGATIVE LABEL SAFETY")
print("=" * 70)

bad_negative = (
    (df["target_6m"] == 0)
    & (
        df["followup_complete_6m"] != True
    )
)

print(
    f"Negative labels without full follow-up: "
    f"{bad_negative.sum():,}"
)


bad_negative_components = (
    (df["target_6m"] == 0)
    & (
        (
            df["schedule_target_evaluable"] != True
        )
        |
        (
            df["cost_target_evaluable"] != True
        )
    )
)

print(
    f"Negative labels without both components "
    f"evaluable: {bad_negative_components.sum():,}"
)


# =========================================================
# 4. POSITIVE LABEL LOGIC
# =========================================================

print("\n" + "=" * 70)
print("4. POSITIVE LABEL LOGIC")
print("=" * 70)

positive_without_event = (
    (df["target_6m"] == 1)
    &
    (
        (df["schedule_deterioration_6m"] != 1)
        &
        (df["cost_deterioration_6m"] != 1)
    )
)

print(
    f"Positive labels without an event: "
    f"{positive_without_event.sum():,}"
)


# =========================================================
# 5. EVENT COUNTS
# =========================================================

print("\n" + "=" * 70)
print("5. EVENT COUNTS")
print("=" * 70)

print(
    "Schedule events:",
    (
        df["schedule_deterioration_6m"] == 1
    ).sum(),
)

print(
    "Cost events:",
    (
        df["cost_deterioration_6m"] == 1
    ).sum(),
)

print(
    "Combined events:",
    (
        df["target_6m"] == 1
    ).sum(),
)


# =========================================================
# 6. LABELS BY REPORT PERIOD
# =========================================================

print("\n" + "=" * 70)
print("6. LABELS BY REPORT PERIOD")
print("=" * 70)

period_summary = (
    df.groupby("report_period")
    .agg(
        rows=("project_id", "size"),
        labelable=("target_labelable", "sum"),
        positives=("target_6m", lambda x: (x == 1).sum()),
        negatives=("target_6m", lambda x: (x == 0).sum()),
        censored=("target_6m", lambda x: x.isna().sum()),
    )
)

print(
    period_summary.to_string()
)


# =========================================================
# 7. TARGET PREVALENCE
# =========================================================

print("\n" + "=" * 70)
print("7. TARGET PREVALENCE")
print("=" * 70)

labelable = df[
    df["target_labelable"] == True
]

if len(labelable):

    prevalence = (
        (labelable["target_6m"] == 1).mean()
        * 100
    )

    print(
        f"Labelable observations: "
        f"{len(labelable):,}"
    )

    print(
        f"Positive: "
        f"{(labelable['target_6m'] == 1).sum():,}"
    )

    print(
        f"Negative: "
        f"{(labelable['target_6m'] == 0).sum():,}"
    )

    print(
        f"Prevalence: {prevalence:.2f}%"
    )


# =========================================================
# 8. POSSIBLE LEAKAGE CHECK
# =========================================================

print("\n" + "=" * 70)
print("8. LEAKAGE CHECK")
print("=" * 70)

future_evidence_columns = [
    "future_max_doc_anticipated",
    "future_max_cost_anticipated_cr",
    "future_schedule_push_months",
    "future_cost_increase_pct",
]

print(
    "Future evidence columns are retained "
    "for label/audit purposes."
)

print(
    "These columns MUST NOT be used as ML input features."
)

print(
    "\nFuture evidence columns:"
)

for column in future_evidence_columns:

    print(
        f"  - {column}"
    )


# =========================================================
# 9. FINAL SANITY
# =========================================================

issues = (
    invalid_target.sum()
    + bad_labelable.sum()
    + bad_negative.sum()
    + bad_negative_components.sum()
    + positive_without_event.sum()
)

print("\n" + "=" * 70)
print("FINAL RESULT")
print("=" * 70)

print(
    f"Validation issues: {issues:,}"
)

if issues == 0:
    print("TARGET V1 VALIDATION: PASS")
else:
    print("TARGET V1 VALIDATION: REVIEW REQUIRED")