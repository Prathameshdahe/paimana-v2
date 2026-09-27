import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import bhoomi_rashi as B  # noqa: E402
from pipeline import external as X  # noqa: E402

CATEGORY_SAMPLES = {
    "land": ["Delay in land acquisition of Champa Sub station.", "3A notification issued for 12 villages",
             "Severe ROW problem & contractual issues", "Rehabilitation & resettlement problems",
             "Removal of encroachments by State Govt", "Out of 410 Ha, 276 Ha land is in physical possession"],
    "forest_env": ["Forest clearance awaited", "Stage II FC granted by MoEF in May-19", "EC received on 31.07.23",
                   "Sand mining ban by NGT", "Delay in CRZ approval", "Permission for felling of 6576 trees awaited",
                   "wildlife sanctuary clearance critical"],
    "litigation": ["Writ petition filed in Hon'ble High Court", "Contractor served Notice of Arbitration",
                   "Matter currently sub judice", "Efforts to get the stay vacated"],
    "contractor": ["The contract was terminated on 14.01.15", "Package to be re-tendered", "Agency under NCLT.",
                   "Slow progress by the contractor in laying of pipelines"],
    "funding": ["Work on 12 stations not started due to fund shortage.",
                "subsequent work on hold for want of financial closure",
                "Progress slow due to non-availability of funds"],
    "utility_shifting": ["Utility shifting.", "Shifting of 3 nos HT Lines pending"],
    "inter_agency": ["Delay in GAD approval by Railways", "NOC from AAI awaited",
                     "held up pending approval from state Govt."],
    "law_order": ["Law & order problem", "The area is Naxal affected",
                  "Stoppage of work due to agitation by local people"],
    "weather": ["Heavy monsoon affecting progress", "Flash flood in Jun-13",
                "works suspended due to lockdown for Covid 19"],
}
NEGATIVES = ["Milestones achieved/total: 0/7", "Land lease agreement signed", "Rainwater harvesting chamber",
             "All tagged Equipment like Pumps and Agitators received", "Work is in progress from all contractors",
             "It is being funded through Domestic loans & bonds", "Matter pursued for early clearance",
             "Reconciliation of expenditure done", "non forest area", "non-forest area"]


@pytest.mark.parametrize("cat", list(CATEGORY_SAMPLES))
def test_each_category_matches_its_samples(cat):
    s = pd.Series(CATEGORY_SAMPLES[cat])
    hit = s.str.contains(X.category_regex(cat), case=False, regex=True)
    assert hit.all(), s[~hit].tolist()


def test_template_and_benign_text_matches_no_category():
    s = pd.Series(NEGATIVES)
    for cat in X.TAXONOMY:
        hit = s.str.contains(X.category_regex(cat), case=False, regex=True)
        assert not hit.any(), (cat, s[hit].tolist())


def test_acronyms_are_case_sensitive():
    s = pd.Series(["pending LA at few stretches", "la la land", "Stage I FC is expected", "fc barcelona"])
    assert s.str.contains(X.category_regex("land"), case=False, regex=True).tolist() == [True, False, False, False]
    fe = s.str.contains(X.category_regex("forest_env"), case=False, regex=True)
    assert fe.tolist() == [False, False, True, False]


def test_subtype_authority_area_and_resolved():
    m = X.tag(pd.Series(["Stage II FC for 353.76 Ha forest land issued by MoEF on 13.01.2020",
                         "Forest land of 30 ha: proposal pending with DFO", "Writ petition filed in High Court"]))
    fe = m[m.category.eq("forest_env")].sort_values("text_id")
    assert fe.subtype.tolist() == ["forest_clearance", "forest_clearance"]
    assert fe.authority.tolist() == ["MoEFCC", "State Forest Dept"]
    assert fe.forest_area_ha.tolist() == [353.76, 30.0]
    assert fe.resolved.tolist() == [True, False]                  # 'pending' blocks the second
    lit = m[m.category.eq("litigation")].iloc[0]
    assert (lit.subtype, lit.authority) == ("court", "High Court")


def test_land_done_by_share_acquired_or_payment_made():
    m = X.tag(pd.Series([
        "Land Acquisition (Hect.):(Scope=1597.321/Physical progress=1583.963)=99.16% Earth Work (Lakh Cum.)",
        "Land Acquisition (Hect):(Scope:795.734 /Physical progress : 795.734)=100% Earthwork(Lakh cum): 50%",
        "Payment of compensation is made",
        "Possession of land has been taken",
        "Land Acquisition (Hect.):(Scope=500/Physical progress=300)=60%",
        "Land Acquisition completede Except for Sardarpur-jhabua section for which FLS is in progress",
    ]))
    land = m[m.category.eq("land")].drop_duplicates("text_id").sort_values("text_id")
    assert land.resolved.tolist() == [True, True, True, True, False, False]


def test_forest_area_skips_non_forest_and_other_clauses():
    s = pd.Series(["Forest land of 111.89 Ha and non-forest land of 648.86 Ha are under process of possession",
                   "Total land of 155.16 Ha is required to be acquired(PVT-152.059 Ha and Forest - 3.101)",
                   "Pvt land 132.344 hect, Govt land -16.404 hect and Forest land-71.72 hect acquired",
                   "Total land required is 1426.08 Ha including forest and nonforest land",
                   "Principal Chief Conservator of Forest 4", "Stage-I FC(323.49Ha): NOC for GMJJ of 152.60Ha"])
    assert X.forest_area(s).fillna(-1).tolist() == [111.89, 3.101, 71.72, -1, -1, 323.49]


def test_a_recommendation_tor_or_request_for_approval_is_not_done():
    s = pd.Series(["WBCZMA issued recommendation to Secretary, MoEF & CC for CRZ Approval",
                   "Environmental Clearance: ToR issued on 14.02.2022",
                   "All approvals received except for Forest Diversion Approval (Stage II)",
                   "Stage II FC issued by MoEF on 03.05.2021", "EMP for approval has been completed"])
    m = X.tag(s)
    assert m[m.category.eq("forest_env")].sort_values("text_id").resolved.tolist() == [False, False, False, True]


def test_free_text_strips_templates():
    s = pd.Series(["Milestones achieved/total: 0/7", "start: 2025-04",
                   "Milestones achieved/total: 2/7; Delay in land acquisition"])
    out = X.free_text(s)
    assert out.isna().tolist() == [True, True, False]
    assert "land acquisition" in out.iloc[2]


def test_events_split_on_gaps_and_open_only_at_the_end():
    q = pd.date_range("2021-01-01", periods=6, freq="QS").astype("datetime64[us]")
    remarks = ["Land acquisition pending", "Land acquisition pending", "Work going on at site",
               "Land acquisition pending", "Work going on at site", "Land acquisition pending"]
    rows = pd.DataFrame({"project_key": "PRJ-1", "period": q, "remarks": remarks,
                         "source_doc_id": [f"d{i}" for i in range(6)], "source_page": 1, "report": [str(p) for p in q]})
    master = pd.DataFrame({"project_key": ["PRJ-1"], "state": "Bihar", "sector": "Railways",
                           "completed_period": pd.NaT})
    seen, m = X.mentions(rows)
    ev = X.events(seen, m, master)
    assert ev.event_no.tolist() == [1, 2, 3]
    assert ev.n_quarters.tolist() == [2, 1, 1]
    assert ev.status.tolist() == ["closed", "closed", "open"]
    assert ev.source_doc_id.tolist() == ["d0", "d3", "d5"]
    done = X.events(seen, m, master.assign(completed_period=q[-1]))
    assert (done.status == "closed").all()                        # a completed project has no open events


def test_event_quote_comes_from_its_last_quarter_and_agrees_with_its_state():
    q = pd.date_range("2021-01-01", periods=2, freq="QS").astype("datetime64[us]")
    remarks = ["Stage-II forest clearance issued on 27/10/2021.",
               "Stage-II forest clearance issued on 27/10/2021. FC proposals for diversion of 101.60 Ha have been "
               "submitted online"]
    rows = pd.DataFrame({"project_key": "PRJ-1", "period": q, "remarks": remarks, "source_doc_id": "d",
                         "source_page": 1, "report": [str(p) for p in q]})
    master = pd.DataFrame({"project_key": ["PRJ-1"], "state": "Bihar", "sector": "Railways",
                           "completed_period": pd.NaT})
    ev = X.events(*X.mentions(rows), master).iloc[0]
    assert (ev.status, ev.resolved, ev.n_quarters) == ("open", False, 2)
    assert ev.evidence.startswith("FC proposals for diversion")    # not the shorter 'issued' sentence
    done = X.events(*X.mentions(rows.iloc[:1]), master).iloc[0]
    assert (done.status, done.evidence) == ("closed", "Stage-II forest clearance issued on 27/10/2021.")


SCEN = pd.read_csv(X.EXTERNAL / "parivesh_fc_scenarios.csv")


def profile(**kw):
    p = {"linear": False, "mining": False, "violation": False, "ofc": False, "defence": False, "survey": False,
         "area_ha": float("nan")}
    return {**p, **kw}


def test_band_parser():
    assert X.band(">5 & <=40") == (5.0, 40.0)
    assert X.band("<=5") == (float("-inf"), 5.0)
    assert X.band(">40") == (40.0, float("inf"))
    assert X.band(">1 & <=5") == (1.0, 5.0)
    assert X.band("<=0.1") == (float("-inf"), 0.1)
    assert X.band("Any") == (float("-inf"), float("inf"))
    assert X.band("NA (<=100 trees/<=25 boreholes-per-10sqkm/<=80 shotholes-per-sqkm)") is None
    assert X.band("Within 100 km") is None


def test_every_scenario_category_has_a_rule():
    cats = set(SCEN.project_category.fillna(""))
    special = {"Survey", "Security/Defence Strategic Linear Infrastructure", "Defence-Related Infrastructure",
               "Defence-Related Infrastructure in LWE District", "Public Utility (road/rail-side amenities) in LWE"}
    assert cats - special <= set(X.CATEGORY)


def test_linear_area_unknown_worst_case_is_moefcc():
    p = profile(linear=True)
    m = X.scenarios_for(SCEN, p)
    assert m.scenario_id.tolist() == ["1A", "1F", "2_main", "2_linear_gt40", "2_DH", "2F", "4_main", "4_govt_all",
                                      "4_DH", "5_DH_gt40"]              # no survey, exemption, mining or violation rows
    s = X.fc_summary(m, p)
    assert (s["fc_expected_complexity"], s["fc_worst_complexity"], s["fc_likely_authority"]) == (3.0, 7, "MoEFCC")
    assert s["fc_gates"] == "PSC + FAC + site inspection"
    assert s["fc_evidence"] == ("linear, area unknown: up to MoEFCC with PSC + FAC + site inspection "
                                "(scenario 5_DH_gt40)")


def test_non_linear_50_ha_and_mining_3_ha():
    m = X.scenarios_for(SCEN, profile(area_ha=50.0))
    assert m.scenario_id.tolist() == ["1A", "1F", "2F", "5_main", "5_DH_gt40"]
    assert X.fc_summary(m, profile(area_ha=50.0))["fc_evidence"].endswith("(scenario 5_main)")
    m = X.scenarios_for(SCEN, profile(mining=True, area_ha=3.0))
    assert m.scenario_id.tolist() == ["1A", "7_main"]
    assert X.fc_summary(m, profile(mining=True, area_ha=3.0))["fc_expected_complexity"] == 4.0


def test_violation_only_matches_violation_rows():
    m = X.scenarios_for(SCEN, profile(linear=True, violation=True))
    assert m.scenario_id.tolist() == ["3F_violation", "5_violation", "7_violation"]


def test_shape_and_mining_rules():
    sector = pd.Series(["Roads & Highways", "Railways", "Railways", "Power", "Power", "Petroleum & Natural Gas",
                        "Petroleum & Natural Gas", "Telecommunications", "Telecommunications", "Water Resources",
                        "Urban Development & Housing", "Coal", "Railways", "Roads & Highways", "Railways"])
    name = pd.Series(["Widening of NH-161A", "Rewari-Rohtak", "Rail Coach Factory Raebareli",
                      "Transmission system associated with Rampur HEP", "Khurja super thermal power project",
                      "Paradip-Hyderabad product pipeline", "Paradip refinery", "BharatNet optical fibre network",
                      "GSM equipment of 799000 lines", "Madhya Ganga canal Phase-II", "Pune Metro Rail Project",
                      "Kerandari opencast project", "Kodingamali bauxite mines to Singaram railway station",
                      "Dedicated Port road to Krishnapatnam Port", "Nangal Dam-Talwara new broad gauge line"])
    s = X.shape(sector, name)
    assert s.tolist() == ["Linear", "Linear", "Non-Linear", "Linear", "Non-Linear", "Linear", "Non-Linear", "Linear",
                          "Non-Linear", "Linear", "Linear", "Non-Linear", "Linear", "Linear", "Linear"]
    mine = X.mining(sector, name, s.eq("Linear"))
    assert mine[mine].index.tolist() == [11]                        # the rail line to a mine is not a mining lease


def test_nh_id_normalises_the_land_table_names():
    s = pd.Series(["161A", "161 (New)", "160 Ext.", "6 Ext", "NH53", "353 C", "353-I", "NE4", "361 New",
                   "Greenfield Expressway", "No Yet to be Assigned", "Newly Proposed"])
    assert X.nh_id(s).tolist()[:9] == ["161A", "161", "160", "6", "53", "353C", "353I", "NE4", "361"]
    assert X.nh_id(s).iloc[9:].isna().all()


def test_nh_from_text_patterns_old_new_and_chainage():
    s = pd.Series(["Sarsam - Kothari of NH-161A - 2L PS from Km.33/00 to 90/00", "NH 161 section", "NH161",
                   "National Highway 161", "NH No. 161", "NH 85 (OLD NH 49)", "NH-11A(NEW NH-148)",
                   "NH-17 & 48 (KARNATAKA)", "NH548 D from KM 132/600", "NH- 965DD upto Junction of NH-66 Ch-22700",
                   "NH-4B & 4 KM 12", "4L from Km 95.400 Udaipura to Km 147.450", "Mumbai-Nagpur NE-4 pkg",
                   "Up-gradation to 2-lane for NH- 965DD from Pacharal-Mandangad-Mhapral-Rajewadi Upto Junction of "
                   "NH-66 Ch-22700 to 75100 Km", "of Kolde to Visarwadi Near Junction with NH-6 section of NH 752G total",
                   "Duttalur at NH-565 Junction to Kavali", "from Jn. with NH 30 near Bela"])
    assert X.nh_from_text(s).fillna("-").tolist() == ["161A", "161", "161", "161", "161", "85", "148", "17;48", "548D",
                                                      "965DD", "4B", "-", "NE4", "965DD", "752G", "-", "-"]


LA = pd.DataFrame({
    "state": "MAHARASHTRA", "highway_name": ["161 (New)", "161 (New)", "166", "Greenfield Highway"],
    "districts_touched": ["NANDED", "HINGOLI|NANDED", "Satara", "PUNE"],
    "num_parcels": [100, 50, 10, 5], "total_area_ha": [10.0, 5.0, 1.0, 0.5],
    "acquisition_complexity_score": [4, 1, 0, 2], "notif_span_days": [900, 100, 0, 10],
    "first_notif_date": ["2019-01-10", "2022-05-01", "2020-01-01", "2021-01-01"],
    "last_notif_date": ["2021-06-30", "2022-08-01", "2020-01-01", "2021-01-11"]})


def test_link_land_district_first_then_nh_and_unknown_elsewhere():
    master = pd.DataFrame({
        "project_key": ["P1", "P2", "P3", "P4", "P5", "P6"],
        "sector": ["Roads & Highways"] * 5 + ["Railways"],
        "state": ["Maharashtra", "Maharashtra", "Karnataka", "Maharashtra", "Multi-State", "Maharashtra"],
        "project_name": ["Hingoli bypass on NH-161", "Widening of NH 161", "NH-161 Karnataka section",
                         "Nanded to Loha", "Satara - Belgaum NH-166", "Hingoli NH-161 rail overbridge"],
        "codes_seen": None})
    st = X.stretches(LA)
    land, pairs = X.link_land(master, st)
    r = land.set_index("project_key")
    assert r.la_match_method.tolist() == ["nh_district", "nh_only", "no_land_data_for_state", "no_nh_in_name",
                                          "nh_district", "not_road"]
    assert r.loc["P1", "la_stretches"] == 1 and r.loc["P1", "la_parcels"] == 50         # only the Hingoli stretch
    assert r.loc["P2", "la_stretches"] == 2 and r.loc["P2", "la_complexity_max"] == 4
    assert r.la_state.tolist() == ["clear", "flagged", "unknown", "unknown", "clear", "unknown"]
    assert r.loc["P2", "la_evidence"] == "NH-161: 150 parcels over 3.6 years of notifications, complexity 4/5"
    assert r.loc["P1", "la_evidence"].startswith("NH-161 (Hingoli): 50 parcels")
    by_nh, by_d = X.land_tables(st)
    assert by_nh.set_index("nh").loc["161", "parcels"] == 150
    assert by_d.set_index(["nh", "district"]).loc[("161", "NANDED"), "stretches"] == 2


def test_la_complexity_reproduces_every_real_stretch():
    la = pd.read_csv(X.EXTERNAL / "land_acquisition_maharashtra.csv")
    got = B.la_complexity(la["num_districts"], la["notif_span_days"], la["num_parcels"], la["total_area_ha"])
    assert len(la) == 347 and got.tolist() == la["acquisition_complexity_score"].tolist()


EXPORT_HEADER = ["State", " highway name ", "Chainage", "DISTRICT", "Sub-District", "Village", "Survey No.",
                 "Area (Ha)", "Publish Date"]
EXPORT_ROWS = [["GUJARAT", "48", "10.000 - 30.000", "SURAT", "Olpad", "Kim", "12/A", "1.5", "15/01/2019"],
               ["", "", "", "", "", "", "13", "2.25", "20/03/2020"],
               ["", "", "", "BHARUCH", "Ankleshwar", "Kosamba", "7", "", "01/02/2022"],
               ["", "48", "30.000 - 30.000", "BHARUCH", "Ankleshwar", "Kosamba", "8", "0.5", "05/05/2021"]]


def write_export(path, header=EXPORT_HEADER, rows=EXPORT_ROWS, th=False):
    """A Bhoomi Rashi-style export: an HTML table saved as .xls, header as its first row (th: a real header row),
    group cells blank."""
    tr = lambda cells, td="td": "<tr>" + "".join(f"<{td}>{c}</{td}>" for c in cells) + "</tr>"   # noqa: E731
    body = tr(header, "th" if th else "td") + "".join(tr(r) for r in rows)
    path.write_text("<html><body><table>" + body + "</table></body></html>", encoding="utf-8")
    return path


def test_parse_and_aggregate_a_bhoomi_rashi_export(tmp_path):
    p = B.parse_bhoomi_rashi(write_export(tmp_path / "gujarat.xls"))
    assert len(p) == 4 and p["state"].eq("GUJARAT").all()                        # forward-filled
    assert p["district"].tolist() == ["SURAT", "SURAT", "BHARUCH", "BHARUCH"]
    assert p["publish_date"].iloc[1] == pd.Timestamp("2020-03-20")                # dd/mm/YYYY
    assert p["chainage_start_km"].iloc[0] == 10.0 and p["chainage_end_km"].iloc[0] == 30.0
    th = B.parse_bhoomi_rashi(write_export(tmp_path / "th.xls", th=True))       # numeric NH column read as 48.0
    assert th["highway_name"].eq("48").all() and th["survey_no"].tolist() == ["12/A", "13", "7", "8"]
    s = B.aggregate_stretches(p)
    assert s.columns.tolist() == pd.read_csv(X.EXTERNAL / "land_acquisition_maharashtra.csv", nrows=1).columns.tolist()
    r = s.set_index("chainage_raw").loc["10.000 - 30.000"]
    assert (r.districts_touched, r.num_districts, r.num_subdistricts, r.num_villages, r.num_parcels) == (
        "BHARUCH|SURAT", 2, 2, 2, 3)
    assert (r.total_area_ha, r.avg_area_per_parcel_ha, r.chainage_length_km, r.parcels_per_km) == (3.75, 1.875, 20.0,
                                                                                                    0.15)
    assert (r.first_notif_date, r.last_notif_date, r.notif_span_days) == ("2019-01-15", "2022-02-01", 1113)
    assert r.acquisition_complexity_score == 3                                    # 2 districts, span >= 1 and 3 years
    z = s.set_index("chainage_raw").loc["30.000 - 30.000"]
    assert pd.isna(z.parcels_per_km) and z.acquisition_complexity_score == 0
    with pytest.raises(ValueError, match=r"lacks \['publish_date'\].*columns found"):
        B.parse_bhoomi_rashi(write_export(tmp_path / "bad.xls", EXPORT_HEADER[:-1], [r[:-1] for r in EXPORT_ROWS]))


def test_load_land_reads_every_state_and_dedupes(tmp_path):
    LA.assign(chainage_raw=["0 - 9", "9 - 12", "0 - 4", "0 - 2"]).to_csv(tmp_path / "land_acquisition_maharashtra.csv",
                                                                       index=False)
    (tmp_path / "bhoomi_rashi").mkdir()
    write_export(tmp_path / "bhoomi_rashi" / "gujarat.xls")
    B.aggregate_stretches(B.parse_bhoomi_rashi(tmp_path / "bhoomi_rashi" / "gujarat.xls")).assign(
        state="Gujarat").to_csv(tmp_path / "land_acquisition_gujarat.csv", index=False)   # same stretches again
    la = X.load_land(tmp_path)
    assert len(la) == len(LA) + 2
    assert X.state_key(la["state"]).value_counts().to_dict() == {"MAHARASHTRA": 4, "GUJARAT": 2}


def test_link_land_needs_the_state_of_the_stretch():
    guj = pd.DataFrame({"state": "Gujarat", "highway_name": ["48"], "districts_touched": ["SURAT"],
                        "num_parcels": [300], "total_area_ha": [25.0], "acquisition_complexity_score": [2],
                        "notif_span_days": [10], "first_notif_date": ["2020-01-01"], "last_notif_date": ["2020-01-11"]})
    st = X.stretches(pd.concat([LA, guj], ignore_index=True))
    master = pd.DataFrame({
        "project_key": ["G1", "G2", "B1", "M1", "U1"], "sector": "Roads & Highways",
        "state": ["Gujarat", "Gujarat", "Bihar", "Multi-State", "Maharashtra"],
        "project_name": ["Six laning of NH-48 Surat section", "Widening of NH-161", "Four laning of NH-161 in Bihar",
                         "NH-48 Vadodara - Surat - Mumbai", "Six laning of NH-48 near Pune"], "codes_seen": None})
    land, _ = X.link_land(master, st)
    r = land.set_index("project_key")
    assert r.la_match_method.tolist() == ["nh_district", "nh_not_in_table", "no_land_data_for_state", "nh_district",
                                          "nh_not_in_table"]
    assert r.la_state.tolist() == ["clear", "unknown", "unknown", "clear", "unknown"]
    assert r.loc["G1", "la_parcels"] == 300 and r.loc["G1", "la_evidence"].startswith("NH-48 (Surat): 300 parcels")


MOCK = X.EXTERNAL / "mock"      # SYNTHETIC fixtures (mock/README.md): formula checks only, never model inputs


def test_composite_matches_the_teammates_v0_formula():
    m = pd.read_csv(MOCK / "external_factor_mock_v0.csv")
    raw = 0.5 * m["fc_complexity_score"] / 7 + 0.5 * m["la_complexity_score"] / 5
    assert (raw - m["external_factor_composite_score"]).abs().max() < 0.001
    # our composite on the mock rows with land known equals the mock score; without land the mock counts land as 0
    fc = pd.DataFrame({"project_key": m["project_id"], "fc_expected_complexity": m["fc_complexity_score"].astype(float),
                       "fc_area_ha": float("nan"), "fc_violation": m["fc_violation_flag"].eq(1)})
    land = pd.DataFrame({"project_key": m["project_id"], "la_linked": m["la_required"].eq(1),
                         "la_complexity_max": m["la_complexity_score"].astype("Int64"), "la_nh": "1"})
    c = X.external_composite(fc, land)
    both = m["la_required"].eq(1)
    assert (c["external_factor_score"] - m["external_factor_composite_score"])[both].abs().max() < 0.001
    assert c["coverage"][both].eq("fc+la").all() and c["coverage"][~both].eq("fc_only").all()


def test_composite_coverage_never_counts_unknown_land_as_zero():
    fc = pd.DataFrame({"project_key": ["A", "B", "C"], "fc_expected_complexity": [3.0, 3.0, 7.0],
                       "fc_area_ha": [float("nan"), 12.5, float("nan")], "fc_violation": [False, False, True]})
    land = pd.DataFrame({"project_key": ["A", "B", "C"], "la_linked": [True, False, False],
                         "la_complexity_max": pd.array([4, None, None], dtype="Int64"),
                         "la_nh": ["161;161A", None, None]})
    c = X.external_composite(fc, land).set_index("project_key")
    assert c["coverage"].tolist() == ["fc+la", "fc_only", "fc_only"]
    assert c["external_factor_score"].round(4).tolist() == [round(0.5 * 3 / 7 + 0.5 * 4 / 5, 4), round(3 / 7, 4), 1.0]
    assert c["la_component"].isna().tolist() == [False, True, True]
    assert c.loc["A", "ext_score_evidence"] == ("forest 3/7 (rulebook, area unknown) + land 4/5 (NH-161, NH-161A, "
                                                "Bhoomi Rashi)")
    assert c.loc["B", "ext_score_evidence"] == "forest 3/7 (rulebook, 12.5 ha); land unknown"
    assert c.loc["C", "ext_score_evidence"] == "forest 7/7 (rulebook, area unknown, violation); land unknown"
