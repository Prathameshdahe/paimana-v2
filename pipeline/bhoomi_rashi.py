"""
Bhoomi Rashi highway-register exports -> parcels -> NH stretches (docs/EXTERNAL_FACTORS_GUIDE.md sections 3 and 5).

The whole-state export from bhoomirashi.gov.in has an .xls extension but is an HTML table whose first row is the
header. The group columns (State to Village) are printed only on the first row of each group. aggregate_stretches
turns the parcels into one row per (state, highway, chainage) in the schema of
raw/external/land_acquisition_maharashtra.csv, which pipeline/external.py load_land reads with every other state.
"""
import re

import numpy as np
import pandas as pd

# normalised header (lower case, letters only) -> column; a few spellings seen in exports and in the guide
HEADER = {"state": "state", "statename": "state", "highwayname": "highway_name", "highway": "highway_name",
          "nhno": "highway_name", "chainage": "chainage", "district": "district", "districtname": "district",
          "subdistrict": "sub_district", "subdistrictname": "sub_district", "tehsil": "sub_district",
          "taluka": "sub_district", "village": "village", "villagename": "village", "surveyno": "survey_no",
          "surveynumber": "survey_no", "area": "area", "areaha": "area", "areainha": "area",
          "publishdate": "publish_date", "publicationdate": "publish_date"}
GROUP = ["state", "highway_name", "chainage", "district", "sub_district", "village"]
REQUIRED = GROUP + ["survey_no", "area", "publish_date"]
STRETCH_COLS = ["state", "highway_name", "chainage_raw", "chainage_start_km", "chainage_end_km", "chainage_length_km",
                "districts_touched", "num_districts", "num_subdistricts", "num_villages", "num_parcels",
                "total_area_ha", "avg_area_per_parcel_ha", "parcels_per_km", "area_ha_per_km", "first_notif_date",
                "last_notif_date", "notif_span_days", "acquisition_complexity_score"]


def _key(name):
    return re.sub(r"[^a-z]", "", str(name).lower())


def parse_bhoomi_rashi(path, state=None):
    """One Bhoomi Rashi export -> one row per parcel: state, highway_name, chainage, district, sub_district,
    village, survey_no, area (ha, numeric), publish_date, chainage_start_km, chainage_end_km.

    publish_date is the Section-3 gazette notification date (dd/mm/YYYY): when the intent to acquire was published,
    NOT when the land was possessed or the compensation settled. state fills or overrides the State column. Headers
    are matched case-insensitively ignoring spaces and punctuation ('Sub District', 'Sub-District', 'Area (ha)')."""
    df = pd.read_html(path, flavor="lxml")[0]
    if not any(HEADER.get(_key(c)) == "highway_name" for c in df.columns):     # header printed as the first row
        df = df.iloc[1:].set_axis(df.iloc[0].to_numpy(), axis=1)
    cols = {c: HEADER[_key(c)] for c in df.columns if _key(c) in HEADER}
    df = df[list(cols)].set_axis(list(cols.values()), axis=1)
    df = df.loc[:, ~df.columns.duplicated()]
    if state is not None:
        df["state"] = state
    missing = [c for c in REQUIRED if c not in df]
    if missing:
        raise ValueError(f"{path}: Bhoomi Rashi export lacks {missing}; columns found: {list(cols) or 'none'} "
                         f"(pass state= if only State is missing)")
    df = df.reset_index(drop=True)
    for c in GROUP + ["survey_no"]:     # read_html turns an all-number column with blanks into floats: 48.0 -> '48'
        df[c] = df[c].map(lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip(),
                          na_action="ignore").replace("", np.nan)
    df[GROUP] = df[GROUP].ffill()
    df = df[df["survey_no"].notna()].reset_index(drop=True)                     # spacer and total rows
    df["area"] = pd.to_numeric(df["area"], errors="coerce")
    df["publish_date"] = pd.to_datetime(df["publish_date"].astype("str").str.strip(), format="%d/%m/%Y",
                                        errors="coerce")
    ch = df["chainage"].str.split(r"\s*-\s*", n=1, expand=True, regex=True).reindex(columns=[0, 1])
    df["chainage_start_km"] = pd.to_numeric(ch[0], errors="coerce")
    df["chainage_end_km"] = pd.to_numeric(ch[1], errors="coerce")
    return df


def la_complexity(num_districts, span_days, parcels, area_ha):
    """The guide's 0-5 acquisition complexity: +1 each for more than one district, a notification span of a year or
    more, of three years or more, 200 parcels or more, 20 ha or more."""
    return ((num_districts > 1).astype("int64") + (span_days >= 365).astype("int64")
            + (span_days >= 3 * 365).astype("int64") + (parcels >= 200).astype("int64")
            + (area_ha >= 20).astype("int64"))


def aggregate_stretches(parcels):
    """Parcels -> one row per (state, highway_name, chainage) in the land_acquisition_maharashtra.csv schema.
    avg_area_per_parcel_ha is the mean of the parcels with an area; per-km values are null on a zero-length
    chainage."""
    g = parcels.groupby(["state", "highway_name", "chainage"], sort=True, dropna=False)
    s = g.agg(chainage_start_km=("chainage_start_km", "first"), chainage_end_km=("chainage_end_km", "first"),
              districts_touched=("district", lambda v: "|".join(sorted(set(v)))),
              num_districts=("district", "nunique"), num_subdistricts=("sub_district", "nunique"),
              num_villages=("village", "nunique"), num_parcels=("survey_no", "size"),
              total_area_ha=("area", "sum"), avg_area_per_parcel_ha=("area", "mean"),
              first=("publish_date", "min"), last=("publish_date", "max")).reset_index()
    s = s.rename(columns={"chainage": "chainage_raw"})
    s["chainage_length_km"] = (s["chainage_end_km"] - s["chainage_start_km"]).round(3)
    length = s["chainage_length_km"].where(s["chainage_length_km"] != 0)
    s["total_area_ha"] = s["total_area_ha"].round(4)
    s["avg_area_per_parcel_ha"] = s["avg_area_per_parcel_ha"].round(4)
    s["parcels_per_km"] = (s["num_parcels"] / length).round(2)
    s["area_ha_per_km"] = (s["total_area_ha"] / length).round(4)
    s["first_notif_date"] = s["first"].dt.strftime("%Y-%m-%d")
    s["last_notif_date"] = s["last"].dt.strftime("%Y-%m-%d")
    s["notif_span_days"] = (s["last"] - s["first"]).dt.days.astype("Int64")
    s["acquisition_complexity_score"] = la_complexity(s["num_districts"], s["notif_span_days"].fillna(0),
                                                      s["num_parcels"], s["total_area_ha"])
    return s[STRETCH_COLS]
