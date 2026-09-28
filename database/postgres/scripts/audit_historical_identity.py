from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

FILES = [
    ROOT / "dataset/silver/project_monitoring_2024-25_clean.csv",
    ROOT / "dataset/silver/project_monitoring_2025-26_clean.csv",
    ROOT / "dataset/silver/project_monitoring_2026-27_clean.csv",
]


frames = []

for file in FILES:

    df = pd.read_csv(file)

    df["source_file_period"] = file.stem

    frames.append(
        df[
            [
                "project_id",
                "project_name",
                "sector",
                "state",
                "agency",
                "source_file_period",
            ]
        ]
    )


all_data = pd.concat(
    frames,
    ignore_index=True,
)


print("=" * 80)
print("HISTORICAL IDENTITY CONSISTENCY AUDIT")
print("=" * 80)

print(
    f"Total observations: {len(all_data):,}"
)

print(
    f"Unique source project IDs: "
    f"{all_data['project_id'].nunique():,}"
)


# ---------------------------------------------------------
# Name consistency
# ---------------------------------------------------------

name_counts = (
    all_data
    .dropna(subset=["project_name"])
    .groupby("project_id")["project_name"]
    .nunique()
)

name_conflicts = name_counts[
    name_counts > 1
]

print("\nProject-name conflicts:")
print(
    f"Source IDs with multiple names: "
    f"{len(name_conflicts):,}"
)


# ---------------------------------------------------------
# Sector consistency
# ---------------------------------------------------------

sector_counts = (
    all_data
    .dropna(subset=["sector"])
    .groupby("project_id")["sector"]
    .nunique()
)

sector_conflicts = sector_counts[
    sector_counts > 1
]

print("\nSector conflicts:")
print(
    f"Source IDs with multiple sectors: "
    f"{len(sector_conflicts):,}"
)


# ---------------------------------------------------------
# State consistency
# ---------------------------------------------------------

state_counts = (
    all_data
    .dropna(subset=["state"])
    .groupby("project_id")["state"]
    .nunique()
)

state_conflicts = state_counts[
    state_counts > 1
]

print("\nState conflicts:")
print(
    f"Source IDs with multiple states: "
    f"{len(state_conflicts):,}"
)


# ---------------------------------------------------------
# Agency consistency
# ---------------------------------------------------------

agency_counts = (
    all_data
    .dropna(subset=["agency"])
    .groupby("project_id")["agency"]
    .nunique()
)

agency_conflicts = agency_counts[
    agency_counts > 1
]

print("\nAgency conflicts:")
print(
    f"Source IDs with multiple agencies: "
    f"{len(agency_conflicts):,}"
)


# ---------------------------------------------------------
# Show examples
# ---------------------------------------------------------

for title, conflicts in [
    ("NAME", name_conflicts),
    ("SECTOR", sector_conflicts),
    ("STATE", state_conflicts),
    ("AGENCY", agency_conflicts),
]:

    if len(conflicts) == 0:
        continue

    print("\n" + "-" * 80)
    print(f"{title} CONFLICT EXAMPLES")
    print("-" * 80)

    ids = conflicts.head(10).index

    print(
        all_data[
            all_data["project_id"].isin(ids)
        ]
        .sort_values(
            ["project_id", "source_file_period"]
        )
        .to_string(index=False)
    )


print("\n" + "=" * 80)
print("AUDIT COMPLETE")
print("=" * 80)