from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

CROSSWALK_FILE = (
    ROOT
    / "dataset"
    / "clean"
    / "reference"
    / "project_id_crosswalk.csv"
)

PROJECT_MASTER_FILE = (
    ROOT
    / "dataset"
    / "clean"
    / "projects"
    / "project_master.csv"
)


crosswalk = pd.read_csv(CROSSWALK_FILE)

accepted = crosswalk[
    crosswalk["applied"].astype(str).str.lower().eq("true")
].copy()

projects = pd.read_csv(PROJECT_MASTER_FILE)


print("=" * 70)
print("CROSSWALK COLUMNS")
print("=" * 70)

print(crosswalk.columns.tolist())


print("\n" + "=" * 70)
print("PROJECT MASTER COLUMNS")
print("=" * 70)

print(projects.columns.tolist())


print("\n" + "=" * 70)
print("ACCEPTED CROSSWALK EVIDENCE")
print("=" * 70)

print(
    accepted["evidence"]
    .value_counts(dropna=False)
    .to_string()
)


print("\n" + "=" * 70)
print("ACCEPTED CROSSWALK KEY_A PREFIXES")
print("=" * 70)

print(
    accepted["key_a"]
    .astype(str)
    .str.split(":", n=1)
    .str[0]
    .value_counts()
    .to_string()
)


print("\n" + "=" * 70)
print("PROJECT MASTER KEY PREFIXES")
print("=" * 70)

print(
    projects["project_key"]
    .astype(str)
    .str.split(":", n=1)
    .str[0]
    .value_counts()
    .to_string()
)


print("\n" + "=" * 70)
print("SAMPLE ACCEPTED LINKS")
print("=" * 70)

print(
    accepted[
        [
            "key_a",
            "key_b",
            "evidence",
            "detail",
            "report_period",
            "n_occurrences",
        ]
    ]
    .head(30)
    .to_string(index=False)
)


print("\n" + "=" * 70)
print("DOES key_a EXIST IN PROJECT MASTER?")
print("=" * 70)

master_keys = set(
    projects["project_key"]
    .dropna()
    .astype(str)
)

key_a = set(
    accepted["key_a"]
    .dropna()
    .astype(str)
)

print("Accepted key_a values:", len(key_a))
print("Found in project_master:", len(key_a & master_keys))
print("Not found:", len(key_a - master_keys))


print("\n" + "=" * 70)
print("DOES key_b EXIST DIRECTLY IN PROJECT MASTER?")
print("=" * 70)

key_b = set(
    accepted["key_b"]
    .dropna()
    .astype(str)
)

print("Accepted key_b values:", len(key_b))
print("Found directly:", len(key_b & master_keys))
