from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

SILVER_FILE = (
    ROOT
    / "dataset"
    / "silver"
    / "project_monitoring_2025-26_clean.csv"
)

CROSSWALK_FILE = (
    ROOT
    / "dataset"
    / "clean"
    / "reference"
    / "project_id_crosswalk.csv"
)


silver = pd.read_csv(SILVER_FILE)
crosswalk = pd.read_csv(CROSSWALK_FILE)

accepted = crosswalk[
    crosswalk["applied"].astype(str).str.lower().eq("true")
].copy()


print("=" * 60)
print("SILVER PROJECT ID SAMPLES")
print("=" * 60)

print(
    silver["project_id"]
    .dropna()
    .astype(str)
    .head(20)
    .to_string(index=False)
)


print("\n" + "=" * 60)
print("CROSSWALK key_b SAMPLES")
print("=" * 60)

print(
    accepted["key_b"]
    .dropna()
    .astype(str)
    .head(20)
    .to_string(index=False)
)


print("\n" + "=" * 60)
print("CROSSWALK key_a SAMPLES")
print("=" * 60)

print(
    accepted["key_a"]
    .dropna()
    .astype(str)
    .head(20)
    .to_string(index=False)
)


print("\n" + "=" * 60)
print("SILVER REPORT PERIOD")
print("=" * 60)

silver_period = (
    pd.to_datetime(silver["report_date"], errors="coerce")
    .dt.to_period("M")
    .dt.to_timestamp()
)

print(silver_period.dropna().drop_duplicates().sort_values().to_string(index=False))


print("\n" + "=" * 60)
print("CROSSWALK REPORT PERIOD")
print("=" * 60)

crosswalk_period = (
    pd.to_datetime(
        accepted["report_period"],
        errors="coerce"
    )
    .dt.to_period("M")
    .dt.to_timestamp()
)

print(
    crosswalk_period
    .dropna()
    .drop_duplicates()
    .sort_values()
    .to_string(index=False)
)


print("\n" + "=" * 60)
print("DATA TYPES")
print("=" * 60)

print("Silver project_id:", silver["project_id"].dtype)
print("Crosswalk key_b:", accepted["key_b"].dtype)