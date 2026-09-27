"""
Merge the three performance-review extractor families into analysis-ready CSVs.

Inputs  dataset/clean/_parts/{perf_2015_18,perf_2018_21,perf_2025_26}/
        perf.csv, perf_detail.csv, manifest.csv   (written by pipeline/extract/*.py)
Outputs dataset/clean/reference/perf_indicator_map.csv      printed (sector, group, indicator, unit) -> indicator_key
        dataset/clean/performance/performance_annexure.csv   every Annexure-A row + key, canonical units, computed %
        dataset/clean/performance/performance_sector_monthly.csv  one row per (report_month, indicator_key)
        dataset/clean/performance/performance_detail.csv     every detail-table cell + table_no, row_label_clean
        dataset/clean/reference/perf_coverage.csv            one row per month Apr 2015 - Mar 2027

Rules
- Printed values are never overwritten. Canonical-unit copies (*_canon) and computed
  percentages (*_computed) are separate columns. Blank = not printed, never 0.
- Units: MT = million tonnes, BU = billion kWh, MCM = million cubic metres,
  Lakh = 100,000 (passengers, as in the Highlights table).
- Computed %: growth = (actual / prev_year_actual - 1) * 100 when both are > 0;
  var-over-target = (actual / target - 1) * 100 only where the source printed a target
  measure (% variation or % achievement) for the row: the source leaves it blank where the
  target covers only part of a total (steel/coal totals), and a computed value would be wrong.
- dq_flags = extractor dq_note + report-level flags from the manifest (report_partial,
  report_truncated, scope_excludes:<sector>, source_title_month:<YYYY-MM>) +
  printed_pct_mismatch (printed % vs computed differ by > 0.6 points) +
  components_sum_mismatch (total != sum of printed parts by > 0.5%) +
  target_pct_not_printed (target printed, source gives no target %; do not derive one) +
  not_comparable_across_years (key whose definition changed, see the map note).
- Sector monthly: growth % printed where printed, else computed; target % printed, else the
  FY2025-26 printed '% achievement' - 100, never computed. pct_source names the source of each
  % field (printed | computed | printed_achievement). April reports print only the month
  block, so cum_* = month values there (pct_source 'from_month_*', dq_flags cum_from_april_month).
- Sector monthly keeps keys with comparable_across_years or is_sector_headline.

Run from repo root:  python pipeline/build_clean_performance.py
"""
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "extract"))
from common import DATASET, PARTS, fiscal_year  # noqa: E402

CLEAN = PARTS.parent
OUT_PERF = CLEAN / "performance"
OUT_REF = CLEAN / "reference"
FAMILIES = ["perf_2015_18", "perf_2018_21", "perf_2025_26"]
SECTORS = ["Power", "Coal", "Steel", "Cement", "Fertilizers", "Petroleum & Natural Gas", "Roads",
           "Railways", "Shipping & Ports", "Civil Aviation", "Telecommunications"]
NUM = ["annual_target", "target", "actual", "prev_year_actual"]
PCT_TOL = 0.6
# Months with no performance review in the source folder (task brief). Anything else
# missing means an extractor dropped a report -> assert.
KNOWN_MISSING = ({"2015-11", "2017-09", "2019-04", "2025-04", "2025-05", "2025-08"}
                 | {str(p) for p in pd.period_range("2021-04", "2025-03", freq="M")}
                 | {str(p) for p in pd.period_range("2026-02", "2027-03", freq="M")})

# ---------------------------------------------------------------------------
# indicator keys
# ---------------------------------------------------------------------------
# key: (sector, display name, canonical unit, comparable_across_years, is_sector_headline, note)
T, F = True, False
KEYS = {
    "power_total": ("Power", "Power generation - total", "BU", T, T,
                    "Headline: matches Highlights 'Power (BU)'. FY2015-21 'Total'; FY2025-26 'Total (I + II)' = non-renewable + renewable; both include Bhutan import."),
    "power_thermal": ("Power", "Thermal power generation", "BU", T, F, ""),
    "power_nuclear": ("Power", "Nuclear power generation", "BU", T, F, ""),
    "power_hydro": ("Power", "Hydro power generation", "BU", T, F,
                    "Separate Annexure row only in the FY2015-21 layout; the FY2025-26 Annexure folds hydro into renewable (power_renewable_incl_hydro)."),
    "power_bhutan_import": ("Power", "Power import from Bhutan", "BU", T, F, ""),
    "power_renewable": ("Power", "Renewable power generation (excl. large hydro)", "BU", T, F,
                        "FY2015-21 layout only; hydro is a separate row. Not the same measure as power_renewable_incl_hydro."),
    "power_renewable_incl_hydro": ("Power", "Renewable power generation (incl. hydro)", "BU", T, F,
                                   "FY2025-26 Annexure 'Power Generation: Renewable Energy' = renewable + hydro (detail Table 1 shows them separately)."),
    "power_non_renewable": ("Power", "Non-renewable power generation (thermal + nuclear + Bhutan import)", "BU", T, F,
                            "FY2025-26 layout subtotal."),
    "coal_total": ("Coal", "Coal production - total (excl. lignite)", "MT", T, T,
                   "Headline: matches Highlights 'Coal (MT) excluding Lignite'. FY2015-21 'Total'; FY2025-26 row 'Coal Production (MT)'."),
    "coal_cil": ("Coal", "Coal production - Coal India Ltd", "MT", T, F, ""),
    "coal_sccl": ("Coal", "Coal production - Singareni Collieries", "MT", T, F, ""),
    "coal_others": ("Coal", "Coal production - others / captive", "MT", T, F,
                    "Label 'Others' (FY2015-21) became 'Others/Captive' (FY2025-26)."),
    "lignite_total": ("Coal", "Lignite production", "MT", T, F, "FY2025-26 layout only."),
    "coal_lignite_total": ("Coal", "Coal + lignite production", "MT", T, F, "FY2025-26 'Total (I + II)'."),
    "steel_finished_total": ("Steel", "Finished steel production - total", "MT", F, T,
                             "Headline: 'Total (I + II)' = main + major (secondary) producers in every layout; equals Highlights 'Steel (Finished Steel)'. "
                             "Series break: from the Jun 2019 report the source restated the series (JSWL and secondary producers revised down), "
                             "so the level drops ~22% (Jun 2018 actual 10.721 MT vs Jun 2019 prev-year 8.333 MT); do not compare levels across report month 2019-06."),
    "steel_main_producers": ("Steel", "Finished steel - main producers", "MT", F, F,
                             "Producer list changed: FY2015-21 SAIL, RINL, TSL, ESSAR, JSWL, JSPL; FY2025-26 SAIL, RINL, TSL GROUP, AMNS GROUP, JSWL GROUP, JSPL, NSL."),
    "steel_secondary_producers": ("Steel", "Finished steel - major (secondary) producers", "MT", F, F,
                                  "Residual of total minus main producers, so it moves with the main-producer list."),
    "steel_sail": ("Steel", "Finished steel - SAIL", "MT", T, F, ""),
    "steel_rinl": ("Steel", "Finished steel - RINL", "MT", T, F, ""),
    "steel_tsl": ("Steel", "Finished steel - Tata Steel", "MT", F, F,
                  "'Tata Steel (TSL)' (printed 'Tata Steet') in FY2015-21; 'TSL GROUP' in FY2025-26."),
    "steel_amns_essar": ("Steel", "Finished steel - ESSAR / AMNS group", "MT", F, F,
                         "'ESSAR' in FY2015-21; 'AMNS GROUP' in FY2025-26."),
    "steel_jsw": ("Steel", "Finished steel - JSW", "MT", F, F, "'JSWL' in FY2015-21; 'JSWL GROUP' in FY2025-26."),
    "steel_jspl": ("Steel", "Finished steel - JSPL", "MT", T, F, ""),
    "steel_nsl": ("Steel", "Finished steel - NSL", "MT", T, F, "FY2025-26 layout only."),
    "cement_total": ("Cement", "Cement production - total", "MT", T, T, "Headline: matches Highlights 'Cement (MT)'."),
    "cement_large_plants": ("Cement", "Cement production - large plants", "MT", T, F, "FY2025-26 layout only."),
    "cement_mini_plants": ("Cement", "Cement production - mini plants", "MT", T, F, "FY2025-26 layout only."),
    "fertilizer_total": ("Fertilizers", "Fertilizer production - total", "MT", F, T,
                         "Headline, definition changed: FY2015-21 total = nitrogen + phosphate; FY2025-26 total = nitrogen + phosphate + urea. The Highlights table uses N+P only in all years."),
    "fertilizer_nitrogen": ("Fertilizers", "Fertilizer production - nitrogen (N)", "MT", T, F, ""),
    "fertilizer_phosphate": ("Fertilizers", "Fertilizer production - phosphate (P)", "MT", T, F, ""),
    "fertilizer_urea": ("Fertilizers", "Urea production", "MT", T, F, "FY2025-26 layout only."),
    "crude_oil_production": ("Petroleum & Natural Gas", "Crude oil production", "MT", T, T,
                             "Headline: first Petroleum row of the Highlights table (the sector has no printed total). Printed 'MT' (FY2015-21) and 'MMT' (FY2025-26) are both million tonnes."),
    "refinery_production": ("Petroleum & Natural Gas", "Refinery production", "MT", T, F,
                            "FY2015-21 layout only. Not the same measure as refinery_crude_processed."),
    "refinery_crude_processed": ("Petroleum & Natural Gas", "Crude oil processed (refinery throughput)", "MT", T, F,
                                 "FY2025-26 layout only; replaces 'Refinery Prod.' in the Annexure and Highlights."),
    "natural_gas_production": ("Petroleum & Natural Gas", "Natural gas production", "MCM", T, F, ""),
    "roads_nhai_km": ("Roads", "NHAI - highway widening and strengthening", "Kms", T, T,
                      "Headline: first Roads row of the Highlights table ('NHAI (KM)'). Label wording changed in FY2025-26 ('Widening to two/four/six/eight lanes and strengthening'); the Highlights table reports both as one series."),
    "roads_state_pwd_bro_km": ("Roads", "State PWD & BRO roads - total", "Kms", T, F,
                               "'Total of (b)' (FY2015-21) / 'State PWD and Border Road Organisation (BRO)' subtotal (FY2025-26); = Highlights 'State PWD & BRO (KM)'."),
    "roads_state_pwd_bro_two_lane_km": ("Roads", "State PWD & BRO - widening to two lanes", "Kms", T, F, ""),
    "roads_state_pwd_bro_multi_lane_km": ("Roads", "State PWD & BRO - widening to four/six/eight lanes", "Kms", T, F, ""),
    "roads_state_pwd_bro_strengthening_km": ("Roads", "State PWD & BRO - strengthening of weak pavement", "Kms", T, F, ""),
    "railways_freight_mt": ("Railways", "Railway revenue-earning freight traffic", "MT", T, T,
                            "Headline: matches Highlights 'Railway Revenue Earning Freight Traffic (MT)'. 'goods' (FY2015-21) / 'Freight' (FY2025-26)."),
    "railways_passengers_mn": ("Railways", "Railway passenger traffic", "Million", T, F, "FY2025-26 layout only."),
    "railways_new_line_km": ("Railways", "Railway new line, gauge conversion and doubling", "Kms", T, F, "FY2025-26 layout only."),
    "ports_major_cargo_mt": ("Shipping & Ports", "Cargo handled at major ports", "MT", T, T,
                             "Headline: matches Highlights 'Cargo Handled at Major Ports (MT)'."),
    "ports_coal_mt": ("Shipping & Ports", "Coal handled at major ports", "MT", T, F, "From Mar 2016; replaced 'Coastal Shipment of Coal'."),
    "ports_coastal_coal_mt": ("Shipping & Ports", "Coastal shipment of coal", "MT", T, F, "Apr 2015 - Feb 2016 only."),
    "ports_pol_crude_mt": ("Shipping & Ports", "POL crude handled at major ports", "MT", T, F, "FY2025-26 layout only; printed in tonnes."),
    "ports_container_mt": ("Shipping & Ports", "Container cargo handled at major ports", "MT", T, F, "FY2025-26 layout only; printed in tonnes."),
    "aviation_dom_passengers": ("Civil Aviation", "Passengers handled at domestic terminals", "Lakh", T, T,
                                "Headline: in the Highlights table of every layout (the sector has no printed total). Printed in numbers."),
    "aviation_intl_passengers": ("Civil Aviation", "Passengers handled at international terminals", "Lakh", T, F, "Printed in numbers."),
    "aviation_export_cargo_t": ("Civil Aviation", "Export cargo handled at airports", "Tonnes", T, F,
                                "FY2025-26 layout prints the actual only."),
    "aviation_import_cargo_t": ("Civil Aviation", "Import cargo handled at airports", "Tonnes", T, F,
                                "FY2025-26 layout prints the actual only."),
    "aviation_aircraft_movements": ("Civil Aviation", "Aircraft movements (incl. general aviation)", "'000 Numbers", T, F, "FY2025-26 layout only."),
    "telecom_connections_net_add": ("Telecommunications", "Net new telephone connections (wireline + wireless)", "'000 Numbers", T, T,
                                    "Headline: Annexure sector total 'Total connections (ii+iii)', a monthly flow like the Highlights telecom rows. FY2015-21 only: the FY2025-26 Annexure prints subscriber stocks instead (telecom_subscribers_total)."),
    "telecom_switching_capacity_net_add": ("Telecommunications", "Net addition in switching capacity", "'000 Lines", T, F, "FY2015-21 layout only."),
    "telecom_wireline_net_add": ("Telecommunications", "Net new wireline (fixed) connections", "'000 Numbers", T, F, "FY2015-21 layout only."),
    "telecom_wireless_net_add": ("Telecommunications", "Net new wireless (WLL + GSM) connections", "'000 Numbers", T, F, "FY2015-21 layout only."),
    "telecom_subscribers_total": ("Telecommunications", "Telephone subscribers - total", "Million", T, F,
                                  "FY2025-26 layout only; a stock (month rows only), not comparable with the net-addition flows."),
    "telecom_wired_subscribers": ("Telecommunications", "Telephone subscribers - wired", "Million", T, F, "FY2025-26 layout only; stock."),
    "telecom_wireless_subscribers": ("Telecommunications", "Telephone subscribers - wireless", "Million", T, F, "FY2025-26 layout only; stock."),
}

# (printed unit, canonical unit) -> multiplier
SCALE = {("BU", "BU"): 1, ("MT", "MT"): 1, ("MMT", "MT"): 1, ("'000 Tonnes", "MT"): 1e-3,
         ("Tonnes", "MT"): 1e-6, ("Tonnes", "Tonnes"): 1, ("Numbers", "Lakh"): 1e-5,
         ("'000 Numbers", "'000 Numbers"): 1, ("'000 Lines", "'000 Lines"): 1, ("Kms", "Kms"): 1,
         ("MCM", "MCM"): 1, ("Million", "Million"): 1}

LABEL_QUIRK = re.compile(r"Steet|pavemen\b|Capacit\b|telephon\b|\(MT$")  # typos / clipping seen in print


def indicator_key(sector, group, ind):
    """Printed Annexure-A labels -> indicator_key (None if unknown). Order matters."""
    g, i = group.lower(), ind.lower()
    t = g + " | " + i
    has = lambda *ws: any(w in i for w in ws)  # noqa: E731
    total_12 = re.search(r"i\s*\+\s*ii\b", i)
    if sector == "Power":
        for w, k in [("thermal", "power_thermal"), ("nuclear", "power_nuclear"), ("hydro", "power_hydro"),
                     ("bhutan", "power_bhutan_import"), ("non-renewable", "power_non_renewable"),
                     ("power generation: renewable", "power_renewable_incl_hydro"), ("renewable", "power_renewable")]:
            if w in i:
                return k
        return "power_total" if i.startswith("total") else None
    if sector == "Coal":
        if "lignite" in i:
            return "lignite_total"
        if total_12:
            return "coal_lignite_total"
        for w, k in [("coal india", "coal_cil"), ("singareni", "coal_sccl"), ("others", "coal_others")]:
            if w in i:
                return k
        return "coal_total" if i.startswith("total") or "coal production" in i else None
    if sector == "Steel":
        if total_12:
            return "steel_finished_total"
        if "secondary" in i:
            return "steel_secondary_producers"
        for pat, k in [(r"\bsail\b", "steel_sail"), (r"\brinl\b", "steel_rinl"), (r"\btata\b|\btsl\b", "steel_tsl"),
                       (r"\bessar\b|\bamns\b", "steel_amns_essar"), (r"\bjswl?\b", "steel_jsw"),
                       (r"\bjspl\b", "steel_jspl"), (r"\bnsl\b", "steel_nsl")]:
            if re.search(pat, i):
                return k
        return "steel_main_producers" if "main producer" in t else None
    if sector == "Cement":
        return "cement_large_plants" if "large" in i else "cement_mini_plants" if "mini" in i \
            else "cement_total" if "cement production" in i else None
    if sector == "Fertilizers":
        for w, k in [("nitrogen", "fertilizer_nitrogen"), ("phosphate", "fertilizer_phosphate"), ("urea", "fertilizer_urea")]:
            if w in i:
                return k
        return "fertilizer_total" if i.startswith("total") or "fertilisers production" in i else None
    if sector == "Petroleum & Natural Gas":
        return "refinery_crude_processed" if "processed" in i else "crude_oil_production" if "crude oil prod" in i \
            else "refinery_production" if "refinery" in i else "natural_gas_production" if "natural gas" in i else None
    if sector == "Roads":
        if "nhai" in t:
            return "roads_nhai_km"
        for w, k in [("two lanes", "roads_state_pwd_bro_two_lane_km"), ("four/six/eight", "roads_state_pwd_bro_multi_lane_km"),
                     ("strengthening", "roads_state_pwd_bro_strengthening_km"), ("pavemen", "roads_state_pwd_bro_strengthening_km")]:
            if w in i:
                return k
        return "roads_state_pwd_bro_km" if "total" in i or "state pwd" in i else None
    if sector == "Railways":
        return "railways_freight_mt" if has("freight", "goods") else "railways_passengers_mn" if "passenger" in i \
            else "railways_new_line_km" if has("gauge", "new line") else None
    if sector == "Shipping & Ports":
        for w, k in [("coastal", "ports_coastal_coal_mt"), ("coal", "ports_coal_mt"), ("pol crude", "ports_pol_crude_mt"),
                     ("container", "ports_container_mt"), ("cargo", "ports_major_cargo_mt")]:
            if w in i:
                return k
        return None
    if sector == "Civil Aviation":
        for w, k in [("export", "aviation_export_cargo_t"), ("import", "aviation_import_cargo_t"),
                     ("international", "aviation_intl_passengers"), ("domestic", "aviation_dom_passengers"),
                     ("aircraft", "aviation_aircraft_movements")]:
            if w in i:
                return k
        return None
    if sector == "Telecommunications":
        for w, k in [("switching", "telecom_switching_capacity_net_add"), ("wireline", "telecom_wireline_net_add"),
                     ("total connections", "telecom_connections_net_add"), ("total telephone subscribers", "telecom_subscribers_total"),
                     ("wired subscribers", "telecom_wired_subscribers"), ("wireless subscribers", "telecom_wireless_subscribers"),
                     ("wireless", "telecom_wireless_net_add")]:
            if w in i:
                return k
    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def load(name):
    frames = []
    for fam in FAMILIES:
        df = pd.read_csv(PARTS / fam / f"{name}.csv", dtype=str, keep_default_na=False)
        df.insert(0, "family", fam)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def num(s):
    return pd.to_numeric(s.replace("", None), errors="raise").astype(float)


def sig(x):
    """Round float noise from unit scaling (7774 * 1e-3 = 7.774000000000001)."""
    return x.map(lambda v: float(f"{v:.12g}") if pd.notna(v) else v)


def flags(*cols):
    """Row-wise ';'-join of flag strings/lists, order kept, duplicates dropped."""
    out = []
    for parts in zip(*cols):
        seen = []
        for p in parts:
            for t in (p if isinstance(p, list) else str(p or "").split(";")):
                t = t.strip()
                if t and t != "nan" and t not in seen:
                    seen.append(t)
        out.append(";".join(seen))
    return out


def report_flags(manifest):
    """source_file -> list of report-level dq flags derived from manifest status/notes."""
    res = {}
    for r in manifest.itertuples():
        fl, notes = [], r.notes or ""
        if r.status != "ok":
            fl.append(f"report_{r.status}")
        if re.search(r"no text layer|not extracted \(no OCR\)", notes):
            fl.append("report_truncated")
        fl += [f"scope_excludes:{m}" for m in re.findall(r"no (\w+) rows in Annexure-A", notes)]
        fl += [f"source_title_month:{m}" for m in re.findall(r"title says (\d{4}-\d{2}) but file name", notes)]
        res[r.source_file] = fl
    return res


def boolstr(s):
    return s.map({True: "true", False: "false", "True": "true", "False": "false"})


# ---------------------------------------------------------------------------
# detail-label cleaning
# ---------------------------------------------------------------------------
LABEL_FIXES = [  # applied after generic cleaning; typos / breaks seen in print
    (r"^Tata Steet\b", "Tata Steel"),
    (r"^Small Hyde$", "Small Hydel"),
    (r"^V\.O\.Chidambaran ?ar\b.*$", "V.O.Chidambaranar (Tuticorin)"),
    (r"^Others \(TISCO.*$", "Others (TISCO, IISCO, DVC)"),
    (r"WLL=GSM", "WLL+GSM"),
    (r"\(\(", "("),
    (r"(?i)\(heavy oil\)", "(Heavy Oil)"),
    (r"^weak pavement to four/six/eight lanes \(Kms\.\)$",
     "Widening/ Strengthening/ existing weak pavement to four/six/eight lanes (Kms.)"),
]
ENUM = re.compile(r"^(?:\(?(?:i{1,3}|iv|vi{0,3}|ix|x)\)|\(?[a-h]\)|[A-H]\.)\s+")


def clean_label(s):
    s = " ".join(str(s).split())
    s = re.sub(r"\s*[#$@*†‡]+\s*", " ", s).strip()      # footnote marks
    s = re.sub(r"([a-z])- ([a-z])", r"\1\2", s)          # hyphen line-wrap
    s = ENUM.sub("", s)                                  # i) a) B. enumerators
    s = re.sub(r"\([^()]*\)?", lambda m: re.sub(r"\s*\+\s*", "+", m[0]), s)  # (A + B) -> (A+B)
    s = re.sub(r"([\w)])\(", r"\1 (", s)
    for pat, rep in LABEL_FIXES:
        s = re.sub(pat, rep, s)
    return " ".join(s.split()).replace("( ", "(").replace(" )", ")")


def table_name(title):
    m = re.match(r"(?i)^\s*table\s*-?\s*\d+\s*[A-Z]?\s*:?\s*(.*?)(?:\s+-\s+.*)?$", title)
    return m[1] if m else title


def clean_labels(detail):
    """row_label_clean: generic clean, then complete labels clipped mid-parenthesis when
    exactly one longer balanced label of the same (sector, table) starts with them."""
    base = detail[["sector", "table_title", "row_label"]].drop_duplicates()
    base["clean"] = base.row_label.map(clean_label)
    base["scope"] = base.sector + "|" + base.table_title.map(table_name)
    balanced = base[base.clean.str.count(r"\(") == base.clean.str.count(r"\)")]
    pool = balanced.groupby("scope").clean.agg(lambda s: sorted(set(s))).to_dict()

    def complete(r):
        if r.clean.count("(") <= r.clean.count(")"):
            return r.clean
        cands = [c for c in pool.get(r.scope, []) if c.startswith(r.clean) and c != r.clean]
        return cands[0] if len(cands) == 1 else r.clean
    base["row_label_clean"] = base.apply(complete, axis=1)
    return detail.merge(base[["sector", "table_title", "row_label", "row_label_clean"]],
                        on=["sector", "table_title", "row_label"], how="left", validate="m:1")


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build_map(perf):
    cols = ["sector", "indicator_group", "indicator", "unit"]
    m = (perf.groupby(cols).agg(n_rows=("report_month", "size"), first_report_month=("report_month", "min"),
                                last_report_month=("report_month", "max")).reset_index())
    m["indicator_key"] = [indicator_key(*r) for r in m[["sector", "indicator_group", "indicator"]].itertuples(index=False)]
    bad = m[m.indicator_key.isna()]
    assert bad.empty, f"unmapped Annexure labels:\n{bad[cols].to_string()}"
    meta = m.indicator_key.map(KEYS)
    assert (meta.str[0] == m.sector).all(), "indicator_key sector mismatch"
    m["indicator_name"] = meta.str[1]
    m["unit_canonical"] = meta.str[2]
    m["scale_to_canonical"] = [SCALE.get((u, c)) for u, c in zip(m.unit, m.unit_canonical)]
    assert m.scale_to_canonical.notna().all(), m[m.scale_to_canonical.isna()][cols + ["unit_canonical"]]
    m["is_sector_headline"] = meta.str[4].astype(bool)
    m["comparable_across_years"] = meta.str[3].astype(bool)
    m["note"] = [n + ("; " if n else "") + "printed label clipped/typo in source" if LABEL_QUIRK.search(i) else n
                 for n, i in zip(meta.str[5], m.indicator)]
    m["_o"] = m.sector.map(SECTORS.index)
    m = m.sort_values(["_o", "indicator_key", "indicator_group", "indicator", "unit"]).drop(columns="_o")
    return m[["sector", "indicator_group", "indicator", "unit", "indicator_key", "indicator_name", "unit_canonical",
              "scale_to_canonical", "is_sector_headline", "comparable_across_years", "note",
              "n_rows", "first_report_month", "last_report_month"]].reset_index(drop=True)


COMPONENTS = {  # total -> parts, summed over whichever parts a layout prints
    "power_total": ["power_thermal", "power_nuclear", "power_hydro", "power_bhutan_import", "power_renewable",
                    "power_renewable_incl_hydro"],
    "power_non_renewable": ["power_thermal", "power_nuclear", "power_bhutan_import"],
    "coal_total": ["coal_cil", "coal_sccl", "coal_others"],
    "coal_lignite_total": ["coal_total", "lignite_total"],
    "steel_finished_total": ["steel_main_producers", "steel_secondary_producers"],
    "steel_main_producers": ["steel_sail", "steel_rinl", "steel_tsl", "steel_amns_essar", "steel_jsw", "steel_jspl", "steel_nsl"],
    "cement_total": ["cement_large_plants", "cement_mini_plants"],
    "fertilizer_total": ["fertilizer_nitrogen", "fertilizer_phosphate", "fertilizer_urea"],
    "roads_state_pwd_bro_km": ["roads_state_pwd_bro_two_lane_km", "roads_state_pwd_bro_multi_lane_km",
                               "roads_state_pwd_bro_strengthening_km"],
    "telecom_connections_net_add": ["telecom_wireline_net_add", "telecom_wireless_net_add"],
    "telecom_subscribers_total": ["telecom_wired_subscribers", "telecom_wireless_subscribers"],
}
RECON = {}  # filled by components_mismatch: column -> (checked, mismatched)


def components_mismatch(a):
    """True on total rows whose printed target/actual/prev differ from the sum of their
    printed parts by more than 0.5% (source arithmetic; values kept as printed)."""
    bad = pd.Series(False, index=a.index)
    for c in ["target", "actual", "prev_year_actual"]:
        v = a[c + "_canon"]
        chk = mis = 0
        for tot, parts in COMPONENTS.items():
            is_tot = a.indicator_key == tot
            s = v[a.indicator_key.isin(parts)].groupby([a.report_month, a.period_type]).sum(min_count=1)
            tv = v[is_tot]
            sv = pd.Series(s.reindex(pd.MultiIndex.from_arrays([a.report_month[is_tot], a.period_type[is_tot]])).values,
                           index=tv.index)
            both = tv.notna() & sv.notna()
            off = both & ((tv - sv).abs() > 0.005 * tv.abs() + 1e-9)
            chk, mis = chk + int(both.sum()), mis + int(off.sum())
            bad[off[off].index] = True
        RECON[c] = (chk, mis)
    return bad


def build_annexure(perf, imap, rflags):
    a = perf.merge(imap[["sector", "indicator_group", "indicator", "unit", "indicator_key", "indicator_name",
                         "unit_canonical", "scale_to_canonical", "comparable_across_years"]],
                   on=["sector", "indicator_group", "indicator", "unit"], how="left", validate="m:1")
    assert a.indicator_key.notna().all()
    for c in NUM:
        a[c + "_canon"] = sig(num(a[c]) * a.scale_to_canonical)
    t, act, prev = num(a.target), num(a.actual), num(a.prev_year_actual)
    vt, ach, gr = num(a.pct_var_target), num(a.pct_achievement), num(a.pct_var_prev_year)
    ok = ~a.dq_note.str.contains("placeholder", regex=False)
    g_raw, v_raw = (act / prev - 1) * 100, (act / t - 1) * 100
    a["growth_pct_computed"] = g_raw.where((prev > 0) & (act > 0) & ok).round(2)
    # The source leaves the target % blank where the target covers only part of the row
    # (e.g. steel/coal totals: only some producers have targets). A value computed there
    # would be wrong, so compute only where the source printed a target-variation measure.
    a["pct_var_target_computed"] = v_raw.where((t > 0) & (act >= 0) & ok & (vt.notna() | ach.notna())).round(2)
    mism = (((gr - g_raw).abs() > PCT_TOL) & (prev > 0)) | (((vt - v_raw).abs() > PCT_TOL) & (t > 0)) | \
           (((ach - act / t * 100).abs() > PCT_TOL) & (t > 0))
    a["dq_flags"] = flags(a.dq_note, a.source_file.map(rflags),
                          mism.map({True: "printed_pct_mismatch", False: ""}),
                          components_mismatch(a).map({True: "components_sum_mismatch", False: ""}),
                          # target printed but no target %: usually a target covering only part of the row
                          ((t > 0) & act.notna() & vt.isna() & ach.isna()).map({True: "target_pct_not_printed", False: ""}),
                          (~a.comparable_across_years).map({True: "not_comparable_across_years", False: ""}))
    a["is_total"] = boolstr(a.is_total)
    a["_o"] = a.sector.map(SECTORS.index)
    a["_p"] = a.period_type.map({"month": 0, "cumulative": 1})
    assert a._p.notna().all(), a.period_type.unique()
    a = a.sort_values(["report_month", "_o", "indicator_key", "_p"]).drop(columns=["_o", "_p", "scale_to_canonical",
                                                                                     "comparable_across_years"])
    front = [c for c in perf.columns if c != "dq_note"]
    return a[front + ["dq_note", "indicator_key", "indicator_name", "unit_canonical"] + [c + "_canon" for c in NUM]
             + ["growth_pct_computed", "pct_var_target_computed", "dq_flags"]].reset_index(drop=True)


def build_monthly(ann, imap):
    keys = imap[imap.comparable_across_years | imap.is_sector_headline].drop_duplicates("indicator_key")
    head = keys.set_index("indicator_key").is_sector_headline
    x = ann[ann.indicator_key.isin(keys.indicator_key)].copy()
    for c in ["pct_var_prev_year", "pct_var_target", "pct_achievement", "growth_pct_computed"]:
        x[c] = num(x[c])
    x["growth"] = x.pct_var_prev_year.fillna(x.growth_pct_computed)
    x["growth_src"] = x.pct_var_prev_year.notna().map({True: "printed", False: "computed"}).where(x.growth.notna(), "")
    # target %: printed; else the FY2025-26 layout's printed '% achievement' - 100; never
    # computed (the source omits it where the target covers only part of the row)
    x["vtarget"] = x.pct_var_target.fillna((x.pct_achievement - 100).round(2))
    x["vtarget_src"] = x.pct_var_target.notna().map({True: "printed", False: "printed_achievement"}) \
        .where(x.vtarget.notna(), "")
    k = ["report_month", "indicator_key"]
    val = ["target_canon", "actual_canon", "prev_year_actual_canon", "growth", "vtarget", "growth_src", "vtarget_src"]
    common_cols = ["fiscal_year", "sector", "indicator_name", "unit_canonical", "source_file"]
    mo = x[x.period_type == "month"][k + common_cols + ["period_end", "annual_target_canon", "dq_flags"] + val]
    cu = x[x.period_type == "cumulative"][k + common_cols + ["period_start", "period_end", "annual_target_canon", "dq_flags"] + val]
    mo = mo.rename(columns={c: "m_" + c for c in mo.columns if c not in k})
    cu = cu.rename(columns={c: "c_" + c for c in cu.columns if c not in k})
    j = mo.merge(cu, on=k, how="outer", validate="1:1")
    for c in common_cols:
        j[c] = j["m_" + c].fillna(j["c_" + c])
        assert (j["m_" + c].isna() | j["c_" + c].isna() | (j["m_" + c] == j["c_" + c])).all(), c
    april = j.report_month.str.endswith("-04") & j.c_period_end.isna() & j.m_period_end.notna()
    for v in val:  # April reports: cumulative (April..April) = month
        j.loc[april, "c_" + v] = j.loc[april, "m_" + v]
    j.loc[april, "c_period_start"] = j.loc[april, "m_period_end"]
    j.loc[april, "c_period_end"] = j.loc[april, "m_period_end"]
    for s in ["c_growth_src", "c_vtarget_src"]:
        j.loc[april & (j[s] != "") & j[s].notna(), s] = "from_month_" + j.loc[april, s]
    fields = [("month_growth_pct", "m_growth_src"), ("month_var_target_pct", "m_vtarget_src"),
              ("cum_growth_pct", "c_growth_src"), ("cum_var_target_pct", "c_vtarget_src")]
    j["pct_source"] = [";".join(f"{f}={s}" for f, s in zip([f for f, _ in fields], r) if isinstance(s, str) and s)
                       for r in j[[s for _, s in fields]].itertuples(index=False)]
    j["dq_flags"] = flags(j.m_dq_flags.fillna(""), j.c_dq_flags.fillna(""),
                          april.map({True: "cum_from_april_month", False: ""}))
    out = pd.DataFrame({
        "report_month": j.report_month, "fiscal_year": j.fiscal_year, "sector": j.sector,
        "indicator_key": j.indicator_key, "indicator_name": j.indicator_name, "unit": j.unit_canonical,
        "is_sector_headline": boolstr(j.indicator_key.map(head)),
        "data_month": j.m_period_end.fillna(j.c_period_end),
        "month_target": j.m_target_canon, "month_actual": j.m_actual_canon,
        "month_prev_year_actual": j.m_prev_year_actual_canon,
        "month_growth_pct": j.m_growth, "month_var_target_pct": j.m_vtarget,
        "cum_period_start": j.c_period_start, "cum_period_end": j.c_period_end,
        "cum_target": j.c_target_canon, "cum_actual": j.c_actual_canon,
        "cum_prev_year_actual": j.c_prev_year_actual_canon,
        "cum_growth_pct": j.c_growth, "cum_var_target_pct": j.c_vtarget,
        "annual_target": j.c_annual_target_canon.fillna(j.m_annual_target_canon),
        "source_file": j.source_file, "pct_source": j.pct_source, "dq_flags": j.dq_flags})
    out["_o"] = out.sector.map(SECTORS.index)
    return out.sort_values(["report_month", "_o", "indicator_key"]).drop(columns="_o").reset_index(drop=True)


def build_detail(detail, rflags):
    d = detail.copy()
    alias = {s.lower(): s for s in SECTORS}
    alias.update({"fertilisers": "Fertilizers", "petroleum": "Petroleum & Natural Gas", "shipping": "Shipping & Ports",
                  "ports": "Shipping & Ports", "telecom": "Telecommunications", "aviation": "Civil Aviation"})
    d["sector"] = d.sector.map(lambda s: alias.get(s.strip().lower(), s))
    bad = set(d.sector) - set(SECTORS)
    assert not bad, f"detail sectors outside vocabulary: {bad}"
    d["table_no"] = pd.to_numeric(d.table_title.str.extract(r"(?i)^\s*table\s*-?\s*(\d+)")[0]).astype("Int64")
    d = clean_labels(d)
    d["dq_flags"] = flags(d.dq_note, d.source_file.map(rflags))
    d["_o"] = range(len(d))  # keep printed row order within a page
    d = d.sort_values(["report_month", "source_file", "page", "_o"],
                      key=lambda s: pd.to_numeric(s, errors="coerce") if s.name == "page" else s,
                      kind="mergesort").drop(columns="_o")
    cols = list(detail.columns)
    cols.insert(cols.index("table_title") + 1, "table_no")
    cols.insert(cols.index("row_label") + 1, "row_label_clean")
    return d[cols + ["dq_flags"]].reset_index(drop=True)


def build_coverage(man, ann, det, rflags):
    months = [str(p) for p in pd.period_range("2015-04", "2027-03", freq="M")]
    by_month = man.set_index("report_period")
    assert by_month.index.is_unique, "two performance reports for one month"
    other = []  # other families' files kept in the Performance Monitoring folder (e.g. PAIMANA flash reports)
    for mf in sorted(PARTS.glob("*/manifest.csv")):
        if mf.parent.name not in FAMILIES:
            o = pd.read_csv(mf, dtype=str, keep_default_na=False)
            other.append(o[o.source_file.str.startswith("Performance Monitoring/")])
    other = pd.concat(other) if other else pd.DataFrame(columns=["source_file", "report_type", "report_period", "status"])
    pdfs = {p.relative_to(DATASET).as_posix() for p in (DATASET / "Performance Monitoring").rglob("*.pdf")}
    unaccounted = pdfs - set(man.source_file) - set(other.source_file)
    assert not unaccounted, f"PDFs in Performance Monitoring not in any manifest: {sorted(unaccounted)}"
    na, nd = ann.groupby("report_month").size(), det.groupby("report_month").size()
    rows = []
    for m in months:
        oth = other[other.report_period == m]
        extra = "; ".join(f"Performance Monitoring folder holds a {r.report_type} project report for this month "
                          f"({r.source_file}; status {r.status} in the project extract)" for r in oth.itertuples())
        if m in by_month.index:
            r = by_month.loc[m]
            notes = "; ".join(filter(None, [";".join(rflags[r.source_file]), r.notes, extra]))
            rows.append([m, fiscal_year(m), r.source_file, r.status, int(na.get(m, 0)), int(nd.get(m, 0)), notes])
        else:
            rows.append([m, fiscal_year(m), "", "missing", 0, 0,
                         "; ".join(filter(None, ["no performance review report in the source folder", extra]))])
    return pd.DataFrame(rows, columns=["report_month", "fiscal_year", "source_file", "status",
                                       "n_annexure_rows", "n_detail_rows", "notes"])


def main():
    perf, detail, man = load("perf"), load("perf_detail"), load("manifest")
    rflags = report_flags(man)
    # parts are internally consistent with their manifests
    cnt = perf.groupby("source_file").size()
    assert (man.set_index("source_file").rows_perf.astype(int) == cnt.reindex(man.source_file).fillna(0).values).all()
    assert set(perf.source_file) <= set(man.source_file) and set(detail.source_file) <= set(man.source_file)

    imap = build_map(perf)
    ann = build_annexure(perf, imap, rflags)
    monthly = build_monthly(ann, imap)
    april = monthly.dq_flags.str.contains("cum_from_april_month", regex=False)
    det = build_detail(detail, rflags)
    cov = build_coverage(man, ann, det, rflags)

    OUT_PERF.mkdir(parents=True, exist_ok=True)
    OUT_REF.mkdir(parents=True, exist_ok=True)
    imap_out = imap.copy()
    for c in ["is_sector_headline", "comparable_across_years"]:
        imap_out[c] = boolstr(imap_out[c])
    imap_out["scale_to_canonical"] = imap_out.scale_to_canonical.map(lambda v: f"{v:.10f}".rstrip("0").rstrip("."))
    imap_out.to_csv(OUT_REF / "perf_indicator_map.csv", index=False, encoding="utf-8")
    ann.to_csv(OUT_PERF / "performance_annexure.csv", index=False, encoding="utf-8")
    monthly.to_csv(OUT_PERF / "performance_sector_monthly.csv", index=False, encoding="utf-8")
    det.to_csv(OUT_PERF / "performance_detail.csv", index=False, encoding="utf-8")
    cov.to_csv(OUT_REF / "perf_coverage.csv", index=False, encoding="utf-8")

    # ---- checks -----------------------------------------------------------
    assert len(ann) == len(perf) and len(det) == len(detail)
    assert not imap.duplicated(["sector", "indicator_group", "indicator", "unit"]).any()
    assert not ann.duplicated(["report_month", "indicator_key", "period_type"]).any()
    assert not monthly.duplicated(["report_month", "indicator_key"]).any()
    assert not det.duplicated(["source_file", "table_title", "row_group", "row_label", "column_label",
                               "period_start", "period_end"]).any()
    heads = imap.drop_duplicates("indicator_key").query("is_sector_headline").groupby("sector").indicator_key.nunique()
    assert (heads == 1).all() and set(heads.index) == set(imap.sector), heads
    assert monthly.groupby(["report_month", "sector"]).is_sector_headline.apply(lambda s: (s == "true").sum()).le(1).all()
    for c in NUM + ["pct_var_target", "pct_var_prev_year", "pct_achievement"]:  # printed values untouched
        assert abs(num(ann[c]).sum() - num(perf[c]).sum()) < 1e-6 * max(1, abs(num(perf[c]).sum())), c
    assert abs(num(det.value).sum() - num(detail.value).sum()) < 1e-6 * abs(num(detail.value).sum())
    inc = ann.indicator_key.isin(monthly.indicator_key.unique())
    for per, col in [("month", "month_actual"), ("cumulative", "cum_actual")]:
        s_ann = ann[inc & (ann.period_type == per)].actual_canon.sum()
        s_mon = monthly[col].sum() - (monthly.loc[april, "month_actual"].sum() if per == "cumulative" else 0)
        assert abs(s_ann - s_mon) < 1e-6 * max(1, abs(s_ann)), (per, s_ann, s_mon)
    assert (monthly.loc[april, "cum_actual"].fillna(-1) == monthly.loc[april, "month_actual"].fillna(-1)).all()
    assert (monthly.cum_actual.isna() | monthly.cum_period_end.notna()).all()
    assert len(cov) == 144 and cov.report_month.is_unique
    assert cov.n_annexure_rows.sum() == len(ann) and cov.n_detail_rows.sum() == len(det)
    assert set(man.source_file) == set(cov.source_file) - {""}
    missing = set(cov[cov.status == "missing"].report_month)
    assert missing <= KNOWN_MISSING, f"reports missing that should exist: {sorted(missing - KNOWN_MISSING)}"
    lagged = monthly[monthly.data_month != monthly.report_month]
    assert lagged.dq_flags.str.contains("carried_forward").all()
    for c, (chk, mis) in RECON.items():  # parts sum to totals (a mapping error breaks this wholesale)
        assert chk > 0 and mis <= 0.02 * chk, (c, chk, mis)

    print(f"map: {len(imap)} printed labels -> {imap.indicator_key.nunique()} keys "
          f"({(~imap.drop_duplicates('indicator_key').comparable_across_years).sum()} not comparable)")
    print(f"annexure: {len(ann)} rows, printed_pct_mismatch {ann.dq_flags.str.contains('printed_pct_mismatch').sum()}, "
          f"components checked/mismatched {RECON}")
    print(f"sector_monthly: {len(monthly)} rows, {monthly.indicator_key.nunique()} keys, "
          f"{monthly.report_month.nunique()} report months, {int(april.sum())} April cum fills, {len(lagged)} lagged")
    print(f"detail: {len(det)} rows, {det.row_label.nunique()} labels -> {det.row_label_clean.nunique()} clean")
    print(f"coverage: {cov.status.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
