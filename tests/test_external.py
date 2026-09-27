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
