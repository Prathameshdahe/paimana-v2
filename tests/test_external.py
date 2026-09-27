import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    "funding": ["Work on 12 stations not started due to fund shortage.", "subsequent work on hold for want of financial closure",
                "Progress slow due to non-availability of funds"],
    "utility_shifting": ["Utility shifting.", "Shifting of 3 nos HT Lines pending"],
    "inter_agency": ["Delay in GAD approval by Railways", "NOC from AAI awaited", "held up pending approval from state Govt."],
    "law_order": ["Law & order problem", "The area is Naxal affected", "Stoppage of work due to agitation by local people"],
    "weather": ["Heavy monsoon affecting progress", "Flash flood in Jun-13", "works suspended due to lockdown for Covid 19"],
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
    assert s.str.contains(X.category_regex("forest_env"), case=False, regex=True).tolist() == [False, False, True, False]


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
    rows = pd.DataFrame({"project_key": "PRJ-1", "period": q, "remarks": remarks, "source_doc_id": [f"d{i}" for i in range(6)],
                         "source_page": 1, "report": [str(p) for p in q]})
    master = pd.DataFrame({"project_key": ["PRJ-1"], "state": "Bihar", "sector": "Railways", "completed_period": pd.NaT})
    seen, m = X.mentions(rows)
    ev = X.events(seen, m, master)
    assert ev.event_no.tolist() == [1, 2, 3]
    assert ev.n_quarters.tolist() == [2, 1, 1]
    assert ev.status.tolist() == ["closed", "closed", "open"]
    assert ev.source_doc_id.tolist() == ["d0", "d3", "d5"]
    done = X.events(seen, m, master.assign(completed_period=q[-1]))
    assert (done.status == "closed").all()                        # a completed project has no open events


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
