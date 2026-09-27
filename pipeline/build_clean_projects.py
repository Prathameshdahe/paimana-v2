"""
Merge the project-report part files (dataset/clean/_parts/proj_*/) into the
analysis-ready project layer under dataset/clean/.

Run from repo root:  python pipeline/build_clean_projects.py

Inputs
  _parts/proj_*/{projects,summary,manifest}.csv  (7 families, via common.write_part)
  _parts/perf_*/manifest.csv                     (source_manifest only)
  portal/portal_projects.csv                     (latest PAIMANA portal snapshot)

Outputs
  reference/sector_map.csv            (era, sector_raw, ministry) -> harmonised sector
  reference/state_map.csv             raw state string -> canonical 2026 State/UT or special value
  reference/project_id_crosswalk.csv  one row per identifier link, applied or rejected (with reason)
  reference/source_manifest.csv       every family manifest + report_family, fiscal_year, flags
  projects/projects_monthly.csv       monthly_flash + paimana_flash project rows
  projects/projects_quarterly.csv     quarterly_qpisr project rows
  projects/project_summaries.csv      printed summary tables + harmonised sector / canonical state
  projects/project_sector_period.csv  computed from the ongoing lists per report x sector
  projects/project_state_period.csv   same per single canonical state
  projects/project_period_overview.csv one row per report
  projects/project_master.csv         one row per project_key

Rules
* Printed columns are never overwritten; derived columns are added. Blank = unknown.
* Sector. OCMS-era labels (2005 .. Jun 2025) map by label. PAIMANA-era rows
  (parser_variant paimana_*) print an HML-2022 sector plus the ministry; the
  OCMS era classified every project by its ministry (checked on the projects
  linked across the two eras: Coal-sector projects of the Ministry of Power were
  POWER, Electricity Generation of the Ministry of Coal was COAL, Waste & Water
  of DoWR was WATER RESOURCES, ...). So a PAIMANA row takes the sector of its
  ministry when the ministry has one in the harmonised vocabulary, else the
  default of its HML sector; sector_hml keeps the HML label. HML labels that
  need a ministry (Construction, Energy Storage, Real Estate) and have none
  (sector-only summary tables) -> 'Unknown'.
* cost_latest_cr = anticipated if printed, else revised, else original
  (cost_latest_basis says which). time_overrun_months_computed =
  (doc_anticipated or doc_revised) - doc_original in months.
  financial_progress_pct = expenditure_cum_cr / cost_latest_cr * 100.
* Project identity (project_key). Printed codes: OCMS 'N' + 8 digits or 9
  digits (an 8-digit alt code lost its leading zero and is padded), PAIMANA 6
  digits, PMG ids (alt only). Keys are system-prefixed. Links are union-found;
  a union is refused if the result would hold two OCMS or two PAIMANA codes or
  would put two rows of the same list of the same report into one project.
  - printed alt codes PAIMANA<->OCMS are applied only when corroborated by the
    OCMS-era rows of that code (exact cost match, or cost within 1% and some
    name overlap, or name-token Jaccard >= 0.25) and one-to-one: the source
    prints many wrong / package-split alt codes (e.g. four NH packages -> one
    OCMS code, off-by-one codes in Feb-May 2026).
  - PAIMANA<->PMG links are applied when one-to-one (no PMG-keyed data exists
    to corroborate them; the crosswalk says so).
  - rows without a code link by exact name (alnum only) + harmonised sector to
    rows of the same report stream in the same, previous or next full report,
    and only when the name is unique in every list involved and the agencies
    (when both printed) agree. Code-less chains get NAME:<hash> keys; a chain
    whose names match rows of exactly one coded project joins that project.
* dq_flags (row level) come from the report's manifest entry: report_partial,
  report_truncated, stale_repeat_of:<period> (ongoing rows), scope_excludes:MoRTH,
  period_mismatch_cover, source_railways_data_as_of:2015-01 (Railways rows),
  source_nhai_data_incomplete (Roads rows).
"""
import hashlib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "extract"))
from common import MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS, fiscal_year  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "dataset" / "clean" / "_parts"
CLEAN = ROOT / "dataset" / "clean"
OUT_P = CLEAN / "projects"
OUT_R = CLEAN / "reference"

PROJ_FAMILIES = ["proj_monthly_2005_10", "proj_monthly_2010_13", "proj_monthly_2013_16",
                 "proj_quarterly_2014_18", "proj_qpsir_2021_24", "proj_qpisr_2024_26",
                 "proj_flash_2025_27"]
PERF_FAMILIES = ["perf_2015_18", "perf_2018_21", "perf_2025_26"]
REPORT_FAMILIES = {"performance_review", "monthly_flash", "quarterly_qpisr", "paimana_flash"}

# ----------------------------------------------------------------------------- vocabularies

def compact(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper().replace("&", "AND"))


def label_norm(s):
    """Readable normalised label: upper, & -> AND, punctuation -> space, trailing page no. cut."""
    t = re.sub(r"[^A-Z0-9]+", " ", str(s).upper().replace("&", " AND "))
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"(\s\d+)+$", "", t)


OCMS_SECTORS = {  # OCMS-era sector label (label_norm) -> harmonised sector
    "ATOMIC ENERGY": "Atomic Energy",
    "CIVIL AVIATION": "Civil Aviation",
    "COAL": "Coal",
    "COMMERCE": "Industry & Commerce",
    "CULTURE DEVELOPMENT": "Tourism & Culture",
    "DEFENCE PRODUCTION": "Defence",
    "DEPARTMENT OF HIGHER EDUCATION": "Education",
    "DONER": "North Eastern Region",
    "DPIIT": "Industry & Commerce",
    "FERTILISERS": "Fertilizers & Chemicals",
    "FERTILIZERS": "Fertilizers & Chemicals",
    "FINANCE": "Finance",
    "HEALTH AND FAMILY WELFARE": "Health",
    "HEALTH AND FW": "Health",
    "HEAVY INDUSTRY": "Industry & Commerce",
    "HEAVY INDUSTRIES": "Industry & Commerce",
    "HOME AFFAIRS": "Home Affairs",
    "INFORMATION AND BROADCASTING": "Other",
    "INFORMATION TECHNOLOGY": "Other",
    "MINE": "Mines & Metals",
    "MINES": "Mines & Metals",
    "PETROCHEMICALS": "Fertilizers & Chemicals",
    "PETROLEUM": "Petroleum & Natural Gas",
    "POWER": "Power",
    "RAILWAYS": "Railways",
    "RENEWABLE ENERGY": "Power",
    "ROAD TRANSPORT AND HIGHWAYS": "Roads & Highways",
    "RURAL DEVELOPMENT": "Rural Development",
    "SHIPPING AND PORTS": "Shipping & Ports",
    "SOCIAL JUSTICE": "Social Justice",
    "STEEL": "Steel",
    "TELECOMMUNICATION": "Telecommunications",
    "TELECOMMUNICATIONS": "Telecommunications",
    "URBAN DEVELOPMENT": "Urban Development & Housing",
    "WATER RESOURCES": "Water Resources",
}
TRUNCATED_SECTORS = {  # label cut short by a narrow column -> full label
    "ROAD TRANSPORT AND": "ROAD TRANSPORT AND HIGHWAYS",
    "HEALTH AND FAMILY": "HEALTH AND FAMILY WELFARE",
    "DEPARTMENT OF HIGHER": "DEPARTMENT OF HIGHER EDUCATION",
    # QPSIR 2024-03 Annex 2 prints 'Department of' in the row where Annex 1 prints
    # 'Department of Higher'; it is the only 'Department of ..' sector in that vocabulary.
    "DEPARTMENT OF": "DEPARTMENT OF HIGHER EDUCATION",
    "FINANC": "FINANCE",
}
JUNK_SECTORS = {"DUMMY SECTOR", "MOBILE SECTOR"}  # OCMS placeholder categories, 0 projects

HML_SECTORS = {  # PAIMANA / HML 2022 sector -> default harmonised sector (None = needs ministry)
    "Aviation & Aviation Infrastructure": "Civil Aviation",
    "Coal": "Coal",
    "Construction": None,
    "Education": "Education",
    "Electricity Generation": "Power",
    "Energy Storage": None,
    "Healthcare": "Health",
    "Inland Waterways": "Shipping & Ports",
    "Logistics Infrastructure": "Industry & Commerce",
    "Metals & Mining": "Mines & Metals",
    "Oil & Gas": "Petroleum & Natural Gas",
    "Railways": "Railways",
    "Real Estate": None,
    "Roads & Highways": "Roads & Highways",
    "Shipping": "Shipping & Ports",
    "Steel": "Steel",
    "Telecommunication": "Telecommunications",
    "Tourism, Hospitality & Wellness": "Tourism & Culture",
    "Transmission & Distribution": "Power",
    "Urban Public Transport": "Urban Development & Housing",
    "Waste & Water": "Urban Development & Housing",
    "Water Resources": "Water Resources",
}
HML_BY_COMPACT = {compact(k): k for k in HML_SECTORS}

MINISTRY_SECTOR = {  # ministry as printed in PAIMANA reports -> harmonised sector (None = use HML)
    "Department for Promotion of Industry & Internal Trade": "Industry & Commerce",
    "Department of Higher Education": "Education",
    "Department of Sports": None,
    "Department of Telecommunications": "Telecommunications",
    "Department of Water Resources, River Development & GR": "Water Resources",
    "Ministry of Civil Aviation": "Civil Aviation",
    "Ministry of Coal": "Coal",
    "Ministry of Health & Family Welfare": "Health",
    "Ministry of Housing & Urban Affairs": "Urban Development & Housing",
    "Ministry of Labour and Employment": None,   # ESIC hospitals: OCMS era had them under HEALTH
    "Ministry of Mines": "Mines & Metals",
    "Ministry of Petroleum & Natural Gas": "Petroleum & Natural Gas",
    "Ministry of Ports, Shipping and Waterways": "Shipping & Ports",
    "Ministry of Power": "Power",
    "Ministry of Railways": "Railways",
    "Ministry of Road Transport & Highways": "Roads & Highways",
    "Ministry of Steel": "Steel",
}
SECTORS = {"Roads & Highways", "Railways", "Power", "Petroleum & Natural Gas", "Coal", "Steel",
           "Mines & Metals", "Telecommunications", "Civil Aviation", "Shipping & Ports",
           "Urban Development & Housing", "Water Resources", "Atomic Energy", "Health", "Education",
           "Fertilizers & Chemicals", "Industry & Commerce", "Home Affairs", "Defence", "Finance",
           "Rural Development", "Social Justice", "North Eastern Region", "Tourism & Culture",
           "Other", "Unknown"}
assert set(OCMS_SECTORS.values()) <= SECTORS
assert {v for v in HML_SECTORS.values() if v} <= SECTORS
assert {v for v in MINISTRY_SECTOR.values() if v} <= SECTORS


def map_sector(era, raw, ministry):
    """-> (sector_raw_norm, sector, sector_hml, rule, note)"""
    raw = str(raw).strip()
    if era == "hml":
        hml = HML_BY_COMPACT.get(compact(raw))
        if hml is None and raw:
            n, s, _, r, note = map_sector("ocms", raw, "")
            return n, s, "", r, (note + "; " if note else "") + "OCMS label in a PAIMANA-era report"
        default = HML_SECTORS.get(hml) if hml else None
        msec = MINISTRY_SECTOR.get(ministry)
        norm = label_norm(hml) if hml else ""
        if msec and not raw:
            return "", msec, "", "ministry", "ministry-level summary row"
        if msec:
            note = "" if msec == default else (
                f"HML '{hml or '(none)'}' under {ministry}: sector follows the ministry "
                "(OCMS-era classification)")
            return norm, msec, hml or "", "ministry" if note else "sector_raw", note
        if default:
            return norm, default, hml, "sector_raw", ""
        if not hml:
            what = f"ministry {ministry!r} has no harmonised sector" if ministry else "blank label"
            return norm, "Unknown", "", "unmapped", what
        return norm, "Unknown", hml, "unmapped", (
            f"HML '{hml}' spans ministries and no mapped ministry is printed")
    norm = label_norm(raw)
    if not norm:
        return "", "Unknown", "", "junk", "blank label"
    if norm not in OCMS_SECTORS:  # split words ('TELECOMMUNICATI ONS')
        hit = [k for k in list(OCMS_SECTORS) + list(TRUNCATED_SECTORS) if compact(k) == compact(norm)]
        if hit:
            norm = hit[0]
    if norm in TRUNCATED_SECTORS:
        full = TRUNCATED_SECTORS[norm]
        return full, OCMS_SECTORS[full], "", "sector_raw", f"truncated label '{raw}'"
    if norm in OCMS_SECTORS:
        return norm, OCMS_SECTORS[norm], "", "sector_raw", ""
    if norm in JUNK_SECTORS:
        return norm, "Unknown", "", "junk", "OCMS placeholder category (0 projects)"
    return norm, "Unknown", "", "junk", "unrecognised label"


STATES = ["Andaman & Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
          "Chandigarh", "Chhattisgarh", "Dadra & Nagar Haveli and Daman & Diu", "Delhi", "Goa",
          "Gujarat", "Haryana", "Himachal Pradesh", "Jammu & Kashmir", "Jharkhand", "Karnataka",
          "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
          "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
          "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"]
STATE_BY_COMPACT = {compact(s): s for s in STATES}
STATE_BY_COMPACT.update({compact(k): v for k, v in {
    "Orissa": "Odisha", "Uttaranchal": "Uttarakhand", "Chhatisgarh": "Chhattisgarh",
    "Jharkhandd": "Jharkhand", "Himachal Pr.": "Himachal Pradesh",
    "Arunachal Pr.": "Arunachal Pradesh", "J & K": "Jammu & Kashmir", "J and K": "Jammu & Kashmir",
    "Andaman & Nicobar": "Andaman & Nicobar Islands", "A & N Islands": "Andaman & Nicobar Islands",
    "D & N Haveli": "Dadra & Nagar Haveli and Daman & Diu",
    "Dadra & Nagar Haveli": "Dadra & Nagar Haveli and Daman & Diu",
    "Daman & Diu": "Dadra & Nagar Haveli and Daman & Diu",
    "Pondicherry": "Puducherry", "NCT of Delhi": "Delhi", "New Delhi": "Delhi",
}.items()})
STATE_SPECIAL = {"MULTISTATE": "Multi-State", "MULTISTATES": "Multi-State", "PANINDIA": "PAN India",
                 "OFFSHORE": "Offshore", "ABROAD": "Abroad", "NOTSPECIFIED": "Not Specified"}
SPECIAL_STATES = set(STATE_SPECIAL.values())


def map_state(raw):
    """-> (state, state_list, note); state '' only for a blank raw value."""
    raw = str(raw).strip()
    c = compact(raw)
    if not c:
        return "", "", ""
    if c in STATE_BY_COMPACT:
        s = STATE_BY_COMPACT[c]
        return s, "", "" if raw.upper() == s.upper() else "alias"
    if c in STATE_SPECIAL:
        return STATE_SPECIAL[c], "", ""
    m = re.fullmatch(r"MULTI[\s-]*STATES?\s*\((.*)\)", raw.upper().strip())
    parts = [p for p in re.split(r",", m[1] if m else raw) if p.strip()]
    canon = [STATE_BY_COMPACT.get(compact(p)) for p in parts]
    if len(parts) > 1 and all(canon):
        return "Multi-State", ";".join(sorted(set(canon))), ""
    if re.search(r"offshore|pan india", raw, re.I):
        return "Not Specified", "", "combined label (Offshore / PAN India rows)"
    if re.search(r"not printed", raw, re.I):
        return "Not Specified", "", "state not printed in the source"
    return "Not Specified", "", "unrecognised state string"


def is_total(v):
    return bool(re.fullmatch(r"\s*((grand|sub)[\s-]*)?total\s*", str(v), re.I))


# ----------------------------------------------------------------------------- helpers

def num(s):
    return pd.to_numeric(s.replace("", np.nan), errors="coerce")


def ym_index(s):
    """'YYYY-MM[-DD]' -> months since year 0 (float, NaN if blank)."""
    s = s.astype(str)
    y = pd.to_numeric(s.str[:4], errors="coerce")
    m = pd.to_numeric(s.str[5:7], errors="coerce")
    return y * 12 + m


def fy(p):
    return fiscal_year(p) if re.fullmatch(r"\d{4}-\d{2}", str(p)) else ""


def join_flags(*lists):
    out = []
    for lst in lists:
        for f in lst:
            if f and f not in out:
                out.append(f)
    return ";".join(out)


def read_part(fam, name, cols):
    d = pd.read_csv(PARTS / fam / f"{name}.csv", dtype=str, keep_default_na=False)
    extra = set(d.columns) - set(cols)
    assert not extra, f"{fam}/{name}: unexpected columns {extra}"
    for c in cols:  # families not yet re-run on the extended schema lack the new columns
        if c not in d:
            d[c] = ""
    d = d[cols].copy()
    d["family"] = fam
    return d


def write(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == bool:
            df[c] = df[c].map({True: "true", False: "false"})
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    print(f"  {path.relative_to(ROOT).as_posix()}: {len(df)} rows")


def norm_code(code, system=None):
    """Printed id -> 'SYSTEM:ID' or None."""
    c = str(code).strip().upper()
    if not c:
        return None
    if system == "PMG":
        return f"PMG:{c}" if re.fullmatch(r"\d+", c) else None
    if re.fullmatch(r"N\d{8}|\d{9}", c):
        return f"OCMS:{c}"
    if re.fullmatch(r"\d{8}", c) and system == "OCMS":
        return f"OCMS:{c.zfill(9)}"       # alt code printed without its leading zero
    if re.fullmatch(r"\d{6}", c) and system in (None, "PAIMANA"):
        return f"PAIMANA:{c}"
    return None


SYS_RANK = {"OCMS": 0, "PAIMANA": 1, "PMG": 2}


def code_sort(k):
    return (SYS_RANK.get(k.split(":")[0], 9), k)


STOP = {"OF", "THE", "AND", "IN", "AT", "TO", "FOR", "FROM", "KM", "NH", "PROJECT", "ON", "WITH",
        "A", "BY", "UNDER", "MODE", "STATE", "EPC", "LANE", "LANES", "LANING", "SECTION", "PKG",
        "PACKAGE", "CONSTRUCTION", "WIDENING", "ROAD", "OLD", "NEW", "DESIGN", "CH", "EXISTING",
        "PAVED", "SHOULDER", "SHOULDERS", "WORK", "WORKS", "IMPROVEMENT", "UPGRADATION", "OF"}


def tokens(s):
    return set(re.findall(r"[A-Z0-9]+", str(s).upper())) - STOP


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


class Components:
    """Union-find over identifier nodes. A union is refused when the merged
    component would hold two different OCMS or PAIMANA codes, or two rows of
    the same list of the same report (slot)."""

    def __init__(self):
        self.parent, self.slots, self.codes = {}, {}, {}

    def add(self, node, slots=(), code=None):
        if node not in self.parent:
            self.parent[node], self.slots[node], self.codes[node] = node, set(), set()
        self.slots[self.find(node)].update(slots)
        if code:
            self.codes[self.find(node)].add(code)

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def conflict(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return None
        if self.slots[ra] & self.slots[rb]:
            return "same_report_list_overlap"
        for sys_ in ("OCMS", "PAIMANA"):
            ca = {c for c in self.codes[ra] if c.startswith(sys_ + ":")}
            cb = {c for c in self.codes[rb] if c.startswith(sys_ + ":")}
            if ca and cb and ca != cb:
                return f"conflicting_{sys_}_codes"
        return None

    def union(self, a, b):
        why = self.conflict(a, b)
        if why:
            return why
        ra, rb = sorted((self.find(a), self.find(b)))
        if ra != rb:
            self.parent[rb] = ra
            self.slots[ra] |= self.slots.pop(rb)
            self.codes[ra] |= self.codes.pop(rb)
        return None


# ----------------------------------------------------------------------------- load

def load():
    proj = pd.concat([read_part(f, "projects", PROJECT_COLS) for f in PROJ_FAMILIES], ignore_index=True)
    summ = pd.concat([read_part(f, "summary", SUMMARY_COLS) for f in PROJ_FAMILIES], ignore_index=True)
    man = pd.concat([read_part(f, "manifest", MANIFEST_COLS) for f in PERF_FAMILIES + PROJ_FAMILIES],
                    ignore_index=True)
    portal = pd.read_csv(CLEAN / "portal" / "portal_projects.csv", dtype=str, keep_default_na=False)
    return proj, summ, man, portal


def manifest_flags(m):
    """Report-level flags from one manifest row."""
    n, f = m["notes"], []
    if m["status"] == "partial":
        f.append("report_partial")
    elif m["status"].startswith("skipped"):
        f.append(m["status"])
    if re.search(r"PDF is truncated", n):
        f.append("report_truncated")
    for p in re.findall(r"i\.e\. (\d{4}-\d{2}) figures reprinted", n):
        f.append(f"stale_repeat_of:{p}")
    if re.search(r"excluding Ministry of Road Transport", n):
        f.append("scope_excludes:MoRTH")
    if re.search(r"transcribed", n) or "transcribed" in m["parser_variant"]:
        f.append("transcribed_from_image")
    if re.search(r"image-only pages", n):
        f.append("image_pages_not_extracted")
    if re.search(r"period check vs file name", n):
        f.append("period_mismatch_cover")
    if re.search(r"Railways is as on 01\.01\.2015|January 2015\) has been used in respect of all "
                 r"projects of Railways", n):
        f.append("source_railways_data_as_of:2015-01")
    if re.search(r"NHAI", n):
        f.append("source_nhai_data_incomplete")
    dup = re.search(r"(?:duplicate of|copy of) (.+?\.pdf)", n)
    if dup:
        f.append(f"duplicate_of:{dup[1]}")
    return f


# ----------------------------------------------------------------------------- main build

def build():
    proj, summ, man, portal = load()
    n_proj_in, n_summ_in, n_man_in = len(proj), len(summ), len(man)
    print(f"inputs: {n_proj_in} project rows, {n_summ_in} summary rows, {n_man_in} manifest rows")

    # ---- manifest / report flags
    man["report_family"] = man["report_type"]
    assert set(man["report_family"]) <= REPORT_FAMILIES, set(man["report_family"])
    man["fiscal_year"] = man["report_period"].map(fy)
    man["_flags"] = man.apply(manifest_flags, axis=1)
    man["data_quality_flags"] = man["_flags"].map(lambda f: ";".join(f))
    src_flags = dict(zip(man["source_file"], man["_flags"]))
    src_era = {s: ("hml" if v.startswith("paimana") else "ocms")
               for s, v in zip(man["source_file"], man["parser_variant"])}
    for d in (proj, summ):
        missing = set(d["source_file"]) - set(src_flags)
        assert not missing, f"source files without a manifest row: {sorted(missing)[:5]}"

    # ---- sector map (projects + sector-like summary rows)
    proj["_era"] = proj["source_file"].map(src_era)
    proj["_ministry_key"] = np.where(proj["_era"] == "hml", proj["ministry"], "")
    summ["_era"] = summ["source_file"].map(src_era)
    dim, dv, sdv = summ["dimension"], summ["dimension_value"], summ["sub_dimension_value"]
    parts = sdv.str.split(r" \| ")
    s_raw = pd.Series("", index=summ.index)
    s_min = pd.Series("", index=summ.index)
    s_like = pd.Series(False, index=summ.index)
    m = dim.eq("sector") & ~dv.map(is_total)
    s_raw[m], s_like[m] = dv[m], True
    m = dim.eq("ministry_sector") & ~sdv.map(is_total)
    s_raw[m], s_min[m], s_like[m] = sdv[m], dv[m], True
    m = dim.eq("state_ministry_sector") & (parts.str.len() >= 2)
    s_raw[m], s_min[m], s_like[m] = parts[m].str[-1], parts[m].str[-2], True
    m = dim.eq("ministry") & ~dv.map(is_total)
    s_min[m], s_like[m] = dv[m], True
    summ["_sector_raw"], summ["_ministry_key"] = s_raw, np.where(summ["_era"] == "hml", s_min, "")

    keys = pd.concat([
        proj[["_era", "sector_raw", "_ministry_key"]].assign(_src="p"),
        summ.loc[s_like, ["_era", "_sector_raw", "_ministry_key"]]
            .rename(columns={"_sector_raw": "sector_raw"}).assign(_src="s"),
    ], ignore_index=True)
    smap = (keys.groupby(["_era", "sector_raw", "_ministry_key"])["_src"]
            .agg(n_project_rows=lambda s: int((s == "p").sum()),
                 n_summary_rows=lambda s: int((s == "s").sum())).reset_index())
    mapped = [map_sector(*t) for t in zip(smap["_era"], smap["sector_raw"], smap["_ministry_key"])]
    smap[["sector_raw_norm", "sector", "sector_hml", "rule", "note"]] = pd.DataFrame(mapped, index=smap.index)
    smap = smap.rename(columns={"_era": "era", "_ministry_key": "ministry"})
    smap = smap[["era", "sector_raw", "ministry", "sector_raw_norm", "sector", "sector_hml", "rule",
                 "note", "n_project_rows", "n_summary_rows"]].sort_values(["era", "sector_raw", "ministry"])
    assert smap["sector"].isin(SECTORS).all()
    sec_lookup = smap.set_index(["era", "sector_raw", "ministry"])[["sector", "sector_hml"]]
    proj = proj.join(sec_lookup, on=["_era", "sector_raw", "_ministry_key"])
    assert proj["sector"].notna().all() and (proj["sector"] != "").all(), "unmapped project sector"
    summ = summ.join(sec_lookup, on=["_era", "_sector_raw", "_ministry_key"])
    summ.loc[~s_like, ["sector", "sector_hml"]] = ""
    summ[["sector", "sector_hml"]] = summ[["sector", "sector_hml"]].fillna("")
    # a ministry-only row with a ministry that has no harmonised sector stays blank, not Unknown
    summ.loc[dim.eq("ministry") & summ["sector"].eq("Unknown"), ["sector", "sector_hml"]] = ""
    assert (summ.loc[s_like & ~dim.eq("ministry"), "sector"] != "").all(), "unmapped summary sector"

    # ---- state map
    st_raw_s = pd.Series("", index=summ.index)
    m = dim.isin(["state", "state_ministry_sector"]) & ~dv.map(is_total)
    st_raw_s[m] = dv[m]
    pan = dim.eq("state_ministry_sector") & dv.eq("") & (parts.str.len() >= 3)
    st_raw_s[pan] = parts[pan].str[0]
    st_like = m
    st_keys = pd.concat([proj["state"].to_frame("state_raw").assign(_src="p"),
                         st_raw_s[st_like].to_frame("state_raw").assign(_src="s")])
    stmap = (st_keys.groupby("state_raw")["_src"]
             .agg(n_project_rows=lambda s: int((s == "p").sum()),
                  n_summary_rows=lambda s: int((s == "s").sum())).reset_index())
    stmap[["state", "state_list", "note"]] = pd.DataFrame(
        [map_state(r) for r in stmap["state_raw"]], index=stmap.index)
    # a blank printed state in a state-wise summary table is 'Not Specified'; in a project row blank
    stmap.loc[stmap["state_raw"].eq("") & (stmap["n_summary_rows"] > 0), "note"] = (
        "blank: project rows stay blank (not printed); summary rows -> Not Specified")
    stmap["state_raw_norm"] = stmap["state_raw"].map(label_norm)
    stmap["is_special"] = stmap["state"].isin(SPECIAL_STATES)
    stmap = stmap[["state_raw", "state_raw_norm", "state", "state_list", "is_special", "note",
                   "n_project_rows", "n_summary_rows"]].sort_values("state_raw")
    st_lookup = stmap.set_index("state_raw")[["state", "state_list"]]
    proj = proj.rename(columns={"state": "state_raw"}).join(st_lookup, on="state_raw")
    summ["state"] = ""
    summ.loc[st_like, "state"] = st_raw_s[st_like].map(st_lookup["state"]).replace("", "Not Specified")
    unmapped_state = stmap[stmap["note"].eq("unrecognised state string")]

    # ---- derived numbers
    c_orig, c_rev, c_ant = num(proj["cost_original_cr"]), num(proj["cost_revised_cr"]), num(proj["cost_anticipated_cr"])
    proj["_c_orig"] = c_orig
    proj["_c_latest"] = c_ant.fillna(c_rev).fillna(c_orig)
    proj["cost_latest_basis"] = np.select([c_ant.notna(), c_rev.notna(), c_orig.notna()],
                                          ["anticipated", "revised", "original"], "")
    doc_later = proj["doc_anticipated"].where(proj["doc_anticipated"] != "", proj["doc_revised"])
    proj["_doc_later"] = doc_later
    proj["_t_over"] = ym_index(doc_later) - ym_index(proj["doc_original"])
    proj["_delay"] = num(proj["delay_months"]).fillna(proj["_t_over"])
    proj["_exp"] = num(proj["expenditure_cum_cr"])
    proj["_phys"] = num(proj["physical_progress_pct"])
    proj["_fin"] = (proj["_exp"] / proj["_c_latest"] * 100).where(proj["_c_latest"] > 0)
    proj["name_norm"] = proj["project_name"].map(lambda s: re.sub(
        r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(s).upper().replace("&", " AND "))).strip())

    # ---- row-level dq_flags
    def row_flags(src, sector, list_type):
        out = []
        for f in src_flags[src]:
            if f.startswith("stale_repeat_of") and list_type != "ongoing":
                continue
            if f == "source_railways_data_as_of:2015-01" and sector != "Railways":
                continue
            if f == "source_nhai_data_incomplete" and sector != "Roads & Highways":
                continue
            if f in ("image_pages_not_extracted",) or f.startswith(("duplicate_of", "skipped")):
                continue
            out.append(f)
        return out

    proj["dq_flags"] = [join_flags(row_flags(s, sec, lt), [f for f in n.split(";") if f.startswith("stale_repeat_of")] if lt == "ongoing" else [])
                        for s, sec, lt, n in zip(proj["source_file"], proj["sector"], proj["list_type"], proj["dq_note"])]
    summ["dq_flags"] = [join_flags([f for f in src_flags[s] if not f.startswith("stale_repeat_of")
                                    and f != "image_pages_not_extracted"
                                    and not (f.startswith("source_railways") and sec not in ("", "Railways"))
                                    and not (f == "source_nhai_data_incomplete" and sec not in ("", "Roads & Highways"))])
                        for s, sec in zip(summ["source_file"], summ["sector"])]

    # ---- identity
    proj, xwalk, link_stats, comp_codes = assign_keys(proj, portal)

    # ---- project rows out
    proj["cost_latest_cr"] = proj["_c_latest"].round(2)
    proj["time_overrun_months_computed"] = proj["_t_over"].astype("Int64")
    proj["financial_progress_pct"] = proj["_fin"].round(2)
    out_cols = [c if c != "state" else "state_raw" for c in PROJECT_COLS] + [
        "family", "project_key", "key_source", "name_norm", "sector", "sector_hml", "state", "state_list",
        "cost_latest_cr", "cost_latest_basis", "time_overrun_months_computed", "financial_progress_pct",
        "dq_flags"]
    proj["_page"] = pd.to_numeric(proj["page"], errors="coerce")
    proj = proj.sort_values(["report_period", "list_type", "sector", "project_key", "report_type",
                             "source_file", "_page", "project_name"], kind="mergesort").reset_index(drop=True)
    dupk = proj.duplicated(["report_type", "report_period", "list_type", "project_key"], keep=False)
    dupk &= ~proj["dq_note"].str.contains("duplicate_in_source")  # row printed twice by the source
    assert not dupk.any(), proj.loc[dupk, ["report_period", "list_type", "project_key", "project_name"]].head(10)
    monthly = proj["report_type"].isin(["monthly_flash", "paimana_flash"])
    assert (monthly | proj["report_type"].eq("quarterly_qpisr")).all()
    write(proj.loc[monthly, out_cols], OUT_P / "projects_monthly.csv")
    write(proj.loc[~monthly, out_cols], OUT_P / "projects_quarterly.csv")

    # ---- summaries out
    summ = summ.sort_values(["report_period", "report_type", "source_file", "table_title", "dimension"],
                            kind="mergesort").reset_index(drop=True)
    summ_cols = SUMMARY_COLS + ["family", "sector", "sector_hml", "state", "dq_flags"]
    write(summ[summ_cols], OUT_P / "project_summaries.csv")

    # ---- period tables
    rep_flags = (proj.groupby(["report_type", "report_period"])["source_file"]
                 .agg(lambda s: join_flags(*[[f for f in src_flags[x] if f != "image_pages_not_extracted"]
                                             for x in sorted(set(s))])))
    sector_period, state_period, overview = period_tables(proj, summ, man, rep_flags)
    write(sector_period, OUT_P / "project_sector_period.csv")
    write(state_period, OUT_P / "project_state_period.csv")
    write(overview, OUT_P / "project_period_overview.csv")

    # ---- master
    master = build_master(proj, comp_codes, portal)
    write(master, OUT_P / "project_master.csv")

    # ---- reference files
    write(smap, OUT_R / "sector_map.csv")
    write(stmap, OUT_R / "state_map.csv")
    write(xwalk, OUT_R / "project_id_crosswalk.csv")
    man_out = man[MANIFEST_COLS + ["family", "report_family", "fiscal_year", "data_quality_flags"]] \
        .sort_values(["report_family", "report_period", "source_file"], kind="mergesort")
    write(man_out, OUT_R / "source_manifest.csv")

    # ---- checks
    assert len(proj) == n_proj_in and monthly.sum() + (~monthly).sum() == n_proj_in
    assert len(summ) == n_summ_in and len(man_out) == n_man_in
    assert not smap.duplicated(["era", "sector_raw", "ministry"]).any()
    assert not stmap.duplicated(["state_raw"]).any()
    assert not xwalk.duplicated(["key_a", "key_b", "evidence"]).any()
    assert master["project_key"].is_unique and set(master["project_key"]) == set(proj["project_key"])
    assert master["n_reports"].sum() == proj.drop_duplicates(["project_key", "report_type", "report_period"]).shape[0]
    ong = proj[proj["list_type"].eq("ongoing")]
    assert sector_period["n_projects"].sum() == len(ong)
    assert abs(sector_period["cost_original_cr"].sum() - ong["_c_orig"].sum()) < 1
    assert abs(sector_period["expenditure_cum_cr"].sum() - ong["_exp"].sum()) < 1
    assert sector_period["n_completed"].sum() == proj["list_type"].eq("completed").sum()
    single = ong["state"].ne("") & ~ong["state"].isin(SPECIAL_STATES)
    assert state_period["n_projects"].sum() == single.sum()
    assert overview["n_projects"].sum() == len(ong)
    chk = sector_period.groupby(["report_type", "report_period"])["n_projects"].sum()
    ov = overview.set_index(["report_type", "report_period"])["n_projects"]
    assert (chk.reindex(ov.index).fillna(0) == ov).all()
    assert proj["sector"].isin(SECTORS).all()
    assert (proj.loc[proj["state_raw"].ne(""), "state"] != "").all()
    cf = proj[proj["dq_flags"].str.contains("printed_code_conflict")]  # untrusted code never keys its row
    assert (cf["project_key"] != [norm_code(c) for c in cf["project_code"]]).all()

    # ---- report
    unk_p = int((proj["sector"] == "Unknown").sum())
    unk_s = int(((summ["sector"] == "Unknown")).sum())
    print(f"sector Unknown: {unk_p} project rows, {unk_s} summary rows; "
          f"unrecognised state strings: {len(unmapped_state)}")
    print("linkage by family:")
    print(link_stats.to_string())
    return dict(proj=proj, summ=summ, smap=smap, stmap=stmap, xwalk=xwalk, master=master,
                link_stats=link_stats, sector_period=sector_period)


# ----------------------------------------------------------------------------- identity

def code_conflicts(proj):
    """Some lists print another project's code (e.g. MoSPI Annexure-I of deleted projects). Within each
    code, rows are single-linked when their names share a token (>= 3 chars) or their agencies agree;
    the cluster with most ongoing rows (then most rows, then earliest) keeps the code, rows of other
    clusters are returned True. Rows with no usable name token cannot be judged and keep the code."""
    sub = proj[proj["_code"].notna()].assign(_ong=lambda d: d["list_type"].eq("ongoing"))
    combos = sub.groupby(["_code", "project_name", "agency"], sort=True).agg(
        n=("_rid", "size"), n_ong=("_ong", "sum"), first=("_rid", "min")).reset_index()
    bad = set()
    for code, g in combos.groupby("_code", sort=True):
        if len(g) < 2:
            continue
        recs = [({t for t in tokens(nm) if len(t) >= 3}, compact(a), nm, a, n, no, f)
                for nm, a, n, no, f in zip(g["project_name"], g["agency"], g["n"], g["n_ong"], g["first"])]
        recs = [r for r in recs if r[0]]            # no usable name token: cannot be judged, keeps code
        par = list(range(len(recs)))

        def root(i):
            while par[i] != i:
                i = par[i]
            return i
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                if recs[i][0] & recs[j][0] or (recs[i][1] and recs[i][1] == recs[j][1]):
                    par[root(j)] = root(i)
        cl = {}
        for i in range(len(recs)):
            cl.setdefault(root(i), []).append(recs[i])
        if len(cl) < 2:
            continue
        keep = max(cl.values(), key=lambda m: (sum(r[5] for r in m), sum(r[4] for r in m), -min(r[6] for r in m)))
        bad |= {(code, r[2], r[3]) for m in cl.values() if m is not keep for r in m}
    return pd.Series([(c, nm, a) in bad for c, nm, a in zip(proj["_code"], proj["project_name"], proj["agency"])],
                     index=proj.index)


def assign_keys(proj, portal):
    proj["_rid"] = np.arange(len(proj))
    proj["_slot"] = proj["report_type"] + "|" + proj["report_period"] + "|" + proj["list_type"]
    # object dtype keeps None (pandas 3 str dtype would turn it into a truthy NaN)
    proj["_code"] = pd.Series([norm_code(c) for c in proj["project_code"]], index=proj.index, dtype=object)
    bad = proj["project_code"].ne("") & proj["_code"].isna()
    assert not bad.any(), f"unrecognised project codes: {proj.loc[bad, 'project_code'].unique()[:10]}"
    proj["_conflict"] = code_conflicts(proj)
    proj.loc[proj["_conflict"], "_code"] = None
    proj.loc[proj["_conflict"], "dq_flags"] = [join_flags(f.split(";"), ["printed_code_conflict"])
                                               for f in proj.loc[proj["_conflict"], "dq_flags"]]
    print(f"printed codes not trusted (name/agency uncorroborated): {int(proj['_conflict'].sum())} rows")
    comp = Components()
    for code, slot in zip(proj["_code"], proj["_slot"]):
        if code:
            comp.add(code, [slot], code)
    xrows = []

    # -- printed alt codes (project_code_alt, or 'OCMS:/PMG:' ids packed in remarks)
    alt = []
    for rid, code, a, rem, src, per in zip(proj["_rid"], proj["_code"], proj["project_code_alt"],
                                            proj["remarks"], proj["source_file"], proj["report_period"]):
        if not code:
            continue
        found = [(x.split(":", 1), "printed_alt_code") for x in a.split(";") if ":" in x]
        found += [((s, i), "remarks_code") for s, i in re.findall(r"\b(OCMS|PMG|PAIMANA)\s*:\s*([A-Z]?\d+)\b", rem)]
        for (sys_, ident), ev in found:
            other = norm_code(ident, sys_.strip().upper())
            if other and other != code:
                alt.append((code, other, ev, src, per))
    alt = pd.DataFrame(alt, columns=["key_a", "key_b", "evidence", "source_file", "report_period"])
    if len(alt):
        alt = (alt.sort_values(["report_period", "source_file"])
               .groupby(["key_a", "key_b", "evidence"], as_index=False)
               .agg(source_file=("source_file", "first"), report_period=("report_period", "first"),
                    n_occurrences=("source_file", "size")))

    # corroborate PAIMANA <-> OCMS against the OCMS-era rows of that code
    by_code = proj[proj["_code"].notna()].groupby("_code")
    ocms_costs = by_code.apply(lambda g: set(pd.concat([num(g["cost_original_cr"]), num(g["cost_revised_cr"]),
                                                        num(g["cost_anticipated_cr"])]).dropna().round(2)),
                               include_groups=False)
    ocms_orig = by_code.apply(lambda g: set(num(g["cost_original_cr"]).dropna().round(2)), include_groups=False)
    names = by_code["project_name"].agg(lambda s: sorted(set(s)))
    p_cost = by_code.apply(lambda g: set(num(g["cost_original_cr"]).dropna().round(2)), include_groups=False)
    p_name = names

    def verify(a, b):
        pair = {k.split(":")[0]: k for k in (a, b)}
        if set(pair) != {"OCMS", "PAIMANA"}:
            return True, "unverifiable: no PMG-keyed data to corroborate"
        a, b = pair["PAIMANA"], pair["OCMS"]
        if b not in names.index:
            return False, "unverified: OCMS code not in any extracted report"
        pc, oc_all, oc_orig = p_cost.get(a, set()), ocms_costs[b], ocms_orig[b]
        if any(abs(x - y) <= 0.011 for x in pc for y in oc_all):
            return True, "cost_exact"
        jac = max(jaccard(x, y) for x in p_name[a] for y in names[b])
        near = any(abs(x - y) <= 0.01 * y for x in pc for y in oc_orig)
        if near and jac >= 0.1:
            return True, f"cost_within_1pct+name_jaccard:{jac:.2f}"
        if jac >= 0.25:
            return True, f"name_jaccard:{jac:.2f}"
        return False, f"no corroboration (name_jaccard:{jac:.2f}, costs {sorted(pc)[:2]} vs {sorted(oc_orig)[:2]})"

    if len(alt):
        v = [verify(a, b) for a, b in zip(alt["key_a"], alt["key_b"])]
        alt["_ok"] = [x[0] for x in v]
        alt["detail"] = [x[1] for x in v]
        alt["reject_reason"] = np.where(alt["_ok"], "", "not_corroborated")
        # one-to-one among corroborated links, per target system
        alt["_sys"] = alt["key_b"].str.split(":").str[0]
        ok = alt["_ok"]
        n_b = alt[ok].groupby(["key_b"])["key_a"].transform("nunique")
        n_a = alt[ok].groupby(["key_a", "_sys"])["key_b"].transform("nunique")
        many = pd.Series(False, index=alt.index)
        many[ok] = (n_b > 1) | (n_a > 1)
        alt.loc[many, "reject_reason"] = "one_to_many"
        alt["_ok"] &= ~many
        for i in alt.index[alt["_ok"]].tolist():
            comp.add(alt.at[i, "key_b"], (), alt.at[i, "key_b"])
            why = comp.union(alt.at[i, "key_a"], alt.at[i, "key_b"])
            if why:
                alt.at[i, "_ok"], alt.at[i, "reject_reason"] = False, why
        alt["applied"] = alt["_ok"]
        xrows.append(alt.drop(columns=["_ok", "_sys"]))

    # -- name linking for rows without a code
    proj["_lkey"] = proj["name_norm"].str.replace(" ", "", regex=False)
    proj["_agency"] = proj["agency"].map(compact)
    ong = proj[proj["list_type"].eq("ongoing")].groupby(["report_type", "report_period"]).size()
    full = {rt: sorted(p for (t, p), n in ong.items() if t == rt and n >= 20) for rt in proj["report_type"].unique()}

    def window(rt, p):
        f = full.get(rt, [])
        prev = max([x for x in f if x < p], default=p)
        nxt = min([x for x in f if x > p], default=p)
        return prev, nxt

    slot_count = proj.groupby(["_slot", "_lkey"]).size()
    proj["_node"] = [c if c else f"ROW:{r}" for c, r in zip(proj["_code"], proj["_rid"])]
    for node, slot in zip(proj["_node"], proj["_slot"]):
        if node.startswith("ROW:"):
            comp.add(node, [slot])
    pairs, n_agency_block = [], 0
    gk = ["report_type", "_lkey", "sector"]
    want = pd.MultiIndex.from_frame(proj.loc[proj["_code"].isna() & proj["_lkey"].ne(""), gk].drop_duplicates())
    cand_rows = proj[pd.MultiIndex.from_frame(proj[gk]).isin(want)]
    for (rt, lk, sec), g in cand_rows.groupby(gk, sort=True):
        if len(g) < 2:
            continue
        recs = list(zip(g["_rid"], g["report_period"], g["_slot"], g["_node"], g["_code"], g["_agency"]))
        for rid, per, slot, node, code, ag in recs:
            if code or slot_count[(slot, lk)] > 1:
                continue
            lo, hi = window(rt, per)
            cands = [c for c in recs if c[0] != rid and lo <= c[1] <= hi and c[2] != slot]
            if not cands or any(slot_count[(c[2], lk)] > 1 for c in cands):
                continue
            keep = [c for c in cands if not (ag and c[5] and ag != c[5])]
            n_agency_block += len(cands) - len(keep)
            pairs += [(node, c[3], c[4] is not None, rid) for c in keep]
    pairs.sort(key=lambda t: (t[2], t[3], t[1]))
    # stage 1: chain code-less rows among themselves
    for a, b, coded, _ in pairs:
        if not coded:
            comp.union(a, b)
    # NAME ids for code-less chains (stable: earliest row's name + sector + period)
    roots = {}
    for node, rid in zip(proj["_node"], proj["_rid"]):
        if node.startswith("ROW:"):
            roots.setdefault(comp.find(node), []).append(rid)
    name_id, used = {}, set()
    order = proj.set_index("_rid")
    for root in sorted(roots, key=lambda r: min(roots[r])):
        rids = sorted(roots[root], key=lambda r: (order.at[r, "report_period"], r))
        first = order.loc[rids[0]]
        h = hashlib.sha1(f"{first['_lkey']}|{first['sector']}|{first['report_period']}".encode()).hexdigest()[:10]
        key, k = f"NAME:{h}", 2
        while key in used:
            key, k = f"NAME:{h}-{k}", k + 1
        used.add(key)
        name_id[root] = key
    # stage 2: a chain whose rows name-match rows of exactly one coded project joins it
    targets = {}
    for a, b, coded, rid in pairs:
        if coded:
            t = targets.setdefault(comp.find(a), {})
            t.setdefault(comp.find(b), []).append(rid)
    name_links = []
    for root in sorted(targets, key=lambda r: name_id[r]):
        tg = targets[root]
        tcodes = {t: sorted(comp.codes[comp.find(t)], key=code_sort)[0] for t in tg}
        first_rid = min(min(v) for v in tg.values())
        src, per = order.at[first_rid, "source_file"], order.at[first_rid, "report_period"]
        n_occ = sum(len(v) for v in tg.values())
        if len(tg) > 1:
            for t in sorted(tg, key=lambda t: tcodes[t]):
                name_links.append((name_id[root], tcodes[t], False, "ambiguous: name matches several coded projects", src, per, n_occ))
            continue
        t = next(iter(tg))
        why = comp.union(root, t)
        name_links.append((name_id[root], tcodes[t], why is None, why or "", src, per, n_occ))
    nl = pd.DataFrame(name_links, columns=["key_a", "key_b", "applied", "reject_reason", "source_file",
                                           "report_period", "n_occurrences"])
    nl["evidence"] = "exact_name_sector_adjacent_report"
    nl["detail"] = "name (alnum) + harmonised sector, same/previous/next full report of the same stream"
    xrows.append(nl)

    # -- final keys
    final = {}
    for node in proj["_node"].unique():
        r = comp.find(node)
        if r not in final:
            codes = sorted(comp.codes[r], key=code_sort)
            final[r] = codes[0] if codes else name_id[r]
    proj["project_key"] = [final[comp.find(n)] for n in proj["_node"]]
    comp_codes = {final[r]: sorted(comp.codes[r], key=code_sort) for r in final}
    proj["key_source"] = np.select(
        [proj["_code"].notna() & (proj["project_key"] == proj["_code"]),
         proj["_code"].notna(),
         proj["project_key"].str.startswith("NAME:")],
        ["printed_code", "crosswalk", "name_chain"], "name_link_to_code")

    xw = pd.concat(xrows, ignore_index=True)
    xw = xw[["key_a", "key_b", "evidence", "detail", "applied", "reject_reason", "source_file",
             "report_period", "n_occurrences"]].sort_values(["evidence", "key_a", "key_b"], kind="mergesort")

    # -- linkage stats
    multi = proj.groupby("project_key")["report_period"].transform("nunique") > 1
    st = proj.assign(_nocode=proj["_code"].isna(), _multi=multi).groupby("family").agg(
        rows=("_rid", "size"),
        pct_printed_code=("_code", lambda s: round(100 * s.notna().mean(), 1)),
        rows_no_code=("_nocode", "sum"),
        pct_no_code_linked_to_code=("key_source", lambda s: round(
            100 * (s == "name_link_to_code").sum() / max(1, s.isin(["name_link_to_code", "name_chain"]).sum()), 1)),
        pct_rows_key_seen_in_2plus_periods=("_multi", lambda s: round(100 * s.mean(), 1)),
    )
    st.attrs["n_agency_block"] = n_agency_block
    print(f"name-link candidate pairs dropped for agency mismatch: {n_agency_block}")
    drop = [c for c in proj.columns if c.startswith("_") and c not in
            ("_c_orig", "_c_latest", "_t_over", "_delay", "_exp", "_phys", "_fin", "_doc_later")]
    return proj.drop(columns=drop), xw, st, comp_codes


# ----------------------------------------------------------------------------- aggregates

PRINTED_SECTOR_TABLES = [  # per report the first title that exists gives printed_n_projects
    ("sector", r"Sectorwise analysis of projects \(abstract\)"),
    ("sector", r"Sectorwise analysis of projects"),
    ("sector", r"Sector-wise analysis of projects"),
    ("sector", r"Sector-wise financial details \(planned and balance expenditure\)"),
    ("sector", r"Analysis of planned and balance expenditure \(Sector wise\)"),
    ("sector", r"Annex 4: Sector-wise distribution - Ongoing Projects.*"),
    ("sector", r"Overview of Ongoing Projects: Sector-wise Distribution"),
    ("ministry_sector", r"Ministry-wise Ongoing Projects"),
]


def stats(d, keys):
    d = d.assign(_both=d["_c_orig"].notna() & d["_c_latest"].notna(),
                 _fin_ok=d["_exp"].notna() & (d["_c_latest"] > 0))
    d = d.assign(_over=(d["_c_latest"] - d["_c_orig"]).where(d["_both"]),
                 _exp_f=d["_exp"].where(d["_fin_ok"]), _lat_f=d["_c_latest"].where(d["_fin_ok"]),
                 _dl=d["_delay"].where(d["_delay"] > 0))
    g = d.groupby(keys, sort=True)
    s1 = lambda s: s.sum(min_count=1)  # noqa: E731
    out = g.agg(n_projects=("project_key", "size"),
                cost_original_cr=("_c_orig", s1), cost_latest_cr=("_c_latest", s1),
                cost_overrun_cr=("_over", s1), n_cost_overrun=("_over", lambda s: int((s > 0).sum())),
                n_with_doc=("_delay", "count"), n_delayed=("_dl", "count"),
                avg_delay_months_delayed=("_dl", "mean"),
                expenditure_cum_cr=("_exp", s1), _e=("_exp_f", s1), _l=("_lat_f", s1),
                avg_physical_progress_pct=("_phys", "mean"))
    out["financial_progress_pct"] = out["_e"] / out["_l"] * 100
    return out.drop(columns=["_e", "_l"])


def period_tables(proj, summ, man, rep_flags):
    base = ["report_type", "report_period", "fiscal_year", "quarter"]
    ong = proj[proj["list_type"].eq("ongoing")]
    cnt = lambda lt, keys: proj[proj["list_type"].eq(lt)].groupby(keys).size()  # noqa: E731

    # printed ongoing counts per harmonised sector, from one table per report
    s = summ[summ["metric"].eq("n_projects") & summ["sector"].ne("")]
    pick = []
    for (rt, rp), g in s.groupby(["report_type", "report_period"]):
        for dim_, pat in PRINTED_SECTOR_TABLES:
            h = g[g["dimension"].eq(dim_) & g["table_title"].str.fullmatch(pat)
                  & g["sub_dimension_value"].eq("" if dim_ == "sector" else g["sub_dimension_value"])]
            if len(h):
                # a table printed on several pages / files: keep one copy per source row label
                h = h.drop_duplicates(["dimension_value", "sub_dimension_value"])
                pick.append(h.assign(_table=h["table_title"].iloc[0]))
                break
    pr = pd.concat(pick) if pick else s.iloc[:0].assign(_table="")
    pr = pr.assign(_v=num(pr["value"]))
    printed = pr.groupby(["report_type", "report_period", "sector"])["_v"].sum(min_count=1)
    printed_tbl = pr.groupby(["report_type", "report_period"])["_table"].first()

    keys = base + ["sector"]
    sp = stats(ong, keys)
    extra = pd.concat({"n_completed": cnt("completed", keys), "n_newly_added": cnt("newly_added", keys),
                       "n_dropped": cnt("dropped", keys)}, axis=1)
    sp = sp.join(extra, how="outer").reset_index()
    for c in ("n_projects", "n_completed", "n_newly_added", "n_dropped", "n_cost_overrun", "n_with_doc", "n_delayed"):
        sp[c] = sp[c].fillna(0).astype(int)
    sp["printed_n_projects"] = [printed.get((a, b, c), np.nan) for a, b, c in
                                zip(sp["report_type"], sp["report_period"], sp["sector"])]
    has_tbl = sp.set_index(["report_type", "report_period"]).index.isin(printed_tbl.index)
    sp.loc[has_tbl & sp["printed_n_projects"].isna(), "printed_n_projects"] = 0  # table printed, sector absent
    sp["printed_n_projects"] = sp["printed_n_projects"].astype("Int64")
    sp["n_projects_diff"] = (sp["n_projects"] - sp["printed_n_projects"]).astype("Int64")
    sp["printed_source_table"] = [printed_tbl.get((a, b), "") for a, b in zip(sp["report_type"], sp["report_period"])]
    flags_by = proj.groupby(keys)["dq_flags"].agg(lambda s: join_flags(*[x.split(";") for x in sorted(set(s))]))
    sp["report_flags"] = [flags_by.get((a, b, c, d, e), "") for a, b, c, d, e in
                          zip(sp["report_type"], sp["report_period"], sp["fiscal_year"], sp["quarter"], sp["sector"])]

    # printed-table sectors with no extracted row at all
    miss = [k for k in printed.index if (sp["report_type"].eq(k[0]) & sp["report_period"].eq(k[1])
                                         & sp["sector"].eq(k[2])).sum() == 0 and printed[k] > 0]
    if miss:
        print(f"printed sectors without extracted rows: {len(miss)} e.g. {miss[:3]}")

    stk = base + ["state"]
    one = proj[proj["state"].ne("") & ~proj["state"].isin(SPECIAL_STATES)]
    tp = stats(one[one["list_type"].eq("ongoing")], stk)
    ex2 = pd.concat({"n_completed": one[one["list_type"].eq("completed")].groupby(stk).size(),
                     "n_newly_added": one[one["list_type"].eq("newly_added")].groupby(stk).size()}, axis=1)
    tp = tp.join(ex2, how="outer").reset_index()
    for c in ("n_projects", "n_completed", "n_newly_added", "n_cost_overrun", "n_with_doc", "n_delayed"):
        tp[c] = tp[c].fillna(0).astype(int)
    tp["report_flags"] = [rep_flags.get((a, b), "") for a, b in zip(tp["report_type"], tp["report_period"])]

    ov = stats(ong, base)
    ov = ov.join(pd.concat({"n_completed": cnt("completed", base), "n_newly_added": cnt("newly_added", base),
                            "n_dropped": cnt("dropped", base)}, axis=1), how="outer").reset_index()
    for c in ("n_projects", "n_completed", "n_newly_added", "n_dropped", "n_cost_overrun", "n_with_doc", "n_delayed"):
        ov[c] = ov[c].fillna(0).astype(int)
    stated = (man.assign(_n=num(man["stated_total_projects"]))
              .groupby(["report_type", "report_period"])["_n"].max())
    ov["stated_total_projects"] = [stated.get((a, b), np.nan) for a, b in zip(ov["report_type"], ov["report_period"])]
    ov["stated_total_projects"] = ov["stated_total_projects"].astype("Int64")
    ov["n_projects_diff"] = (ov["n_projects"] - ov["stated_total_projects"]).astype("Int64")
    ps = sp.groupby(["report_type", "report_period"])["printed_n_projects"].sum(min_count=1)
    ov["printed_sector_table_total"] = [ps.get((a, b), pd.NA) for a, b in zip(ov["report_type"], ov["report_period"])]
    ov["printed_sector_table_total"] = ov["printed_sector_table_total"].astype("Int64")
    srcs = proj.groupby(["report_type", "report_period"])["source_file"].agg(lambda s: ";".join(sorted(set(s))))
    ov["source_files"] = [srcs.get((a, b), "") for a, b in zip(ov["report_type"], ov["report_period"])]
    ov["report_flags"] = [rep_flags.get((a, b), "") for a, b in zip(ov["report_type"], ov["report_period"])]

    def tidy(d, lead):
        for c in ("cost_original_cr", "cost_latest_cr", "cost_overrun_cr", "expenditure_cum_cr",
                  "avg_delay_months_delayed", "financial_progress_pct", "avg_physical_progress_pct"):
            d[c] = d[c].round(2)
        cols = lead + ["n_projects", "cost_original_cr", "cost_latest_cr", "cost_overrun_cr", "n_cost_overrun",
                       "n_with_doc", "n_delayed", "avg_delay_months_delayed", "expenditure_cum_cr",
                       "financial_progress_pct", "avg_physical_progress_pct", "n_completed", "n_newly_added"]
        rest = [c for c in d.columns if c not in cols]
        return d[cols + rest].sort_values(lead, kind="mergesort").reset_index(drop=True)

    return tidy(sp, keys), tidy(tp, stk), tidy(ov, base)


LIST_RANK = {"completed": 4, "dropped": 3, "ongoing": 2, "newly_added": 1}
RT_RANK = {"quarterly_qpisr": 0, "monthly_flash": 1, "paimana_flash": 2}


def changes(vals, is_increase=False):
    """Count value changes (or increases) along a chronological series, NaNs skipped."""
    v = [x for x in vals if pd.notna(x)]
    if is_increase:
        return sum(1 for a, b in zip(v, v[1:]) if b > a)
    return sum(1 for a, b in zip(v, v[1:]) if abs(b - a) > max(0.01, 0.0005 * abs(a)))


def build_master(proj, codes, portal):
    d = proj.assign(_lr=proj["list_type"].map(LIST_RANK).fillna(0), _rt=proj["report_type"].map(RT_RANK),
                    _docl=ym_index(proj["_doc_later"]))
    d = d.sort_values(["project_key", "report_period", "_rt", "_lr", "source_file"], kind="mergesort")
    blank_nan = lambda c: d[c].replace("", np.nan)  # noqa: E731
    lastv = d.assign(**{c: blank_nan(c) for c in ["project_name", "sector", "sector_hml", "state", "ministry",
                                                  "agency", "doa_original", "doc_original", "_doc_later"]}) \
        .groupby("project_key")[["project_name", "sector", "sector_hml", "state", "ministry", "agency",
                                 "_c_orig", "_c_latest", "_exp", "_phys", "doa_original", "doc_original",
                                 "_doc_later", "_delay"]].last()
    g = d.groupby("project_key")
    last_row = g.tail(1).set_index("project_key")
    m = pd.DataFrame({
        "first_seen_period": g["report_period"].min(),
        "last_seen_period": g["report_period"].max(),
        "n_reports": d.drop_duplicates(["project_key", "report_type", "report_period"]).groupby("project_key").size(),
        "last_report_type": last_row["report_type"],
        "last_list_type": last_row["list_type"],
        "completed_period": d[d["list_type"].eq("completed")].groupby("project_key")["report_period"].min(),
    })
    # ponytail: one value per period across both report streams; where monthly and quarterly
    # reports of the same months print different figures this can count spurious changes.
    per = d.groupby(["project_key", "report_period"])[["_c_latest", "_docl"]].last()
    m["n_cost_revisions"] = per.groupby(level=0)["_c_latest"].agg(lambda s: changes(s.tolist()))
    m["n_schedule_slips"] = per.groupby(level=0)["_docl"].agg(lambda s: changes(s.tolist(), True))
    m = m.join(lastv)
    in_portal = set("PAIMANA:" + portal["project_code"].astype(str).str.strip())
    m["project_codes"] = [";".join(codes.get(k, [])) for k in m.index]
    m["in_portal_snapshot"] = [any(c in in_portal for c in codes.get(k, [])) for k in m.index]
    m = m.reset_index().rename(columns={
        "_c_orig": "cost_original_cr", "_c_latest": "cost_latest_cr", "_exp": "expenditure_cum_cr",
        "_phys": "physical_progress_pct", "_doc_later": "doc_latest_anticipated", "_delay": "delay_months_latest"})
    for c in ("cost_original_cr", "cost_latest_cr", "expenditure_cum_cr", "physical_progress_pct"):
        m[c] = m[c].round(2)
    m["delay_months_latest"] = m["delay_months_latest"].astype("Int64")
    cols = ["project_key", "project_codes", "project_name", "sector", "sector_hml", "state", "ministry", "agency",
            "first_seen_period", "last_seen_period", "n_reports", "last_report_type", "last_list_type",
            "completed_period", "cost_original_cr", "cost_latest_cr", "expenditure_cum_cr", "physical_progress_pct",
            "doa_original", "doc_original", "doc_latest_anticipated", "delay_months_latest", "n_cost_revisions",
            "n_schedule_slips", "in_portal_snapshot"]
    return m[cols].fillna({"project_codes": ""}).sort_values("project_key").reset_index(drop=True)


if __name__ == "__main__":
    assert map_sector("ocms", "TELECOMMUNICATI ONS", "")[1] == "Telecommunications"
    assert map_sector("ocms", "ROAD TRANSPORT AND HIGHWAYS 853", "")[1] == "Roads & Highways"
    assert map_sector("hml", "Energy Storage", "")[1] == "Unknown"
    assert map_sector("hml", "Energy Storage", "Ministry of Petroleum & Natural Gas")[1] == "Petroleum & Natural Gas"
    assert map_sector("hml", "Healthcare", "Ministry of Labour and Employment")[1] == "Health"
    assert map_state("MULTI-STATES (BIHAR, JHARKHAND)") == ("Multi-State", "Bihar;Jharkhand", "")
    assert map_state("Bihar, Jharkhand")[0] == "Multi-State" and map_state("ORISSA")[0] == "Odisha"
    assert norm_code("60100093", "OCMS") == "OCMS:060100093" and norm_code("706718") == "PAIMANA:706718"
    c = Components()
    c.add("OCMS:A", [("m", "2020-01", "ongoing")], "OCMS:A")
    c.add("OCMS:B", [("m", "2020-02", "ongoing")], "OCMS:B")
    c.add("PAIMANA:1", [("p", "2026-01", "ongoing")], "PAIMANA:1")
    assert c.union("OCMS:A", "PAIMANA:1") is None and c.union("OCMS:B", "PAIMANA:1") == "conflicting_OCMS_codes"
    build()
