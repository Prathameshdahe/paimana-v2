"""
Canonical agency names and the Agency Performance Matrix (docs/IMPLEMENTATION_GUIDE_v2.md B 6.3).

Run from repo root after score (part of the profile step):  python -m pipeline.run profile

Inputs   silver/observations.parquet, silver/project_master.parquet, gold/predictions_latest.json (and the file it
         names: the current portfolio)
Outputs  gold/agency_map.csv (every printed agency string -> canonical name and how it was mapped, for review),
         gold/agency_matrix.parquet (one row per canonical agency)

canonical_agency(): upper case, '&' -> AND, punctuation to spaces, LTD / LIMITED / PVT and trailing roman numerals
dropped; then the first rule that applies: the ALIASES table (built from the printed strings, largest first); a
bracketed acronym ('Airport Authority of India [AAI]' -> AAI) or a parenthesised all-caps one when two or more words
stand outside it; a railway office ('CAO/C/ECoR', 'CAOC/WR WR mor') -> its zone, or the railway PSU it names (RVNL,
IRCON, KRIDE); '<acronym> FOR ...' and an executing agency's own prefix ('CPWD EDUCATION', 'HSCL FOR RURAL') -> the
acronym; the longest multi-word alias that starts the name ('SOUTH EASTERN RAILWAY JH' -> SER).
Anything else keeps its normalised form, and build_map() then merges it into a larger name of the same sector when
rapidfuzz token_set_ratio >= FUZZY_MIN and the words that differ on both sides are a spelling variant of each other
(so 'WATER RESOURCES MP' and 'WATER RESOURCES PB' stay two agencies).

Matrix, per project (current and finished, observations up to asof): schedule bias = (latest anticipated completion,
or the completion report period) - sanction, over (first printed scheduled completion - sanction), minus 1; cost
bias = latest anticipated cost / first original cost - 1. Only projects with a known planned duration count. Per
canonical agency: n, median, IQR and a bootstrap 90% CI of the median for both; for n < SHRINK_N the medians are
shrunk toward the sector median with weight n / (n + SHRINK_K) (raw kept); hidden when n < HIDE_N. Capital under
management and n_open read the current portfolio. Trend = median schedule bias of projects sanctioned in the last
TREND_YEARS years of data minus that of earlier ones (None with fewer than TREND_MIN on either side).
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.silver import ROOT, SILVER, months  # noqa: E402

GOLD = ROOT / "dataset" / "gold"
FUZZY_MIN, TYPO_MIN = 92, 80
SHRINK_N, SHRINK_K, HIDE_N = 10, 10, 5
TREND_YEARS, TREND_MIN = 3, 3
N_BOOT, CI = 1000, 0.90

ZONES = {
    "CR": ["CENTRAL RAILWAY", "CENTRALRAILWAY"], "ER": ["EASTERN RAILWAY"], "ECR": ["EAST CENTRAL RAILWAY"],
    "ECOR": ["EAST COAST RAILWAY"], "NR": ["NORTHERN RAILWAY", "NORTHEN RAILWAY"], "NCR": ["NORTH CENTRAL RAILWAY"],
    "NER": ["NORTH EASTERN RAILWAY"], "NFR": ["NORTHEAST FRONTIER RAILWAY", "NORTH EAST FRONTIER RAILWAY", "NEFR"],
    "NWR": ["NORTH WESTERN RAILWAY"], "SR": ["SOUTHERN RAILWAY"], "SCR": ["SOUTH CENTRAL RAILWAY"],
    "SER": ["SOUTH EASTERN RAILWAY"], "SECR": ["SOUTH EAST CENTRAL RAILWAY", "SOUTH EASTERN CENTRAL RAILWAY"],
    "SWR": ["SOUTH WESTERN RAILWAY"], "WR": ["WESTERN RAILWAY"], "WCR": ["WEST CENTRAL RAILWAY"],
    "SCOR": ["SOUTH COAST RAILWAY", "SAUTH COST RAILWAY"], "METRO RAILWAY KOLKATA": ["METRO RAILWAY KOLKATA"],
}
RAIL_PSU = ["RVNL", "IRCON", "KRIDE", "RLDA", "DFCCIL", "KRCL"]
RAIL_OFFICE = {"CAO", "CAOC", "CAOCON", "PCE", "GM", "CGM", "CE", "CPM", "CMD"}
EXECUTING = {"CPWD", "NBCC", "HSCL", "HSCC"}   # build for other ministries: 'CPWD FOR MHA', 'NBCC FOR HEALTH'
# canonical -> normalised printed variants (see normalise()); the acronym itself maps to itself anyway
ALIASES = {
    "NHAI": ["NATIONAL HIGHWAYS AUTHORITY OF INDIA", "NATIONAL HIGHWAYS DEVELOPMENT PROJECT"],
    "MORTH": ["MINISTRY OF ROAD TRANSPORT AND HIGHWAYS", "MINISTRY OF ROAD TRANSPORT AND HIGHWAYS STATE PWDS",
              "DEPT OF ROAD TRANSPORT AND HIGHWAYS"],
    "STATE PWD": ["PUBLIC WORKS DEPT OF STATE", "PWD"],
    "NHIDCL": ["NATIONAL HIGHWAYS AND INFRASTRUCTURE DEVELOPMENT CORPORATION"],
    "POWERGRID": ["POWER GRID CORPORATION OF INDIA", "PGCIL", "P GRID", "P GR"],
    "IOCL": ["INDIAN OIL CORPORATION"], "ONGC": ["OIL AND NATURAL GAS CORPORATION", "ONGCL"],
    "NTPC": ["NATIONAL THERMAL POWER CORPORATION"], "BSNL": ["BHARAT SANCHAR NIGAM"],
    "BPCL": ["BHARAT PETROLEUM CORPORATION"], "HPCL": ["HINDUSTAN PETROLEUM CORPORATION"],
    "GAIL": ["GAS AUTHORITY OF INDIA"], "GAIL GAS": ["GAIL GAS"],
    "AAI": ["AIRPORT AUTHORITY OF INDIA", "AIRPORTS AUTHORITY OF INDIA"],
    "CPWD": ["CENTRAL PUBLIC WORKS DEPARTMENT"],
    "NBCC": ["NATIONAL BUILDINGS CONSTRUCTION CORPORATION", "NATIONAL BUILDING CONSTRUCION CORPORATION"],
    "HSCC": ["HOSPITAL SERVICES CONSULTANCY CORPORATION"],
    "HSCL": ["HINDUSTAN STEELWORK CONSTRUCTION", "HINDUSTAN STEELWORKS CONSTRUCTION"],
    "NPCC": ["NATIONAL PROJECTS CONSTRUCTION CORPORATION"],
    "MOHUA": ["MINISTRY OF HOUSING AND URBAN AFFAIRS", "PMAY MINISTRY OF HOUSING AND URBAN AFFAIRS"],
    "MOHFW": ["MINISTRY OF HEALTH AND FAMILY WELFARE", "H AND FW",
              "MEDICAL EDUCATION MINISTRY OF HEALTH AND FAMILY WELFARE"],
    "MOPNG": ["MINISTRY OF PETROLEUM AND NATURAL GAS", "MINISTRYOFPETROLEUMNATURALGAS"],
    "DOT": ["DEPARTMENT OF TELECOMMUNICATIONS", "DEPARTMENT OF TELECOMMUNICATION"],
    "MTNL": ["MAHANAGAR TELEPHONE NIGAM"], "SAIL": ["STEEL AUTHORITY OF INDIA", "BOKARO STEEL PL"],
    "RINL": ["RASTRIYA ISPAT NIGAM", "RASHTRIYA ISPAT NIGAM"],
    # Coal India subsidiaries ('WCL - CIL' loses the CIL in normalise())
    "WCL": ["WESTERN COAL FIELDS"], "SECL": ["SOUTH EASTERN COAL FIELDS"], "MCL": ["MAHANADI COAL FIELDS"],
    "NCL": ["NORTHERN COAL FIELDS"], "ECL": ["EASTERN COAL FIELDS"], "BCCL": ["BHARAT COKING COAL"],
    "CCL": ["CENTRAL COAL FIELDS"], "SCCL": ["SINGARENI COLLIERS COMPANY", "SINGARENI COLLIERIES COMPANY"],
    "NLC": ["NLCIL", "NLC INDIA", "NEYVELI LIGNITE CORPORATION"],
    "ESIC": ["EMPLOYEE S STATE INSURANCE COMPANY", "EMPLOYEES STATE INSURANCE CORPORATION"],
    "NHPC": ["NATIONAL HYDRO ELECTRIC POWER CORPORATION", "NATIONAL HYDROELECTRIC POWER CORPORATION"],
    "SJVN": ["SATLUJ JAL VIDYUT NIGAM", "SJVNL"],
    "THDC": ["THDC INDIA", "THDCIL", "THDCL", "TEHRI HYDRO DEVELOPMENT CORPORATION"],
    "NEEPCO": ["NORTH EAST ELECTRIC POWER CORPORATION", "NORTH EASTERN ELECTRIC POWER CORPORATION"],
    "NPCIL": ["NUCLEAR POWER CORPORATION OF INDIA"], "DVC": ["DAMODAR VALLEY CORPORATION"],
    "OIL": ["OIL INDIA"], "CPCL": ["CHENNAI PETROLEUM CORPORATION"], "NRL": ["NUMALIGARH REFINERY"],
    "MRPL": ["MANGALORE REFINERY AND PETROCHEMICALS", "MANGALORE REFIN", "MANGALORE REFINARY AND PETROCHEMICALS"],
    "BCPL": ["BRAHMAPUTRA CRECKER AND POLYMER", "BRAHMAPUTRA CRACKER AND POLYMER"],
    "IGGL": ["INDRADHANUSH GAS GRID"], "ETTPL": ["ENNORE TANK", "ENNORE TANK TERMINAL"],
    "BRPL": ["BONGAIGAON REFINERY PETROLEUM"], "ISPRL": ["INDIAN STRATEGIC PETROLEUM RESERVES"],
    "NFL": ["NATIONAL FERTILISER", "NATIONAL FERTILIZERS"],
    "RCF": ["RASHTRIYA CHEMICAL AND FERTILISER", "RASHTRIYA CHEMICALS AND FERTILIZERS"],
    "NALCO": ["NATIONAL ALUMINIUM COMPANY", "NATIONAL ALUMINUM COMPANY"],
    "NMDC": ["NATIONAL MINERAL DEVELOPMENT CORPORATION"], "HCL": ["HINDUSTAN COPPER"],
    "UCIL": ["URANIUM CORPORATION OF INDIA"], "BHEL": ["BHARAT HEAVY ELECTRICALS"],
    "NICDC": ["NATIONAL INDUSTRIAL CORRIDOR DEVELOPMENT CORPORATION"],
    "SCI": ["SHIPPING CRP OF INDIA", "SHIPPING CORPORATION OF INDIA"],
    "CONCOR": ["CONTAINER CORPORATION OF INDIA"], "KPL": ["KAMARAJAR PORT", "ENNORE PORT"],
    "DPT": ["DEENDAYAL PORT TRUST", "DEENDAYAL PORT AUTHORITY"], "MBPT": ["MUMBAI PORT TRUST", "MPT", "MUMBAI PORT TRU"],
    "IWAI": ["INLAND WATERWAYS AUTHORITY OF INDIA"],
    "SMPK": ["HALDIA DOCK COMPLEX SYAMA PRASAD MOOKERJEE PORT AUTHORITY", "SYAMA PRASAD MOOKERJEE PORT KOLKATA"],
    "RVNL": ["RAIL VIKAS NIGAM"], "IRCON": ["INDIAN RAILWAY CONSTRUCTION COMPANY"],
    "RLDA": ["RAIL LAND DEVELOPMENT AUTHORITY"], "DFCCIL": ["DFCC", "DEDICATED FREIGHT CORRIDOR CORPORATION OF INDIA"],
    "KRCL": ["KONKAN RAILWAY CORPORATION"], "KRIDE": ["K RIDE"], "RITES": ["RAIL INDIA TECHNICAL AND ECONOMIC SERVICE"],
    "MRVC": ["MUMBAI RAIL VIKAS CORPORATION"], "NHSRCL": ["NATIONAL HIGH SPEED RAIL CORPORATION", "NHSRC"],
    "CORE": ["RAILWAY ELECTRIFICATION", "RE", "CENTRAL ORGANISATION FOR RAILWAY ELECTRIFICATION"],
    "INDIAN RAILWAYS": ["MINISTRY OF RAILWAY", "RAILWAY", "INDIAN RAILWAY", "EDTK MC RB"],
    "DMRC": ["DELHI METRO RAIL CORPORATION", "DMRCL"], "MMRC": ["MUMBAI METRO RAIL CORPORATION"],
    "MMRCL": ["MAHARASHTRA METRO RAIL CORPORATION", "MAHARASTRA METRO RAIL CORPORATION", "NAGPUR METRO RAIL CORPORATION"],
    "KMRCL": ["KOLKATA METRO RAIL CORPORATION"], "KMRL": ["KOCHI METRO RAIL CORPORATION"],
    "MPMRCL": ["MADHYA PRADESH METRO RAIL CO"], "PMRCL": ["PATNA METRO RAIL CORPORATION", "PATNA METRO RAI"],
    "NCRTC": ["NATIONAL CAPITAL REGION TRANSPORT CORP", "NATIONAL CAPITAL REGION TRANSPORT CORPORATION"],
    "BMRCL": ["BENGALURU METRO RAIL", "BANGALORE METRO RAIL CORPORATION"], "CMRL": ["CHENNAI METRO RAIL"],
    "JMRC": ["JAIPUR METRO RAIL CORPORATION"], "UPMRC": ["LUCKNOW METRO RAIL CORPORATION", "LMRCL",
                                                        "UTTAR PRADESH METRO RAIL CORPORATION"],
    "UP JAL NIGAM": ["UPJALNIGAM", "UTTAR PRADESH JAL NIGAM"], "UK JAL NIGAM": ["UKJALNIGAM"],
    "NMCG": ["NATIONAL MISSION FOR CLEAN GANGA", "NMCG1"], "DJB": ["DELHI JAL BOARD"],
    "KMDA": ["KOLKATA METROPOLITAN DEVELOPMENT AUTHORITY"], "BUIDCO": ["BIHAR URBAN INFRASTRUCTURE DEVELOPMENT CORPORATION"],
    "MRTP": ["METROPOLITAN RAPID TRANSPORT PROJECTS"], "MOWR": ["MINISTRY OF WATER RESOURCES"],
    "DMIC": ["DELHI MUMBAI INDUSTRIAL CORRIDOR"], "IICC": ["INDIA INTERNATIONAL CONVENTION AND EXPO CENTRE"],
    "EDCIL": ["EDCIL INDIA"], "IIT KHARAGPUR": ["IITKGP", "INDIAN INSTITUTE OF TECHNOLOGY KHARAGPUR"],
    "SIKKIM UNIVERSITY": ["SIKKIM UNIVERSI"], "WORKSHOPS AND PRODUCTION UNIT": ["WS AND PU"],
    **{code: names for code, names in ZONES.items()},
}
JUNK = {"INVALID CO"}
ALIAS = {v: c for c, vs in ALIASES.items() for v in vs} | {c: c for c in ALIASES}
PREFIXES = sorted((v for v in ALIAS if " " in v), key=len, reverse=True)
ZONE_CODES = set(ZONES) - {"METRO RAILWAY KOLKATA"}
NOISE = {"LTD", "LIMITED", "LIMITTED", "PVT", "PRIVATE", "THE", "ERSTWHILE"}
ROMAN = {"I", "II", "III", "IV"}


def normalise(name: str) -> str:
    s = re.sub(r"[^A-Z0-9]+", " ", name.upper().replace("&", " AND ")).split()
    s = [w for w in s if w not in NOISE]
    while len(s) > 1 and s[-1] in ROMAN:
        s = s[:-1]
    if len(s) > 1 and "CIL" in s:
        s = [w for w in s if w != "CIL"]
    return " ".join("RAILWAY" if w == "RAILWAYS" else w for w in s).replace("COALFIELDS", "COAL FIELDS")


def canonical_agency(name) -> tuple[str | None, str]:
    """(canonical name, method) for one printed agency string; (None, 'missing') for no name."""
    if not isinstance(name, str) or not name.strip():
        return None, "missing"
    s = normalise(name)
    if not s or s in JUNK:
        return None, "invalid"
    if s in ALIAS:
        return ALIAS[s], "alias"
    br = re.search(r"\[([^\]]{2,})\]", name) or re.search(r"\(([A-Z][A-Z&-]{1,9})\)", name)
    if br and len(normalise(name.replace(br.group(0), " ")).split()) >= 2:
        code = normalise(br.group(1))
        return ALIAS.get(code, code), "bracket"
    w = s.split()
    if w[-1] == "MOR" or w[0] in RAIL_OFFICE:
        psu = next((p for p in RAIL_PSU if p in w), None)
        zone = next((t for t in reversed(w) if t in ZONE_CODES), None)
        if psu or zone:
            return psu or zone, "railway_office"
    if len(w) > 1 and (w[0] in EXECUTING or (w[1] in ("FOR", "OF") and w[0] in ALIAS)):
        return ALIAS.get(w[0], w[0]), "prefix"
    head = next((p for p in PREFIXES if s.startswith(p + " ")), None)
    if head:
        return ALIAS[head], "alias_prefix"
    return s, "normalised"


def _typo_only(a: str, b: str) -> bool:
    """The words that differ on both sides are a spelling variant of each other (or one side has none)."""
    ta, tb = set(a.split()), set(b.split())
    da, db = " ".join(sorted(ta - tb)), " ".join(sorted(tb - ta))
    return not da or not db or fuzz.ratio(da, db) >= TYPO_MIN


def build_map(obs: pd.DataFrame) -> pd.DataFrame:
    """Every distinct printed agency -> raw, canonical, method, n_projects, sector (its projects' modal sector)."""
    d = obs.dropna(subset=["agency"])
    m = d.groupby("agency").agg(n_projects=("project_key", "nunique"),
                                sector=("sector", lambda s: s.mode().iat[0] if s.notna().any() else None))
    m = m.reset_index().rename(columns={"agency": "raw"})
    got = m["raw"].map(canonical_agency)
    m["canonical"], m["method"] = got.str[0], got.str[1]
    # fuzzy: a normalised leftover joins the larger canonical name of its sector it matches
    size = m.groupby("canonical")["n_projects"].sum()
    for i in m.index[m["method"].eq("normalised")]:
        name, sector = m.at[i, "canonical"], m.at[i, "sector"]
        pool = [c for c in m.loc[m["sector"].eq(sector), "canonical"].dropna().unique()
                if c != name and size[c] > size[name]]
        best = max(pool, key=lambda c: (fuzz.token_set_ratio(name, c), size[c]), default=None)
        if best and fuzz.token_set_ratio(name, best) >= FUZZY_MIN and _typo_only(name, best):
            m.at[i, "canonical"], m.at[i, "method"] = best, "fuzzy"
    return m.sort_values(["n_projects", "raw"], ascending=[False, True], ignore_index=True)


# ------------------------------------------------------------------ matrix

def project_biases(obs: pd.DataFrame, master: pd.DataFrame, amap: pd.DataFrame, asof) -> pd.DataFrame:
    """One row per project with a known planned duration: canonical agency, sector, ministry, sanction date,
    schedule_bias, cost_bias."""
    o = obs[obs["period"] <= pd.Timestamp(asof)].sort_values(["project_key", "period"], kind="mergesort")
    g = o.groupby("project_key")
    p = pd.DataFrame({"sanction_date": g["sanction_date"].first(), "scheduled": g["scheduled_completion"].first(),
                      "anticipated": g["anticipated_completion"].last(), "original_cost": g["original_cost_cr"].first(),
                      "anticipated_cost": g["anticipated_cost_cr"].last()})
    mm = master.set_index("project_key")
    p["anticipated"] = p["anticipated"].fillna(mm["completed_period"].reindex(p.index))
    planned = months(p["scheduled"]) - months(p["sanction_date"])
    p["schedule_bias"] = (months(p["anticipated"]) - months(p["sanction_date"])) / planned.where(planned > 0) - 1
    p["cost_bias"] = p["anticipated_cost"] / p["original_cost"].where(p["original_cost"] > 0) - 1
    canon = amap.set_index("raw")["canonical"]
    p["agency"] = mm["agency"].reindex(p.index).map(canon)
    p["sector"], p["ministry"] = mm["sector"].reindex(p.index), mm["ministry"].reindex(p.index)
    p = p[p["schedule_bias"].notna() & p["agency"].notna()]
    return p.reset_index()[["project_key", "agency", "sector", "ministry", "sanction_date", "schedule_bias",
                            "cost_bias"]]


def shrink(raw, n, prior, k=SHRINK_K, below=SHRINK_N):
    """raw pulled toward prior with weight n / (n + k) when n < below; raw otherwise (or when prior is unknown)."""
    raw, n, prior = np.asarray(raw, float), np.asarray(n, float), np.asarray(prior, float)
    w = np.where(n < below, n / (n + k), 1.0)
    return np.where(np.isnan(prior), raw, w * raw + (1 - w) * prior), w


def median_ci(x: np.ndarray, rng) -> tuple[float, float]:
    """Bootstrap CI of the median (percentile, N_BOOT resamples)."""
    if len(x) < 2:
        return (float(x[0]), float(x[0])) if len(x) else (np.nan, np.nan)
    med = np.median(x[rng.integers(0, len(x), (N_BOOT, len(x)))], axis=1)
    return tuple(float(v) for v in np.quantile(med, [(1 - CI) / 2, (1 + CI) / 2]))


def _mode(s):
    s = s.dropna()
    return s.mode().iat[0] if len(s) else None


def matrix(proj: pd.DataFrame, cur: pd.DataFrame, names: pd.Series | None = None) -> pd.DataFrame:
    """Agency matrix from project_biases() rows and the current portfolio (project_key, agency canonical,
    anticipated_cost_cr)."""
    rng = np.random.default_rng(0)
    recent_from = proj["sanction_date"].max() - pd.DateOffset(years=TREND_YEARS)
    rows = []
    for agency, d in proj.groupby("agency", sort=True):
        r = {"agency": agency, "sector": _mode(d["sector"]), "ministry": _mode(d["ministry"]), "n_projects": len(d)}
        for col in ("schedule_bias", "cost_bias"):
            x = d[col].dropna().to_numpy(float)
            q25, med, q75 = np.quantile(x, [0.25, 0.5, 0.75]) if len(x) else (np.nan,) * 3
            lo, hi = median_ci(x, rng)
            r |= {f"{col}_raw": med, f"{col}_q25": q25, f"{col}_q75": q75, f"{col}_ci_lo": lo, f"{col}_ci_hi": hi}
        r["n_cost"] = int(d["cost_bias"].notna().sum())
        recent = d["sanction_date"] >= recent_from
        ok = recent.sum() >= TREND_MIN and (~recent).sum() >= TREND_MIN
        r["n_recent"] = int(recent.sum())
        r["trend"] = (d.loc[recent, "schedule_bias"].median() - d.loc[~recent, "schedule_bias"].median()
                      if ok else np.nan)
        rows.append(r)
    m = pd.DataFrame(rows)
    sector = proj.groupby("sector")[["schedule_bias", "cost_bias"]].median()
    for col in ("schedule_bias", "cost_bias"):
        prior = m["sector"].map(sector[col])
        m[f"sector_{col}"] = prior
        m[col], m["shrink_weight"] = shrink(m[f"{col}_raw"], m["n_projects"], prior)
    m["shrunk"] = m["n_projects"] < SHRINK_N
    m["hidden"] = m["n_projects"] < HIDE_N
    live = cur.dropna(subset=["agency"]).groupby("agency").agg(n_open=("project_key", "size"),
                                                                capital_cr=("anticipated_cost_cr", "sum"))
    m = m.set_index("agency").join(live, how="outer").rename_axis("agency").reset_index()
    m = m.fillna({"n_projects": 0, "n_open": 0, "capital_cr": 0.0, "hidden": True, "shrunk": True, "n_cost": 0,
                  "n_recent": 0})
    for c in ("n_projects", "n_open", "n_cost", "n_recent"):
        m[c] = m[c].astype("int64")
    m[["hidden", "shrunk"]] = m[["hidden", "shrunk"]].astype(bool)
    if names is not None:
        m["names"] = m["agency"].map(names)
    return m.sort_values(["hidden", "capital_cr", "n_projects"], ascending=[True, False, False], ignore_index=True)


def main(gold=GOLD, silver=SILVER):
    t0 = time.time()
    obs = pd.read_parquet(silver / "observations.parquet")
    master = pd.read_parquet(silver / "project_master.parquet")
    ptr = json.loads((gold / "predictions_latest.json").read_text(encoding="utf-8"))
    asof = pd.Timestamp(ptr["asof"])
    pred = pd.read_parquet(ROOT / ptr["path"], columns=["project_key", "agency", "anticipated_cost_cr"])
    amap = build_map(obs[obs["period"] <= asof])
    amap.to_csv(gold / "agency_map.csv", index=False)
    canon = amap.set_index("raw")["canonical"]
    names = amap.dropna(subset=["canonical"]).groupby("canonical")["raw"].agg(lambda s: " | ".join(s.head(3)))
    cur = pred.assign(agency=pred["agency"].map(canon))
    proj = project_biases(obs, master, amap, asof)
    m = matrix(proj, cur, names)
    m.insert(1, "asof", asof)
    m.to_parquet(gold / "agency_matrix.parquet", index=False)
    print(f"agency_map: {amap['raw'].nunique()} printed names -> {amap['canonical'].nunique()} canonical "
          f"({amap['method'].value_counts().to_dict()})")
    print(f"agency_matrix: {len(m)} agencies, {int((~m['hidden']).sum())} shown (n >= {HIDE_N}), "
          f"{len(proj)} dated projects, {time.time() - t0:.1f}s")
    with pd.option_context("display.width", 250):
        print(m.head(15)[["agency", "sector", "n_projects", "n_open", "capital_cr", "schedule_bias",
                          "schedule_bias_ci_lo", "schedule_bias_ci_hi", "cost_bias", "trend"]].round(3).to_string())
    return amap, m


if __name__ == "__main__":
    main()
