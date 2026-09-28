import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import risk_profile as R  # noqa: E402
from pipeline import gold  # noqa: E402

ASOF = pd.Timestamp("2026-07-01")
T = pd.Timestamp


def checklist(fc_p1=None, land_p1=None, **extra):
    """Four projects: P1 Maharashtra road linked with low land complexity, remarks but no mentions; P2 outside
    Maharashtra with no remarks at all; P3 open land and litigation events, a forest clearance reported done;
    P4 untiered, linear with 50 ha forest known, a small agency, stale data, no sector data. fc_p1 / land_p1
    override P1's forest / land columns; extra goes to build_rows (remark_status, priors, portal)."""
    keys = ["P1", "P2", "P3", "P4"]
    cur = pd.DataFrame({
        "project_key": keys, "p_date_push_2q": [0.9, 0.5, 0.1, np.nan], "p_cost_rev_2q": [0.1, 0.2, 0.3, 0.4],
        "tier": ["High", "Medium", "Low", None], "no_completion_date": [False, False, False, True],
        "progress_velocity_2q": 1.0, "velocity_vs_sector_median": 0.5, "cost_variation_pct": 10.0,
        "physical_progress_pct": [50.0, 5.0, 50.0, np.nan], "elapsed_ratio": [0.5, 0.8, 0.5, 0.5],
        "spi": [1.0, 0.06, 1.0, np.nan], "stagnation_quarters": [0.0, 0.0, 3.0, np.nan], "burn_gap": [0.0, 30.0, -20.0, np.nan], "expenditure_ratio": 0.5,
        "revisions_so_far": [0.0, 3.0, 1.0, 0.0], "first_period": T("2020-01-01"),
        "sector": ["Roads & Highways", "Railways", "Railways", "Nothing"], "agency": ["NHAI", "NHAI", "NHAI", "Small"],
        "months_since_last_obs": [1.0, 1.0, 1.0, 6.0], "dq_score": 1.0,
        **{f"ext_open_{c}": 0.0 for c in gold.EXT_CATS}})
    cur.loc[2, ["ext_open_land", "ext_open_litigation"]] = 1.0
    ev = pd.DataFrame({"project_key": ["P3", "P3", "P3"], "category": ["land", "forest_env", "litigation"],
                       "event_no": 1, "first_seen": T("2021-01-01"), "last_seen": T("2023-04-01"),
                       "evidence": ["Land acquisition pending", "Stage II FC granted", "Writ petition in High Court"],
                       "resolved": [False, True, False], "status": ["open", "closed", "open"]})
    mentions = pd.DataFrame({"project_key": ["P1", "P3"], "period": T("2023-04-01"), "category": [None, "land"],
                             "resolved": pd.array([pd.NA, False], dtype="boolean")})
    fc = pd.DataFrame({"project_key": keys, "fc_shape": ["Linear", "Linear", "Non-Linear", "Linear"],
                       "fc_worst_complexity": 7, "fc_expected_complexity": [3.0, 3.0, 3.0, 6.5],
                       "fc_area_known": [False, False, False, True], "fc_area_ha": [np.nan] * 3 + [50.0],
                       "fc_violation": False,
                       "fc_evidence": "linear, area unknown: up to MoEFCC"})
    land = pd.DataFrame({"project_key": keys, "la_state": ["clear", "unknown", "clear", "unknown"],
                         "la_linked": [True, False, True, False], "la_complexity_max": pd.array([1, None, 5, None],
                                                                                         dtype="Int64"),
                         "la_nh": ["161", None, "160", None],
                         "la_evidence": ["NH-161: 50 parcels, complexity 1/5", None,
                                         "NH-160: 9 parcels, complexity 0/5", None],
                         "la_match_method": ["nh_only", "no_land_data_for_state", "nh_district", "not_road"]})
    agencies = pd.DataFrame({"bias": [0.5, 0.9], "n": [100, 3], "slip_rate_raw": [0.4, np.nan]},
                            index=pd.Index(["NHAI", "SMALL"], name="agency"))
    sector = pd.DataFrame({"actual_target_ratio": [0.9, 1.0, 1.0, np.nan], "trend_4q": [2.0, 1.0, 1.0, np.nan],
                           "period": [T("2026-01-01")] * 3 + [pd.NaT]})
    for df, over in ((fc, fc_p1), (land, land_p1)):
        for col, v in (over or {}).items():
            df.loc[0, col] = v
    rows = R.build_rows(cur, ASOF, ev, mentions, fc, land, agencies, sector, **extra)
    return rows.set_index(["project_key", "dimension"])


def test_every_project_gets_thirteen_rows_with_valid_states():
    r = checklist()
    assert r.groupby(level=0).size().eq(13).all()
    assert set(r["state"]) <= {"flagged", "clear", "unknown"}
    assert list(r.loc["P1"].index) == R.DIMENSIONS


def test_empty_search_is_unknown_never_clear():
    r = checklist()
    assert r.loc[("P2", "land_acquisition"), "state"] == "unknown"
    assert "no land data for this state" in r.loc[("P2", "land_acquisition"), "evidence"]
    assert "no free-text remarks" in r.loc[("P2", "litigation"), "evidence"]
    for k in ("P1", "P2", "P4"):                                         # nothing found in remarks
        assert r.loc[(k, "litigation"), "state"] == "unknown" and r.loc[(k, "contractor_stress"), "state"] == "unknown"
    assert "up to Apr 2023" in r.loc[("P1", "litigation"), "evidence"]
    # a linear project whose area is unknown is not flagged for forest clearance, only unknown
    assert r.loc[("P1", "forest_clearance"), "state"] == "unknown"


def test_clear_needs_positive_evidence_and_open_events_flag():
    r = checklist()
    assert r.loc[("P1", "land_acquisition"), ["state", "source"]].tolist() == ["clear", "bhoomi_rashi"]
    assert r.loc[("P3", "land_acquisition"), ["state", "source"]].tolist() == ["flagged", "report"]   # open beats clear
    assert r.loc[("P3", "forest_clearance"), ["state", "source"]].tolist() == ["clear", "report"]     # reported done
    assert r.loc[("P3", "litigation"), "state"] == "flagged"
    assert r.loc[("P4", "forest_clearance"), "state"] == "flagged"                  # linear, 50 ha known, worst 7
    assert r.loc[("P4", "forest_clearance"), "evidence"].startswith("high clearance complexity expected")


def test_rule_dimensions():
    r = checklist()
    s = r["state"]
    assert s.loc[("P4", "schedule_slip")] == "unknown" and "Watch" in r.loc[("P4", "schedule_slip"), "evidence"]
    assert s.loc[("P1", "schedule_slip")] == "flagged" and s.loc[("P3", "schedule_slip")] == "clear"
    assert s.loc[("P2", "execution_stagnation")] == "flagged" and s.loc[("P4", "execution_stagnation")] == "unknown"
    # SPI 1.0 but 3 quarters without progress: the stagnation override's rule flags it, as the tier panel says
    assert s.loc[("P1", "execution_stagnation")] == "clear" and s.loc[("P3", "execution_stagnation")] == "flagged"
    assert r.loc[("P3", "execution_stagnation"), "evidence"].endswith("; no progress for 3 quarters")
    assert [s.loc[(k, "expenditure_lag")] for k in ("P1", "P2", "P3", "P4")] == ["clear", "flagged", "flagged",
                                                                                 "unknown"]
    assert s.loc[("P2", "repeated_revisions")] == "flagged" and s.loc[("P3", "repeated_revisions")] == "clear"
    assert s.loc[("P1", "sector_headwind")] == "flagged" and s.loc[("P4", "sector_headwind")] == "unknown"
    assert s.loc[("P1", "agency_optimism")] == "flagged" and s.loc[("P4", "agency_optimism")] == "unknown"
    assert s.loc[("P4", "data_staleness")] == "flagged" and s.loc[("P1", "data_staleness")] == "clear"


def test_mh_ratio_removes_a_stratum_confound():
    # within each stratum the flag changes nothing; pooled, the flagged rows sit in the low-rate stratum
    y = [1] * 1 + [0] * 9 + [1] * 1 + [0] * 9 + [1] * 5 + [0] * 5 + [1] * 5 + [0] * 5
    flag = [True] * 10 + [False] * 10 + [True] * 10 + [False] * 10
    strata = ["a"] * 20 + ["b"] * 20
    assert R.mh_ratio(y, flag, strata) == pytest.approx(1.0)
    flag2 = [True] * 20 + [False] * 20                                  # flag only in stratum a: no comparison
    assert R.mh_ratio(y, flag2, strata) is None


def test_external_composite_row_is_rated_only_with_land():
    r = checklist()
    # P1: forest 3/7 (area unknown, the rulebook estimate) + land 1/5 -> 0.31 unknown; P3: 3/7 + 5/5 -> 0.71
    # flagged; P2, P4: no land -> unknown
    assert [r.loc[(k, "external_composite"), "state"] for k in ("P1", "P2", "P3", "P4")] == ["unknown", "unknown",
                                                                                              "flagged", "unknown"]
    assert r.loc[("P1", "external_composite"), "evidence"].endswith(
        "not rated clear: forest area unknown, so the forest half is the rulebook's estimate")
    assert r.loc[("P3", "external_composite"), "evidence"] == (
        "score 0.71 (fc+la): forest 3/7 (rulebook, area unknown) + land 5/5 (NH-160, Bhoomi Rashi)")
    p4 = r.loc[("P4", "external_composite"), "evidence"]
    assert p4 == ("score 0.93 (fc_only): forest 6.5/7 (rulebook, 50 ha); land unknown (no land data for non-road "
                  "projects), so the score is the forest half alone and is not rated")


def test_external_composite_clear_needs_both_halves_known_and_unflagged():
    known = {"fc_area_known": True, "fc_area_ha": 2.0, "fc_worst_complexity": 2, "fc_expected_complexity": 2.0}
    r = checklist(fc_p1=known)                                           # 2/7 + 1/5 -> 0.24, both known
    assert r.loc[("P1", "forest_clearance"), "state"] == "unknown" and r.loc[("P1", "external_composite"),
                                                                             "state"] == "clear"
    # land flagged at 3/5 with forest known: 0.44 is below the cut but never clear
    r = checklist(fc_p1=known, land_p1={"la_state": "flagged", "la_complexity_max": 3})
    assert r.loc[("P1", "land_acquisition"), "state"] == "flagged"
    assert r.loc[("P1", "external_composite"), "state"] == "unknown"
    assert r.loc[("P1", "external_composite"), "evidence"].endswith("not rated clear: the land row is flagged")


def test_evidence_of_a_dimension_no_project_flags_is_null():
    ev = pd.Series(["land line"], index=pd.MultiIndex.from_tuples([("P1", "land_acquisition")],
                                                                   names=["project_key", "dimension"]))
    keys = pd.Series(["P1", "P2"])
    got = R.evidence_of(ev, "land_acquisition", keys)
    assert got.iloc[0] == "land line" and pd.isna(got.iloc[1])
    assert R.evidence_of(ev, "litigation", keys).isna().all()



def test_measured_hidden_delay_and_overdue_parivesh_reach_the_checklist():
    remark_status = pd.DataFrame({"project_key": ["P1", "P2", "P3"],
                                  "fc_stage": ["stage1_granted", "central_fac_moef", "stage1_granted"],
                                  "fc_stage_as_of": T("2023-04-01"), "la_pct": [np.nan, np.nan, 60.0],
                                  "la_pct_as_of": [pd.NaT, pd.NaT, T("2026-04-01")]})
    ci = {"strata": "x", "n_rows": 50, "extra_months_lo": 1.0, "extra_months_hi": 9.0, "extra_push": 0.1,
          "extra_push_lo": -0.05, "extra_push_hi": 0.25}
    priors = pd.DataFrame([
        {"factor": "forest_clearance", "group": "fc_central", "measurable": False, "n_projects": 13},
        {"factor": "forest_clearance", "group": "fc_stage1", "measurable": True, "n_projects": 38, "extra_months": 3.0,
         **ci},
        {"factor": "land_progress", "group": "la_50_80", "measurable": True, "n_projects": 31, "extra_months": 1.0,
         **ci | {"extra_months_lo": -2.0}},
        {"factor": "land_complexity", "group": "cx_0_3", "measurable": True, "n_projects": 212, "extra_months": -1.0,
         **ci | {"extra_months_lo": -2.0, "extra_months_hi": 0.1}}])
    portal = pd.DataFrame({"project_key": ["P1", "P2"], "n_overdue": [0, 1], "n_final": [1, 0], "n_open": [0, 1],
                           "evidence": ["FP/XX/ROAD/2/2018 (a road, 5 ha): filed Jan 2018, Stage-II Mar 2020",
                                        "FP/XX/RAIL/1/2019 (a line, 70 ha): filed Jan 2019, no Stage-I after 90 "
                                        "months"]})
    r = checklist(remark_status=remark_status, priors=priors, portal=portal)
    p2 = r.loc[("P2", "forest_clearance")]
    assert p2["state"] == "flagged" and p2["source"] == "parivesh_portal"
    assert p2["evidence"].startswith("open on PARIVESH past its rule limit; ")
    assert "; PARIVESH: FP/XX/RAIL/1/2019" in p2["evidence"]
    # a remark stage over four quarters old is the last report's status, never an expected delay now
    assert p2["evidence"].endswith("; forest stage at the last report (2023-Q2, not current): pending at FAC / "
                                   "MoEFCC; projects at that stage then: too few projects to measure (13, need 15)")
    assert "expected hidden delay" not in p2["evidence"]
    # P1's PARIVESH proposal is final with nothing open: its older remark stage gets no prior at all
    p1 = r.loc[("P1", "forest_clearance"), "evidence"]
    assert "; PARIVESH: FP/XX/ROAD/2/2018" in p1 and "hidden delay" not in p1 and "last report" not in p1
    # P3's clearance is reported done: its old remark stage gets no prior; its current land share does
    assert "hidden delay" not in r.loc[("P3", "forest_clearance"), "evidence"]
    assert r.loc[("P3", "land_acquisition"), "evidence"].endswith(
        "; land 60% acquired in the remarks (as of 2026-Q2): no measurable extra delay (+1 month over the next year, "
        "CI -2 to +9; +10 pts date-push risk, CI -5 to +25; 31 projects)")
    # P1 is rated clear on its stretch: the complexity 0-3 prior; the unrated P2 gets none
    assert "measured hidden delay at the same deadline distance, complexity 0-3/5" in r.loc[
        ("P1", "land_acquisition"), "evidence"]
    assert "measured hidden delay" not in r.loc[("P2", "land_acquisition"), "evidence"]
    # without the new inputs the rows are as before
    assert checklist().loc[("P2", "forest_clearance"), "state"] == "unknown"


def web_fact(key, taxonomy, **kw):
    """A gold research_facts row (pipeline/research.py): live negative, severity 2, match high unless overridden."""
    return {"fact_id": f"{key}-{taxonomy}-{len(kw)}", "project_key": key, "category": taxonomy, "taxonomy": taxonomy,
            "direction": "negative", "severity": 2, "event_date": T("2026-05-01"), "date_precision": "month",
            "published_date": T("2026-05-20"), "status": "ongoing", "summary": "Work held up at 19 locations",
            "source": "The Hindu", "match": "high", **kw}


def test_web_research_flags_but_never_clears():
    research = pd.DataFrame([
        web_fact("P2", "land"),
        web_fact("P2", "land", severity=3, summary="Villagers stopped work", event_date=T("2026-06-01")),
        web_fact("P2", "litigation", summary="High Court stayed work", event_date=T("2026-08-13"),
                 date_precision="day"),
        web_fact("P3", "land", summary="Farmers protest"),                  # already flagged by the report
        web_fact("P1", "contractor", severity=1),                           # a mention, not a hold-up
        web_fact("P1", "litigation", match="medium"),                       # not surely this project
        web_fact("P1", "forest_env", status="resolved"),
        web_fact("P1", "land", event_date=T("2025-06-01")),                 # older than 4 quarters before asof
        web_fact("P4", "contractor", direction="positive"),
        web_fact("P4", "funding", severity=3)])                             # no checklist row for funding
    base, r = checklist(), checklist(research=research)
    changed = base["state"].ne(r["state"])
    assert set(changed[changed].index) == {("P2", "land_acquisition"), ("P2", "litigation")}
    p2 = r.loc[("P2", "land_acquisition")]
    assert (p2["state"], p2["source"]) == ("flagged", "news_research")
    assert p2["evidence"].startswith("Villagers stopped work (The Hindu, 2026-06) (+1 more); no land data for this")
    assert r.loc[("P2", "litigation"), "evidence"].startswith("High Court stayed work (The Hindu, 2026-08-13); ")
    p3 = r.loc[("P3", "land_acquisition")]
    assert p3["source"] == "report" and p3["evidence"].endswith("; web research: Farmers protest (The Hindu, 2026-05)")
    for k in ("P1", "P4"):   # nothing live, severe and surely theirs: the rows are exactly as before
        assert r.loc[k].equals(base.loc[k])
    assert not (base["state"].ne("clear") & r["state"].eq("clear")).any()   # research never clears
    counts = R.research_flags(r.reset_index(), research)
    assert counts["flagged_only_by_research"] == {"land_acquisition": 1, "forest_clearance": 0, "litigation": 1,
                                                  "contractor_stress": 0}
    assert counts["flagged_also_by_research"]["land_acquisition"] == 1 and counts["n_projects_with_facts"] == 4
    assert checklist(research=research.iloc[:0]).equals(base)


def test_research_applies_at_the_latest_asof_only(tmp_path, monkeypatch):
    latest = T("2026-07-01")
    facts = pd.DataFrame([web_fact("P2", "land")])
    monkeypatch.setattr(R, "GOLD", tmp_path)
    assert R.research_at(latest, latest) is None                          # the research step has not run
    facts.to_parquet(tmp_path / "research_facts.parquet", index=False)
    got = R.research_at(latest, latest)
    assert got is not None and got.equals(facts)                          # it has: read at the latest asof
    assert R.research_at(T("2026-09-30"), latest) is not None
    assert R.research_at(T("2026-04-01"), latest) is None                 # a later snapshot is not point in time


def test_committed_research_lines_are_the_live_high_severe_facts():
    """The committed gold research facts at the committed asof: a research line exactly where a fact is live,
    negative, severity >= 2 and match high in one of the four checklist taxonomies (whatever the sweep holds)."""
    latest = pd.read_parquet(R.SILVER / "observations.parquet", columns=["period"])["period"].max()
    research = R.research_at(latest, latest)
    assert research is not None and len(research), "the committed gold research_facts.parquet is missing"
    keys = pd.Series(sorted(research["project_key"].unique()))
    lines = R.research_lines(keys, research, latest)
    ok = research[research["match"].eq("high") & research["severity"].ge(R.RESEARCH_MIN_SEVERITY)
                  & R.web_research.live(research, latest)]
    for tax, dim in R.RESEARCH_DIMENSION.items():
        want = set(ok.loc[ok["taxonomy"].eq(tax), "project_key"])
        assert set(keys[lines[dim].ne("")]) == want, dim
    assert sum(lines[d].ne("").sum() for d in lines) >= 1   # the pilot flags 3 rows and adds 1 line
