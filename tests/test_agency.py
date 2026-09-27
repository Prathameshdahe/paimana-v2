import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import agency  # noqa: E402

REAL = {  # printed strings from silver observations -> canonical
    "NHAI": "NHAI",
    "NATIONAL HIGHWAYS AUTHORITY OF INDIA": "NHAI",
    "National Highways Authority of India [NHAI]": "NHAI",
    "MINISTRY OF ROAD TRANSPORT AND HIGHWAYS (STATE PWDs)": "MORTH",
    "Airport Authority of India [AAI]": "AAI",
    "POWER GRID CORPORATION OF INDIA LIMITED": "POWERGRID",
    "P.GRID": "POWERGRID",
    "WCL - CIL": "WCL",
    "STEEL AUTHORITY OF INDIA LIMITED (SAIL)": "SAIL",
    "CAO/C/ECoR ECoR mor": "ECOR",
    "GM IRCON KATNI WCR mor": "IRCON",
    "South Central Railway [SCR] - II": "SCR",
    "SOUTH EASTERN RAILWAY": "SER",
    "South Eastern Railway - JH": "SER",
    "CPWD FOR MHA": "CPWD",
    "RVNL - II": "RVNL",
    "NLC India Limited [NLCIL]": "NLC",
    "EDTK[MC]/RB": "INDIAN RAILWAYS",
}


@pytest.mark.parametrize("raw,expected", REAL.items())
def test_canonical_agency_on_real_strings(raw, expected):
    assert agency.canonical_agency(raw)[0] == expected


def test_missing_and_junk_names():
    assert agency.canonical_agency(None) == (None, "missing")
    assert agency.canonical_agency("  ") == (None, "missing")
    assert agency.canonical_agency("INVALID CO.")[0] is None
    # a one-letter bracket ('[P] LIMITED' = private) is not an acronym
    assert agency.canonical_agency("CHENAB VELLEY POWER PROJECTS [P] LIMITED")[0] == "CHENAB VELLEY POWER PROJECTS P"


def test_alias_variants_are_in_normal_form():
    assert [v for vs in agency.ALIASES.values() for v in vs if agency.normalise(v) != v] == []


def test_fuzzy_merges_spelling_variants_within_a_sector_only():
    rows = [("Water Resources-MP", "Water Resources", 3), ("Water resource-mp", "Water Resources", 1),
            ("Water Resources-PB", "Water Resources", 1), ("Water Resources-MP ", "Power", 1)]
    obs = pd.DataFrame([{"project_key": f"{a}-{i}", "agency": a, "sector": s} for a, s, n in rows for i in range(n)])
    m = agency.build_map(obs).set_index("raw")
    assert m.at["Water resource-mp", "canonical"] == "WATER RESOURCES MP"
    assert m.at["Water resource-mp", "method"] == "fuzzy"
    assert m.at["Water Resources-PB", "canonical"] == "WATER RESOURCES PB"      # another state, another agency


def test_shrinkage_math():
    shrunk, w = agency.shrink([0.5, 0.5, 0.5, 0.5], [5, 9, 10, 3], [0.2, 0.2, 0.2, np.nan])
    assert w[0] == pytest.approx(5 / 15) and w[1] == pytest.approx(9 / 19) and w[2] == 1.0
    assert shrunk[0] == pytest.approx(5 / 15 * 0.5 + 10 / 15 * 0.2)
    assert shrunk[1] == pytest.approx(9 / 19 * 0.5 + 10 / 19 * 0.2)
    assert shrunk[2] == 0.5            # n >= 10: raw
    assert shrunk[3] == 0.5            # no sector prior: raw


def test_matrix_hides_small_agencies_and_shrinks_toward_the_sector():
    rows = []
    for name, n, bias in (("A", 4, 1.0), ("B", 5, 1.0), ("C", 12, 0.0)):
        for i in range(n):
            rows.append({"project_key": f"{name}{i}", "agency": name, "sector": "Roads", "ministry": "M",
                         "sanction_date": pd.Timestamp("2010-01-01") + pd.DateOffset(years=i),
                         "schedule_bias": bias, "cost_bias": bias / 2})
    proj = pd.DataFrame(rows)
    cur = pd.DataFrame({"project_key": ["A0", "C1", "D0"], "agency": ["A", "C", "D"],
                        "anticipated_cost_cr": [100.0, 50.0, 7.0]})
    m = agency.matrix(proj, cur).set_index("agency")
    assert m.loc["A", "hidden"] and not m.loc["B", "hidden"] and not m.loc["C", "hidden"]
    sector = proj["schedule_bias"].median()                         # 0.0: C's 12 projects dominate
    assert m.loc["B", "schedule_bias_raw"] == 1.0
    assert m.loc["B", "schedule_bias"] == pytest.approx(5 / 15 * 1.0 + 10 / 15 * sector)
    assert m.loc["C", "schedule_bias"] == m.loc["C", "schedule_bias_raw"] == 0.0 and not m.loc["C", "shrunk"]
    assert m.loc["C", "schedule_bias_ci_lo"] <= 0.0 <= m.loc["C", "schedule_bias_ci_hi"]
    assert m.loc["A", "capital_cr"] == 100.0 and m.loc["A", "n_open"] == 1
    # an agency with current projects but no dated history is kept, hidden, n = 0
    assert m.loc["D", "n_projects"] == 0 and m.loc["D", "hidden"] and m.loc["D", "capital_cr"] == 7.0
    # trend: C has 12 projects sanctioned yearly 2010-2021; the last 3 years of data are 2018-2021 (4 recent)
    assert m.loc["C", "n_recent"] == 4 and m.loc["C", "trend"] == 0.0 and np.isnan(m.loc["A", "trend"])
