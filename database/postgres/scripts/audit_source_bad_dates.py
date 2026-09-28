from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

silver_file = (
    ROOT
    / "dataset"
    / "silver"
    / "project_monitoring_2025-26_clean.csv"
)

df = pd.read_csv(silver_file)

print("=" * 70)
print("SILVER DATE AUDIT")
print("=" * 70)

print("Rows:", len(df))

date_cols = [
    "doc_original",
    "doc_revised",
    "doc_anticipated",
]

for col in date_cols:
    print(f"\n--- {col} ---")

    s = pd.to_datetime(df[col], errors="coerce")

    print("Non-null:", s.notna().sum())
    print("Min:", s.min())
    print("Max:", s.max())

    bad = (
        s.notna()
        & (
            (s.dt.year < 1900)
            | (s.dt.year > 2100)
        )
    )

    print("Out-of-range:", bad.sum())

    if bad.any():
        print("\nSample bad values:")
        print(
            df.loc[
                bad,
                [
                    "project_id",
                    "project_name",
                    "report_date",
                    col,
                    "source_file",
                    "page",
                ],
            ]
            .head(20)
            .to_string(index=False)
        )