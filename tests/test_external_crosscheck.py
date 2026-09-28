"""
Cross-check of the teammate's external-factor mock data against the real sources (docs/EXTERNAL_DATA_CROSSCHECK.md).

The mock files in dataset/raw/external/mock/ are SYNTHETIC: they are read here only to check formulas and the
parts drawn from real data, never as model or app inputs (the last test guards that).
"""
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import bhoomi_rashi as B  # noqa: E402
from pipeline import external as X  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MOCK = X.EXTERNAL / "mock"
V0 = pd.read_csv(MOCK / "external_factor_mock_v0.csv")
V1 = pd.read_csv(MOCK / "external_factor_mock_v1_gatishakti.csv")
SCEN = pd.read_csv(X.EXTERNAL / "parivesh_fc_scenarios.csv")
REAL_LA = pd.read_csv(X.EXTERNAL / "land_acquisition_maharashtra.csv")


def test_mock_files_are_the_same_150_projects():
    assert V0.shape == (150, 23) and V1.shape == (150, 29)
    assert V1["project_id"].equals(V0["project_id"])
    assert sorted(set(V1) - set(V0)) == sorted(c for c in V1 if c.startswith("gs_"))


def test_mock_fc_rows_are_draws_from_the_real_rulebook():
    fc = V0[V0["fc_required"].eq(1)]
    assert len(fc) == 89 and fc["fc_scenario_id"].isin(SCEN["scenario_id"]).all()
    assert fc["fc_scenario_id"].nunique() == len(SCEN) == 28                   # every scenario is used
    m = fc.merge(SCEN, left_on="fc_scenario_id", right_on="scenario_id", validate="m:1")
    assert m["fc_authority_level"].eq(m["authority_level"]).all()
    assert m["fc_complexity_score"].eq(m["complexity_score"]).all()
    allowed = [("Yes" if f else "No") in v.split("/") for f, v in zip(m["fc_violation_flag"], m["violation"])]
    assert all(allowed)


def test_v1_composite_is_the_three_way_mean():
    c = (V1["fc_complexity_score"] / 7 + V1["la_complexity_score"] / 5 + V1["gs_complexity_score"] / 4) / 3
    assert (c - V1["external_factor_composite_score"]).abs().max() < 0.001


def test_real_land_table_matches_the_guide():
    # the LA rule reproducing all 347 real scores is tests/test_external.py test_la_complexity_reproduces_every_...
    assert len(REAL_LA) == 347 and REAL_LA["num_parcels"].sum() == 89_950 and REAL_LA["highway_name"].nunique() == 90
    assert REAL_LA["state"].eq("MAHARASHTRA").all()


def mock_la_hits():
    la = V0[V0["la_required"].eq(1)]
    rule = B.la_complexity(la["la_num_districts"], la["la_span_days"], la["la_num_parcels"], la["la_total_area_ha"])
    return la, rule.eq(la["la_complexity_score"])


def test_mock_la_scores_follow_the_rule_only_half_the_time():
    # measured: 35 of 71 (49%); the guessed state fragmentation factor is applied after scoring, and 62 of the 71
    # rows are outside Maharashtra. A regenerated mock that scores after scaling should reach 100%: then drop this
    # test and the xfail below turns into a pass (strict, so it fails loudly until it is removed).
    la, hit = mock_la_hits()
    assert len(la) == 71 and int(hit.sum()) == 35
    assert int((~la["state"].eq("Maharashtra")).sum()) == 62


@pytest.mark.xfail(strict=True, reason="mock LA scores ignore the fragmentation scaling (49% follow the rule)")
def test_mock_la_scores_follow_the_rule():
    assert mock_la_hits()[1].all()


def test_mock_data_never_reaches_the_pipeline():
    code = [p for d in ("pipeline", "ml", "backend") for p in (ROOT / d).rglob("*.py")]
    used = [p.name for p in code
            if re.search(r"external_factor_mock|external[/\\]mock|['\"]mock['\"]", p.read_text(encoding="utf-8"))]
    assert code and not used
    names = ["features.parquet", "external_fc.parquet", "external_land.parquet", "external_composite.parquet"]
    for path in [X.GOLD / n for n in names] + sorted(X.GOLD.glob("risk_profile_*.parquet")):
        keys = pd.read_parquet(path, columns=["project_key"])["project_key"]
        assert keys.str.startswith("PRJ-").all(), path.name                   # never a mock PAIMANA-1xxx id
