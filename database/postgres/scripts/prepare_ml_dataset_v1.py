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
    / "features_ml_v1_labeled.csv"
)

OUTPUT_DIR = (
    ROOT
    / "dataset"
    / "gold"
    / "ml"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# =========================================================
# LOAD
# =========================================================

df = pd.read_csv(INPUT_FILE)

df["report_period"] = pd.to_datetime(
    df["report_period"],
    errors="coerce",
)

df["target_6m"] = pd.to_numeric(
    df["target_6m"],
    errors="coerce",
)

df = df[
    df["target_6m"].isin([0, 1])
].copy()

df = df.sort_values(
    ["report_period", "project_id"]
).reset_index(drop=True)


print("=" * 70)
print("PREPARING ML TRAINING DATASET V1")
print("=" * 70)

print(f"Labelled rows: {len(df):,}")


# =========================================================
# CHRONOLOGICAL SPLIT
#
# Train = Apr 2024
# Validation = Jul 2024
# Test = Oct 2024
#
# These are the periods with BOTH classes.
# =========================================================

TRAIN_PERIOD = pd.Timestamp("2024-04-01")
VALIDATION_PERIOD = pd.Timestamp("2024-07-01")
TEST_PERIOD = pd.Timestamp("2024-10-01")


train = df[
    df["report_period"] == TRAIN_PERIOD
].copy()

validation = df[
    df["report_period"] == VALIDATION_PERIOD
].copy()

test = df[
    df["report_period"] == TEST_PERIOD
].copy()


# =========================================================
# POINT-IN-TIME ML FEATURES
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

    # Financial / physical relationship
    "financial_progress_pct",
    "physical_financial_gap_pct",

    # Change from previous observation
    "physical_progress_delta",
    "expenditure_delta_cr",
    "cost_revision_delta_cr",
    "delay_delta_months",

    # Velocity
    "physical_progress_velocity",
    "expenditure_velocity_cr",

    # Previous state
    "previous_progress_pct",
    "previous_expenditure_cr",
    "previous_cost_revised_cr",
    "previous_delay_months",

    # Time since previous observation
    "days_since_previous_report",

    # Project history
    "months_since_first_observation",
]


missing_features = [
    column
    for column in feature_columns
    if column not in df.columns
]

if missing_features:
    raise ValueError(
        "Missing expected feature columns: "
        + ", ".join(missing_features)
    )


# =========================================================
# BUILD X / Y
# =========================================================

def make_dataset(frame):

    X = frame[
        feature_columns
    ].copy()

    y = frame[
        "target_6m"
    ].astype(int)

    return X, y


X_train, y_train = make_dataset(train)

X_validation, y_validation = make_dataset(
    validation
)

X_test, y_test = make_dataset(test)


# =========================================================
# DATASET SUMMARY
# =========================================================

def print_summary(
    name,
    frame,
    y,
):

    print(
        f"\n{name}"
    )

    print(
        "-" * 50
    )

    print(
        f"Period:       "
        f"{frame['report_period'].iloc[0].date()}"
    )

    print(
        f"Rows:         {len(frame):,}"
    )

    print(
        f"Positive:     {(y == 1).sum():,}"
    )

    print(
        f"Negative:     {(y == 0).sum():,}"
    )

    print(
        f"Positive %:   "
        f"{(y == 1).mean() * 100:.2f}%"
    )


print_summary(
    "TRAIN",
    train,
    y_train,
)

print_summary(
    "VALIDATION",
    validation,
    y_validation,
)

print_summary(
    "TEST",
    test,
    y_test,
)


# =========================================================
# SAVE DATASETS
# =========================================================

def save_dataset(
    X,
    y,
    filename,
):

    output = X.copy()

    output["target_6m"] = y.values

    output.to_csv(
        OUTPUT_DIR / filename,
        index=False,
    )


save_dataset(
    X_train,
    y_train,
    "train_v1.csv",
)

save_dataset(
    X_validation,
    y_validation,
    "validation_v1.csv",
)

save_dataset(
    X_test,
    y_test,
    "test_v1.csv",
)


# =========================================================
# SAVE FEATURE CONTRACT
# =========================================================

feature_list = (
    OUTPUT_DIR
    / "feature_columns_v1.txt"
)

feature_list.write_text(
    "\n".join(feature_columns),
    encoding="utf-8",
)


# =========================================================
# SAVE SPLIT CONTRACT
# =========================================================

split_contract = (
    OUTPUT_DIR
    / "split_v1.txt"
)

split_contract.write_text(
    "\n".join(
        [
            "ML SPLIT V1",
            "",
            "TRAIN = 2024-04-01",
            "VALIDATION = 2024-07-01",
            "TEST = 2024-10-01",
            "",
            "Split type = chronological",
            "Censored rows excluded",
            "Future evidence columns excluded",
            "Project identifiers excluded",
            "Provenance/source fields excluded",
        ]
    ),
    encoding="utf-8",
)


# =========================================================
# FINAL
# =========================================================

print("\n" + "=" * 70)
print("ML DATASET PREPARATION COMPLETE")
print("=" * 70)

print(
    f"Features: {len(feature_columns)}"
)

print(
    f"Train:    {len(X_train):,}"
)

print(
    f"Validation: {len(X_validation):,}"
)

print(
    f"Test:     {len(X_test):,}"
)

print(
    "\nCreated:"
)

print(
    f"  {OUTPUT_DIR / 'train_v1.csv'}"
)

print(
    f"  {OUTPUT_DIR / 'validation_v1.csv'}"
)

print(
    f"  {OUTPUT_DIR / 'test_v1.csv'}"
)

print(
    f"  {feature_list}"
)

print(
    f"  {split_contract}"
)