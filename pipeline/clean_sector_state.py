"""
Silver-layer sector/state/project_type cleaner. Bronze CSVs untouched.

Tiered fix, best evidence first:
  1. PDF word-position extraction (extract_pdf_context.py output) — real
     ground truth where we have the source PDF (2024-25 all 4 quarters,
     partial 2025-26)
  2. majority vote of the raw column per project_id within a fiscal year —
     helps where PDF coverage is missing and the raw signal isn't total noise
  3. regex tag from project_name — sector + project_type, works for any row,
     never used for state (name rarely mentions state)
  4. raw column value, last resort

Run extract_pdf_context.py first; this script reads its output from
dataset/silver/pdf_sector_state_fix.csv.
"""
import pandas as pd
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "dataset" / "raw" / "csv"
OUT_DIR = ROOT / "dataset" / "silver"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_FIX = pd.read_csv(OUT_DIR / "pdf_sector_state_fix.csv", dtype=str)[
    ["project_id", "sector_pdf", "state_pdf"]
]

SECTOR_RULES = [
    (r"\bAIRPORT\b", "CIVIL AVIATION"),
    (r"\bSOLAR\b|\bMW\b|THERMAL|HYDRO|TRANSMISSION|SUBSTATION|\bTPP\b|\bSTPP\b|POWER (GRID|PLANT|PROJECT|STATION)", "POWER"),
    (r"\bNH-?\s?\d|LANING|HIGHWAY|EXPRESSWAY|\bNH\b|FLYOVER|BYPASS", "ROAD TRANSPORT AND HIGHWAYS"),
    (r"RAILWAY|DOUBLING|GAUGE|\bRAIL\b|METRO|ELECTRIFICATION OF.*LINE|\bRRTS\b", "RAILWAYS"),
    (r"ATOMIC|NUCLEAR", "ATOMIC ENERGY"),
    (r"REFINERY|PIPELINE|\bLNG\b|PETROCHEM|\bLPG\b|CRUDE OIL|NATURAL GAS|GAS DISTRIBUTION", "PETROLEUM"),
    (r"\bCOAL\b|WASHERY|\bOCP\b|COALFIELD", "COAL"),
    (r"\bPORT\b|BERTH|JETTY|\bHARBOUR\b", "SHIPPING AND PORTS"),
    (r"\bSTEEL\b|STEEL PLANT", "STEEL"),
    (r"\bAIIMS\b|HOSPITAL|MEDICAL COLLEGE|MEDICAL SCIENCE", "HEALTH AND FAMILY WELFARE"),
    (r"\bIIT\b|\bNIT\b|\bIIM\b|\bIISER\b|UNIVERSITY|CENTRAL SCHOOL|CAMPUS OF", "DEPARTMENT OF HIGHER EDUCATION"),
    (r"METRO RAIL|SEWERAGE|WATER SUPPLY SCHEME|URBAN INFRA", "URBAN DEVELOPMENT"),
    (r"\bMINE\b|\bMINING\b|IRON ORE", "MINES"),
    (r"IRRIGATION|BARRAGE|\bDAM\b|CANAL PROJECT|RIVER LINKING", "WATER RESOURCES"),
]

TYPE_RULES = [
    (r"\bDOUBLING\b", "doubling"),
    (r"GAUGE CONVERSION", "gauge_conversion"),
    (r"ELECTRIFICATION", "electrification"),
    (r"\b\d\s?-?\s?LAN(E|ING)\b|WIDENING", "widening_laning"),
    (r"NEW (LINE|LINK|CONSTRUCTION|AIRPORT|TERMINAL)|CONSTRUCTION OF", "new_construction"),
    (r"UP-?GRADATION|REHABILITATION|STRENGTHENING|REVAMPING|MODERNI[SZ]ATION", "upgradation_rehab"),
    (r"\bBRIDGE\b|FLYOVER|ROB\b", "bridge_flyover"),
    (r"\bTUNNEL\b", "tunnel"),
    (r"EXPANSION|AUGMENTATION|CAPACITY EXPANSION", "expansion"),
    (r"BYPASS", "bypass"),
]


def tag(name, rules):
    n = name.upper()
    for pat, label in rules:
        if re.search(pat, n):
            return label
    return None


def contra_rate(d, seccol):
    n = c = 0
    for nm, sec in zip(d["project_name"].str.upper(), d[seccol].astype(str).str.upper()):
        exp = tag(nm, SECTOR_RULES)
        if exp:
            n += 1
            if exp.split()[0] not in sec:
                c += 1
    return n, c


def mode_nonblank(s):
    s = s[s != ""]
    return s.mode().iloc[0] if not s.empty else ""


def clean_file(fy_file):
    d = pd.read_csv(CSV_DIR / fy_file, dtype=str, keep_default_na=False)
    d["sector"] = d["sector"].str.strip()
    d["state"] = d["state"].str.strip()
    n0, c0 = contra_rate(d, "sector")

    d = d.merge(PDF_FIX, on="project_id", how="left")

    sector_vote = d.groupby("project_id")["sector"].transform(mode_nonblank)
    state_vote = d.groupby("project_id")["state"].transform(mode_nonblank)
    agency_vote = d.groupby("project_id")["agency"].transform(mode_nonblank)
    sector_tag = d["project_name"].map(lambda n: tag(n, SECTOR_RULES) or "")

    # agency has the same page-header-bleed bug as sector/state (e.g. a state
    # name landing in the agency cell) — same majority-vote fix
    d["agency_clean"] = agency_vote.where(agency_vote != "", d["agency"])

    d["sector_clean"] = d["sector_pdf"]
    d["sector_clean"] = d["sector_clean"].where(d["sector_clean"].notna(), sector_vote.replace("", pd.NA))
    d["sector_clean"] = d["sector_clean"].where(d["sector_clean"].notna(), sector_tag.replace("", pd.NA))
    d["sector_clean"] = d["sector_clean"].fillna(d["sector"])

    d["state_clean"] = d["state_pdf"]
    d["state_clean"] = d["state_clean"].where(d["state_clean"].notna(), state_vote.replace("", pd.NA))
    d["state_clean"] = d["state_clean"].fillna(d["state"])

    # provenance tier, for the frontend's data-confidence badge
    import numpy as np

    d["sector_source"] = np.select(
        [d["sector_pdf"].notna(), sector_vote != "", sector_tag != ""],
        ["pdf_reparse", "cross_period_vote", "name_keyword_rule"],
        default="original_extraction",
    )
    d["state_source"] = np.select(
        [d["state_pdf"].notna(), state_vote != ""],
        ["pdf_reparse", "cross_period_vote"],
        default="original_extraction",
    )

    d["project_type"] = d["project_name"].map(lambda n: tag(n, TYPE_RULES) or "unspecified")

    n1, c1 = contra_rate(d, "sector_clean")
    print(f"{fy_file}: rows={len(d)} sector contradiction ORIG {c0}/{n0} ({100*c0/max(n0,1):.0f}%)"
          f"  ->  CLEAN {c1}/{n1} ({100*c1/max(n1,1):.0f}%)")
    print(f"  sector_clean blank: {(d['sector_clean']=='').mean()*100:.0f}%"
          f"  state_clean blank: {(d['state_clean']=='').mean()*100:.0f}%"
          f"  project_type unspecified: {(d['project_type']=='unspecified').mean()*100:.0f}%")

    keep = ["report_date","report_type","fiscal_year","project_id","project_name",
            "sector_clean","state_clean","sector_source","state_source","project_type",
            "agency_clean","cost_original","cost_revised",
            "cost_anticipated","cost_overrun","cost_overrun_pct","cumulative_expenditure",
            "doc_original","doc_revised","doc_anticipated","delay_months","physical_progress",
            "source_file","page"]
    out = OUT_DIR / f"{fy_file.replace('.csv','')}_clean.csv"
    d[keep].rename(columns={"sector_clean": "sector", "state_clean": "state", "agency_clean": "agency"}).to_csv(out, index=False)
    print("  wrote", out)
    return d


if __name__ == "__main__":
    for f in ["project_monitoring_2024-25.csv", "project_monitoring_2025-26.csv", "project_monitoring_2026-27.csv"]:
        clean_file(f)
