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


def checklist():
    """Four projects: P1 Maharashtra road linked with low land complexity, remarks but no mentions; P2 outside
    Maharashtra with no remarks at all; P3 open land and litigation events, a forest clearance reported done;
    P4 untiered, linear with 50 ha forest known, a small agency, stale data, no sector data."""
    keys = ["P1", "P2", "P3", "P4"]
    cur = pd.DataFrame({
        "project_key": keys, "p_date_push_2q": [0.9, 0.5, 0.1, np.nan], "p_cost_rev_2q": [0.1, 0.2, 0.3, 0.4],
        "tier": ["High", "Medium", "Low", None], "no_completion_date": [False, False, False, True],
        "progress_velocity_2q": 1.0, "velocity_vs_sector_median": 0.5, "cost_variation_pct": 10.0,
        "physical_progress_pct": [50.0, 5.0, 50.0, np.nan], "elapsed_ratio": [0.5, 0.8, 0.5, 0.5],
        "spi": [1.0, 0.06, 1.0, np.nan], "burn_gap": [0.0, 30.0, -20.0, np.nan], "expenditure_ratio": 0.5,
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
                       "fc_worst_complexity": 7, "fc_expected_complexity": 3.0,
                       "fc_area_known": [False, False, False, True], "fc_violation": False,
                       "fc_evidence": "linear, area unknown: up to MoEFCC"})
    land = pd.DataFrame({"project_key": keys, "la_state": ["clear", "unknown", "clear", "unknown"],
                         "la_linked": [True, False, True, False],
                         "la_evidence": ["NH-161: 50 parcels, complexity 1/5", None,
                                         "NH-160: 9 parcels, complexity 0/5", None],
                         "la_match_method": ["nh_only", "outside_maharashtra", "nh_district", "not_road"]})
    agencies = pd.DataFrame({"bias": [0.5, 0.9], "n": [100, 3], "slip_rate_raw": [0.4, np.nan]},
                            index=pd.Index(["NHAI", "SMALL"], name="agency"))
    sector = pd.DataFrame({"actual_target_ratio": [0.9, 1.0, 1.0, np.nan], "trend_4q": [2.0, 1.0, 1.0, np.nan],
                           "period": [T("2026-01-01")] * 3 + [pd.NaT]})
    rows = R.build_rows(cur, ASOF, ev, mentions, fc, land, agencies, sector)
    return rows.set_index(["project_key", "dimension"])


def test_every_project_gets_twelve_rows_with_valid_states():
    r = checklist()
    assert r.groupby(level=0).size().eq(12).all()
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
    assert s.loc[("P4", "schedule_slip")] == "unknown" and "untiered" in r.loc[("P4", "schedule_slip"), "evidence"]
    assert s.loc[("P1", "schedule_slip")] == "flagged" and s.loc[("P3", "schedule_slip")] == "clear"
    assert s.loc[("P2", "execution_stagnation")] == "flagged" and s.loc[("P4", "execution_stagnation")] == "unknown"
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
