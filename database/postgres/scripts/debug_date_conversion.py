from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

SILVER_FILE = (
    ROOT
    / "dataset"
    / "silver"
    / "project_monitoring_2025-26_clean.csv"
)

silver = pd.read_csv(SILVER_FILE)

print("=" * 70)
print("DATE CONVERSION DEBUG")
print("=" * 70)

date_columns = [
    "doc_original",
    "doc_revised",
    "doc_anticipated",
]

for column in date_columns:
    print(f"\n{'=' * 70}")
    print(column)
    print("=" * 70)

    # BEFORE conversion
    print("\nBEFORE conversion:")
    print("dtype:", silver[column].dtype)

    print(
        silver[column]
        .dropna()
        .head(10)
        .to_list()
    )

    # Perform EXACT conversion used by loader
    converted = pd.to_datetime(
        silver[column],
        errors="coerce",
    ).dt.date

    print("\nAFTER conversion:")
    print("dtype:", converted.dtype)

    print(
        converted
        .dropna()
        .head(10)
        .to_list()
    )

    # Check suspicious years
    bad = converted[
        converted.notna()
        & (
            converted.map(lambda x: x.year < 1900 or x.year > 2100)
        )
    ]

    print("\nOut-of-range AFTER conversion:", len(bad))

    if len(bad):
        print(
            pd.DataFrame(
                {
                    "original": silver.loc[bad.index, column],
                    "converted": bad,
                }
            )
            .head(20)
            .to_string(index=False)
        )