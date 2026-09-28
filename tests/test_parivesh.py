"""pipeline/parivesh.py: user-agency privacy, timeline parsing, stage at asof and the project roll-up (no network)."""
import pandas as pd

from pipeline import parivesh as P

ASOF = pd.Timestamp("2026-07-01")

TIMELINE = """<html><body>
<p>(i). Proposal No. : FP/MP/RAIL/41734/2019 (ii). Name of Project for which Forest Land is required : Katni-Singrauli
Railway Doubling Project. (iii). Short narrative ... (iv). State : Madhya Pradesh (v). Category of the Project :
Railway (vi). Shape ... (vii). Area of forest land proposed for diversion(in ha.): 72.8362</p>
<table><tr><td>Proposal No.</td><td>Submitted by User Agency</td><td>Division</td><td>Circle</td><td>Nodal Office</td>
<td>State Government</td><td>Regional Office</td><td>Stage-I Approval on</td><td>Stage-II Approval on</td></tr>
<tr><td>FP/MP/RAIL/41734/2019</td><td>25/08/2019</td><td>Sanjay Tiger Reserve :08/06/2020</td><td>Sidhi: 01/04/2021</td>
<td>Madhya Pradesh:30/04/2021</td><td>Madhya Pradesh:01/06/2021</td><td>Bhopal:23/06/2021</td></tr></table>
<span>Query raised by Regional Office (Bhopal) on:<b>20/07/2021</b></span>
<span>Query raised by DFO (Sanjay Tiger Reserve) on:<b>17/08/2021</b></span><span>Replied by UA on :<b>17/09/2022</b></span>
<span>Query raised by DFO (Sanjay Tiger Reserve) on:<b>17/01/2023</b></span><span>Replied by UA on :<b></b></span>
<div><b>NOTE:-</b> Proposal Withdrawn by <b> </b>. </div>
<table><tr><td>User Agency (someone@example.com) REPLY</td></tr></table>
</body></html>"""


def test_only_government_bodies_keep_a_user_agency_name():
    s = pd.Series(["NATIONAL HIGHWAY AUTHORITY OF INDIA PIU AGRA", "PADAM KUMAR JAIN", "ESSAR OIL LIMITED",
                   "MAGNET BUILDTECH PVT LTD", "EXECUTIVE ENGINEER PWD KORBA", "WESTERN COALFIELDS LIMITED", None,
                   "BHARAT COKING COAL LIMITED", "EASTERN COAL FIELD LTD", "R V GAJJAR", "SRI NIRANJAN NAYAK"])
    assert P.public_agency(s).notna().tolist() == [True, False, False, False, True, True, False, True, True, False,
                                                   False]


def test_legacy_table_keeps_linked_proposals_without_people_or_email():
    pull = pd.DataFrame({"state": "Bihar",
                         "proposal_no": ["FP/BR/ROAD/1/2018", "FP/BR/ROAD/2/2019", "FP/BR/ROAD/3/2019"], "file_no": "x",
                         "name": ["house of Sh. A S/o B", "a road", "unlinked"], "category": "Road",
                         "user_agency": ["SOME PERSON", "PWD DIVISION PATNA", "PWD"], "area_ha": 1.0,
                         "status": "APPROVED", "received": ["2018-01-02", "2019-01-02", "2019-01-02"],
                         "stage1": [None, "2019-06-01", None], "stage2": None,
                         "milestones": ["EDS by UA (someone@example.com): 01/02/2019", None, None]})
    t = P.legacy_table(pull, {"FP/BR/ROAD/1/2018", "FP/BR/ROAD/2/2019"})
    assert t["proposal_no"].tolist() == ["FP/BR/ROAD/1/2018", "FP/BR/ROAD/2/2019"]      # only the linked ones
    assert pd.isna(t["user_agency_govt"].iloc[0]) and pd.isna(t["name"].iloc[0])        # a person's title goes too
    assert t["user_agency_govt"].iloc[1] == "PWD DIVISION PATNA" and t["name"].iloc[1] == "a road"
    assert "@" not in t["milestones"].iloc[0]
    assert t.columns.tolist() == P.LEGACY_COLS and t["listing"].eq(P.LEGACY_NOTE).all()


def test_parse_timeline_reads_levels_last_query_and_note_but_no_email():
    r = P.parse_timeline(TIMELINE, "FP/MP/RAIL/41734/2019")
    assert (r["submitted"], r["division"], r["regional_office"]) == ("2019-08-25", "2020-06-08", "2021-06-23")
    assert r.get("stage1") is None and r["area_ha"] == "72.8362" and r["state"] == "Madhya Pradesh"
    assert (r["last_query_on"], r["last_query_by"], r["last_query_replied"]) == (
        "2023-01-17", "DFO (Sanjay Tiger Reserve)", False)
    assert r["note"] == "Proposal Withdrawn" and "@" not in str(r)


def test_fetch_is_polite_and_keeps_a_redirect_as_its_status():
    class Resp:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, params):
            self.calls.append(params["pid"])
            return Resp(200, TIMELINE) if len(self.calls) == 1 else Resp(302)

    naps = []
    d = P.fetch_timelines(["FP/MP/RAIL/41734/2019", "FP/JH/MIN/44804/2020"], client=Client(), sleep=naps.append,
                          today="2026-09-28")
    assert naps == [P.MIN_GAP_S] and d["http"].tolist() == [200, 302]
    assert d["note"].iloc[0] == "Proposal Withdrawn" and d["retrieved"].eq("2026-09-28").all()


def test_stage_at_asof_reads_only_dated_events_by_asof():
    t = pd.Timestamp
    assert P.stage_at(t("2020-03-09"), pd.NaT, pd.NaT, False, ASOF) == ("filed, no Stage-I", t("2020-03-09"))
    assert P.stage_at(t("2019-03-01"), t("2021-02-25"), t("2026-08-01"), False, ASOF)[0] == "Stage-I, awaiting Stage-II"
    assert P.stage_at(t("2019-03-01"), t("2021-02-25"), t("2023-10-06"), False, ASOF)[0] == "Stage-II (final)"
    assert P.stage_at(t("2019-08-25"), pd.NaT, pd.NaT, True, ASOF)[0] == "dropped without approval"
    assert P.stage_at(t("2026-08-01"), pd.NaT, pd.NaT, False, ASOF)[0] is None                  # filed after asof


def test_proposal_rows_and_project_rollup():
    legacy = pd.DataFrame({"proposal_no": ["FP/JH/MIN/44804/2020", "FP/MP/RAIL/39172/2019"], "name": ["Muraidih", "KS"],
                           "category": ["Mining", "Railway"], "area_ha": [133.69, 66.69],
                           "received": pd.to_datetime(["2020-03-09", "2019-03-01"]),
                           "stage1": pd.to_datetime([None, "2021-02-25"]), "stage2": pd.to_datetime([None, "2023-10-06"]),
                           "milestones": ["SIR RO Ranchi : 02 Feb 2026 EDS(Addl. Info) : 05 Aug 2026", None],
                           "status": ["Pending With UA", "APPROVED"], "retrieved": "2026-09-27"})
    tl = pd.DataFrame([P.parse_timeline(TIMELINE, "FP/MP/RAIL/41734/2019") | {"retrieved": "2026-09-28"}])
    tl = tl.reindex(columns=P.TIMELINE_COLS)
    for c in ["submitted", "stage1", "stage2", "last_query_on"]:
        tl[c] = pd.to_datetime(tl[c])
    links = pd.DataFrame({"project_key": ["PRJ-1", "PRJ-2", "PRJ-2", "PRJ-3"],
                          "proposal_no": ["FP/JH/MIN/44804/2020", "FP/MP/RAIL/39172/2019", "FP/MP/RAIL/41734/2019",
                                          "FP/XX/ROAD/9/2020"], "link_source": "report remarks"})
    rows = P.proposal_rows(links, legacy, tl, ASOF).set_index("proposal_no")
    m = rows.loc["FP/JH/MIN/44804/2020"]
    assert m["stage_at_asof"] == "filed, no Stage-I" and round(m["months_in_stage"]) == 76 and m["open_at_asof"]
    assert m["last_query_on"] == pd.Timestamp("2026-02-02")                        # the 05 Aug 2026 EDS is after asof
    assert rows.loc["FP/MP/RAIL/41734/2019", "stage_at_asof"] == "dropped without approval"
    assert "no reply on the page" in rows.loc["FP/MP/RAIL/41734/2019", "evidence"]
    assert rows.loc["FP/XX/ROAD/9/2020", "found_in"] == "not_found"
    blank = P.proposal_rows(links.iloc[:1], legacy.assign(name=None), tl, ASOF)["evidence"].iloc[0]
    assert blank.startswith("FP/JH/MIN/44804/2020 (133.7 ha): filed Mar 2020")        # a blanked title
    events = pd.DataFrame({"project_key": ["PRJ-2"], "category": ["forest_env"], "status": ["open"],
                           "last_seen": [pd.Timestamp("2026-04-01")]})
    p = P.portal_projects(rows.reset_index(), links, events, ASOF).set_index("project_key")
    assert p.index.tolist() == ["PRJ-1", "PRJ-2"]                                  # not-found proposals drop out
    assert p.loc["PRJ-1", "open_not_in_report"] and not p.loc["PRJ-2", "open_not_in_report"]
    # one proposal final and one withdrawn reads as final, not dropped
    assert (p.loc["PRJ-2", "n_final"], p.loc["PRJ-2", "n_dropped"], p.loc["PRJ-2", "stage_at_asof"]) == (
        1, 1, "Stage-II (final)")
    assert p.loc["PRJ-2", "area_ha"] == round(66.69 + 72.8362, 2)


def test_remark_links_split_every_named_number():
    rs = pd.DataFrame({"project_key": ["A", "B"], "proposal_no": ["FP/MP/RAIL/39172/2019;FP/MP/RAIL/41734/2019", None]})
    assert P.remark_links(rs)["proposal_no"].tolist() == ["FP/MP/RAIL/39172/2019", "FP/MP/RAIL/41734/2019"]
