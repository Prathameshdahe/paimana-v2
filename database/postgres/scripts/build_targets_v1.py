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
    / "features_ml_v1_labeled.csv"
)

HORIZON_MONTHS = 6

SCHEDULE_PUSH_MONTHS = 3.0

COST_INCREASE_PCT = 5.0

LABEL_VERSION = "target_v1_anticipated_6m"


# =========================================================
# LOAD
# =========================================================

df = pd.read_csv(INPUT_FILE)

df["report_period"] = pd.to_datetime(
    df["report_period"],
    errors="coerce",
)

df["doc_anticipated"] = pd.to_datetime(
    df["doc_anticipated"],
    errors="coerce",
)

df["cost_anticipated_cr"] = pd.to_numeric(
    df["cost_anticipated_cr"],
    errors="coerce",
)

df = df.sort_values(
    ["project_id", "report_period"]
).reset_index(drop=True)


print("=" * 70)
print("BUILDING POINT-IN-TIME 6-MONTH TARGET")
print("=" * 70)

print(f"Input rows: {len(df):,}")
print(f"Projects:   {df['project_id'].nunique():,}")


# =========================================================
# TARGET OUTPUT COLUMNS
# =========================================================

df["schedule_deterioration_6m"] = pd.NA
df["cost_deterioration_6m"] = pd.NA

df["future_max_doc_anticipated"] = pd.NaT
df["future_max_cost_anticipated_cr"] = pd.NA

df["future_schedule_push_months"] = pd.NA
df["future_cost_increase_pct"] = pd.NA

df["followup_complete_6m"] = False

df["schedule_target_evaluable"] = False
df["cost_target_evaluable"] = False

df["target_6m"] = pd.NA
df["target_labelable"] = False

df["label_version"] = LABEL_VERSION


# =========================================================
# PROCESS EACH PROJECT
# =========================================================

for project_id, group in df.groupby(
    "project_id",
    sort=False,
):

    group = group.sort_values(
        "report_period"
    )

    indices = group.index.tolist()

    periods = group["report_period"].tolist()

    anticipated_dates = (
        group["doc_anticipated"].tolist()
    )

    anticipated_costs = (
        group["cost_anticipated_cr"].tolist()
    )

    latest_project_period = max(periods)


    for i, row_index in enumerate(indices):

        current_period = periods[i]

        horizon_end = (
            current_period
            + pd.DateOffset(
                months=HORIZON_MONTHS
            )
        )

        current_date = anticipated_dates[i]

        current_cost = anticipated_costs[i]


        # -------------------------------------------------
        # Full follow-up check
        # -------------------------------------------------

        followup_complete = (
            latest_project_period
            >= horizon_end
        )

        df.at[
            row_index,
            "followup_complete_6m",
        ] = followup_complete


        # -------------------------------------------------
        # Future observations inside 6-month horizon
        # -------------------------------------------------

        future_indices = [
            j
            for j in range(i + 1, len(indices))
            if periods[j] <= horizon_end
        ]


        if not future_indices:
            continue


        # =================================================
        # SCHEDULE TARGET
        # =================================================

        future_dates = [
            anticipated_dates[j]
            for j in future_indices
            if pd.notna(anticipated_dates[j])
        ]

        schedule_evaluable = (
            pd.notna(current_date)
            and len(future_dates) > 0
        )

        df.at[
            row_index,
            "schedule_target_evaluable",
        ] = schedule_evaluable


        schedule_event = False

        if schedule_evaluable:

            max_future_date = max(
                future_dates
            )

            df.at[
                row_index,
                "future_max_doc_anticipated",
            ] = max_future_date

            push_months = (
                (
                    max_future_date.year
                    - current_date.year
                ) * 12
                + (
                    max_future_date.month
                    - current_date.month
                )
            )

            df.at[
                row_index,
                "future_schedule_push_months",
            ] = push_months

            schedule_event = (
                push_months
                >= SCHEDULE_PUSH_MONTHS
            )

            df.at[
                row_index,
                "schedule_deterioration_6m",
            ] = int(schedule_event)


        # =================================================
        # COST TARGET
        # =================================================

        future_costs = [
            anticipated_costs[j]
            for j in future_indices
            if pd.notna(anticipated_costs[j])
        ]

        cost_evaluable = (
            pd.notna(current_cost)
            and current_cost > 0
            and len(future_costs) > 0
        )

        df.at[
            row_index,
            "cost_target_evaluable",
        ] = cost_evaluable


        cost_event = False

        if cost_evaluable:

            max_future_cost = max(
                future_costs
            )

            df.at[
                row_index,
                "future_max_cost_anticipated_cr",
            ] = max_future_cost

            increase_pct = (
                (
                    max_future_cost
                    - current_cost
                )
                / current_cost
                * 100.0
            )

            df.at[
                row_index,
                "future_cost_increase_pct",
            ] = increase_pct

            cost_event = (
                increase_pct
                >= COST_INCREASE_PCT
            )

            df.at[
                row_index,
                "cost_deterioration_6m",
            ] = int(cost_event)


        # =================================================
        # COMBINED TARGET
        # =================================================

        # Positive can be detected even before
        # the full 6-month follow-up is complete.
        positive_event = (
            (
                schedule_evaluable
                and schedule_event
            )
            or
            (
                cost_evaluable
                and cost_event
            )
        )

        if positive_event:

            df.at[
                row_index,
                "target_6m",
            ] = 1

            df.at[
                row_index,
                "target_labelable",
            ] = True

            continue


        # -------------------------------------------------
        # Negative only with full follow-up AND
        # both target components evaluable.
        # -------------------------------------------------

        negative_is_defensible = (
            followup_complete
            and schedule_evaluable
            and cost_evaluable
        )

        if negative_is_defensible:

            df.at[
                row_index,
                "target_6m",
            ] = 0

            df.at[
                row_index,
                "target_labelable",
            ] = True


# =========================================================
# FINALIZE TYPES
# =========================================================

df["target_6m"] = pd.to_numeric(
    df["target_6m"],
    errors="coerce",
).astype("Int64")

df["schedule_deterioration_6m"] = (
    pd.to_numeric(
        df["schedule_deterioration_6m"],
        errors="coerce",
    ).astype("Int64")
)

df["cost_deterioration_6m"] = (
    pd.to_numeric(
        df["cost_deterioration_6m"],
        errors="coerce",
    ).astype("Int64")
)


# =========================================================
# SAVE
# =========================================================

df.to_csv(
    OUTPUT_FILE,
    index=False,
)


# =========================================================
# SUMMARY
# =========================================================

labelable = df["target_labelable"]

positive = (
    df["target_6m"] == 1
)

negative = (
    df["target_6m"] == 0
)

censored = (
    df["target_6m"].isna()
)


print("\n" + "=" * 70)
print("TARGET SUMMARY")
print("=" * 70)

print(
    f"Rows:                       {len(df):,}"
)

print(
    f"Labelable rows:              "
    f"{labelable.sum():,}"
)

print(
    f"Positive target rows:        "
    f"{positive.sum():,}"
)

print(
    f"Negative target rows:        "
    f"{negative.sum():,}"
)

print(
    f"Censored/unlabelled rows:    "
    f"{censored.sum():,}"
)

print(
    f"Schedule deterioration:     "
    f"{(df['schedule_deterioration_6m'] == 1).sum():,}"
)

print(
    f"Cost deterioration:          "
    f"{(df['cost_deterioration_6m'] == 1).sum():,}"
)

print(
    f"Full 6-month follow-up:       "
    f"{df['followup_complete_6m'].sum():,}"
)

print(
    f"Schedule evaluable:           "
    f"{df['schedule_target_evaluable'].sum():,}"
)

print(
    f"Cost evaluable:               "
    f"{df['cost_target_evaluable'].sum():,}"
)

if positive.sum() + negative.sum() > 0:

    prevalence = (
        positive.sum()
        / labelable.sum()
        * 100
    )

    print(
        f"Positive prevalence:         "
        f"{prevalence:.2f}%"
    )

print(
    f"\nLabel version: {LABEL_VERSION}"
)

print(
    f"Output: {OUTPUT_FILE}"
)