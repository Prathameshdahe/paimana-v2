"""
Clean the three PAIMANA portal exports in the Dataset folder root
(Projects_Report.csv, Sector-Wise-Report.csv, State-Wise-Report.csv)
into dataset/clean/portal/.

Portal quirks handled:
- each file starts with a title line and a blank line; the summary files
  have no header row.
- summary cost cells read "original (latest)", where latest = revised cost
  if the project was revised, else original.
- in the project list a revised cost of 0 means "not revised"; it becomes
  blank here, and cost_latest_cr falls back to the original cost.

A newer project-list export on its own (the live report watcher,
backend/live/watcher.py) replaces portal_projects.csv only; the two summary
files stay those of the last full export:
  python pipeline/extract/portal_csv.py --projects <path to Projects_Report.csv>
"""
import re
import sys
from pathlib import Path

import pandas as pd

from common import DATASET, ROOT

OUT = ROOT / "dataset" / "clean" / "portal"


def months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def projects(src=DATASET / "Projects_Report.csv"):
    d = pd.read_csv(src, skiprows=2)
    d.columns = ["sr_no", "sector", "ministry", "agency", "project_code", "project_name",
                 "cost_original_cr", "cost_revised_cr", "expenditure_cum_cr",
                 "physical_progress_pct", "doc_original", "doc_revised", "sanction_date"]
    for c in ["sector", "ministry", "agency", "project_name"]:
        d[c] = d[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    d["cost_revised_cr"] = d["cost_revised_cr"].where(d["cost_revised_cr"] > 0)
    dates = {}
    for c in ["doc_original", "doc_revised", "sanction_date"]:
        dates[c] = pd.to_datetime(d[c], format="%d/%m/%Y", errors="raise")
        d[c] = dates[c].dt.strftime("%Y-%m-%d")
    d["cost_latest_cr"] = d["cost_revised_cr"].fillna(d["cost_original_cr"])
    d["cost_overrun_cr"] = (d["cost_latest_cr"] - d["cost_original_cr"]).round(2)
    d["cost_overrun_pct"] = (d["cost_overrun_cr"] / d["cost_original_cr"] * 100).round(2)
    d["financial_progress_pct"] = (d["expenditure_cum_cr"] / d["cost_latest_cr"] * 100).round(2)
    d["delay_months"] = [
        months_between(o, r) if pd.notna(r) else None
        for o, r in zip(dates["doc_original"], dates["doc_revised"])
    ]
    d["delay_months"] = d["delay_months"].astype("Int64")
    # Values are kept as reported; implausible ones are flagged, not fixed.
    ratio = d["cost_revised_cr"] / d["cost_original_cr"]
    flags = {
        "revised_cost_implausible": (ratio < 0.2) | (ratio > 10),
        "expenditure_over_150pct_of_cost": d["financial_progress_pct"] > 150,
        "revised_doc_before_original": d["delay_months"].fillna(0) < 0,
        "no_sanction_date": d["sanction_date"].isna(),
    }
    d["dq_flags"] = [";".join(k for k, m in flags.items() if m.iloc[i]) for i in range(len(d))]
    return d.drop(columns="sr_no")


PAIR = re.compile(r"^\s*([\d.]+)\s*\(\s*([\d.]+)\s*\)\s*$")


def summary(fname, dim):
    d = pd.read_csv(DATASET / fname, skiprows=2, header=None,
                    names=["rank", dim, "n_projects", "cost_pair", "expenditure_cr"])
    pairs = d["cost_pair"].str.extract(PAIR).astype(float)
    assert pairs.notna().all().all(), f"{fname}: unparsed cost pair"
    d["cost_original_cr"], d["cost_latest_cr"] = pairs[0], pairs[1]
    return d.drop(columns="cost_pair")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    OUT.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ["--projects"]:
        p = projects(Path(argv[1]))
        assert not p["project_code"].duplicated().any()
        p.to_csv(OUT / "portal_projects.csv", index=False, encoding="utf-8")
        print(f"projects {len(p)} -> {OUT / 'portal_projects.csv'} (summaries unchanged)")
        return
    p = projects()
    sec = summary("Sector-Wise-Report.csv", "sector")
    st = summary("State-Wise-Report.csv", "state")

    # The sector file is an exact rollup of the project list; fail loudly if not.
    g = p.groupby("sector").agg(n=("project_code", "size"), exp=("expenditure_cum_cr", "sum"),
                                latest=("cost_latest_cr", "sum"))
    chk = sec.set_index("sector").join(g)
    assert (chk["n"] == chk["n_projects"]).all(), "sector counts disagree with project list"
    assert ((chk["exp"] - chk["expenditure_cr"]).abs() < 1).all(), "sector expenditure disagrees"
    assert ((chk["latest"] - chk["cost_latest_cr"]).abs() < 5).all(), "sector latest cost disagrees"
    assert not p["project_code"].duplicated().any()

    p.to_csv(OUT / "portal_projects.csv", index=False, encoding="utf-8")
    sec.to_csv(OUT / "portal_sector_summary.csv", index=False, encoding="utf-8")
    st.to_csv(OUT / "portal_state_summary.csv", index=False, encoding="utf-8")
    print(f"projects {len(p)}, sectors {len(sec)}, states {len(st)} -> {OUT}")


if __name__ == "__main__":
    main()
