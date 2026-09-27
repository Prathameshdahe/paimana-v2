import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.identity import (BundlePaths, IdentityCheckError, IdentityConfig,  # noqa: E402
                               IdentityMap, get_project_bundle, run_all)


def rows():
    return pd.DataFrame([
        # same project, three reports, three spellings, code appears later
        dict(source_report_type="monthly_2013_16", source_period="2014-04-01", source_row_id="r1",
             project_name="Delhi-Mumbai Exp. Pkg-I", project_code=None, sector="Road Transport",
             state="Rajasthan", agency="NHAI", ministry="MoRTH", original_cost_cr=1200.0, sanction_year=2013),
        dict(source_report_type="quarterly_2014_18", source_period="2016-01-01", source_row_id="q7",
             project_name="Delhi Mumbai Expressway Package 1", project_code="RT-0451", sector="Road Transport",
             state="Rajasthan", agency="NHAI", ministry="MoRTH", original_cost_cr=1215.0, sanction_year=2013),
        dict(source_report_type="flash", source_period="2026-04-01", source_row_id="f30",
             project_name="DELHI MUMBAI EXPRESSWAY PKG I", project_code="RT-0451", sector="Road Transport",
             state="Rajasthan", agency="NHAI", ministry="MoRTH", original_cost_cr=1215.0, sanction_year=None),
        # a different package: similar name, different cost -> must NOT merge
        dict(source_report_type="flash", source_period="2026-04-01", source_row_id="f31",
             project_name="Delhi Mumbai Expressway Package 4", project_code="RT-0454", sector="Road Transport",
             state="Gujarat", agency="NHAI", ministry="MoRTH", original_cost_cr=2400.0, sanction_year=2013),
        # unrelated project
        dict(source_report_type="flash", source_period="2026-04-01", source_row_id="f32",
             project_name="Gosikhurd Irrigation Project", project_code="WR-0090", sector="Water Resources",
             state="Maharashtra", agency="VIDC", ministry="Jal Shakti", original_cost_cr=18000.0, sanction_year=2008),
        # wrong printed code: code of Gosikhurd, name of something else entirely
        dict(source_report_type="flash", source_period="2026-05-01", source_row_id="g12",
             project_name="Bihta Airport Civil Enclave", project_code="WR-0090", sector="Civil Aviation",
             state="Bihar", agency="AAI", ministry="MoCA", original_cost_cr=450.0, sanction_year=2019),
    ])


@pytest.fixture
def cfg(tmp_path):
    return IdentityConfig(root=tmp_path / "identity")


def test_same_project_one_key_and_distinct_projects_distinct_keys(cfg):
    m = IdentityMap(cfg, run_id="t1")
    res = m.resolve_batch(rows())
    k = res.set_index("source_row_id")["project_key"]
    assert k["r1"] == k["q7"] == k["f30"]
    assert k["f31"] != k["r1"]
    assert k["f32"] != k["r1"] and k["f32"] != k["f31"]
    assert set(res[res.source_row_id.isin(["r1", "q7", "f30"])]["review_status"]) == {"accepted"}


def test_wrong_printed_code_is_not_merged_but_flagged(cfg):
    m = IdentityMap(cfg, run_id="t1")
    res = m.resolve_batch(rows()).set_index("source_row_id")
    # Bihta Airport carries Gosikhurd's code: name contradicts code -> own key, review flag
    assert res.loc["g12", "project_key"] != res.loc["f32", "project_key"]
    assert res.loc["g12", "match_method"] == "code_conflict"
    assert res.loc["g12", "review_status"] == "review"
    assert "g12" in set(m.review_queue()["source_row_id"])


def test_compatible_code_match_links_for_review(cfg):
    m = IdentityMap(cfg, run_id="t1")
    res = m.resolve_batch(rows()).set_index("source_row_id")
    gosi = res.loc["f32", "project_key"]
    sub = pd.DataFrame([dict(
        source_report_type="flash", source_period="2026-06-01", source_row_id="h1",
        project_name="Gosikhurd Left Bank Canal Works", project_code="WR-0090",
        sector="Water Resources", state="Maharashtra", agency="VIDC", ministry="Jal Shakti",
        original_cost_cr=900.0, sanction_year=2015)])
    r2 = m.resolve_batch(sub).iloc[0]
    assert r2["project_key"] == gosi and r2["review_status"] == "review"
    assert r2["match_method"] == "code_exact"
    # a human decides it is a separate project: manual NEW mints a fresh key on the next run
    m.save()
    m2 = IdentityMap(cfg, run_id="t2")
    manual = pd.DataFrame([dict(source_report_type="flash", source_period="2026-06-01",
                                source_row_id="h1", project_key="NEW")])
    r3 = m2.resolve_batch(sub, manual=manual).iloc[0]
    assert r3["project_key"] != gosi and r3["match_method"] == "manual"
    assert r3["review_status"] == "accepted"
    # applying the same manual file again does not mint a second key
    new_key = r3["project_key"]
    r4 = m2.resolve_batch(sub, manual=manual).iloc[0]
    assert r4["project_key"] == new_key and r4["match_method"] == "alias_cache"


def test_idempotent_rerun_mints_nothing(cfg):
    m = IdentityMap(cfg, run_id="t1")
    first = m.resolve_batch(rows()).set_index("source_row_id")["project_key"]
    m.save()
    m2 = IdentityMap(cfg, run_id="t2")
    n_before = len(list(m2.keys(active_only=False)))
    second = m2.resolve_batch(rows()).set_index("source_row_id")["project_key"]
    assert first.equals(second)
    assert len(list(m2.keys(active_only=False))) == n_before
    assert set(m2.resolve_batch(rows())["match_method"]) == {"alias_cache"}


def test_from_scratch_rebuild_is_deterministic(tmp_path):
    a = IdentityMap(IdentityConfig(root=tmp_path / "a"), run_id="a")
    b = IdentityMap(IdentityConfig(root=tmp_path / "b"), run_id="b")
    shuffled = rows().sample(frac=1.0, random_state=7)
    ka = a.resolve_batch(rows()).set_index("source_row_id")["project_key"].sort_index()
    kb = b.resolve_batch(shuffled).set_index("source_row_id")["project_key"].sort_index()
    assert ka.equals(kb)


def test_merge_resolves_old_key(cfg):
    m = IdentityMap(cfg, run_id="t1")
    res = m.resolve_batch(rows()).set_index("source_row_id")
    loser, winner = res.loc["f31", "project_key"], res.loc["r1", "project_key"]
    m.merge(loser, winner, reason="test")
    assert m.canonical(loser) == winner
    al = m.aliases_frame(canonical=True).set_index("source_row_id")
    assert al.loc["f31", "project_key"] == winner
    # a re-resolve of the loser's source row now lands on the winner
    again = m.resolve_batch(rows()).set_index("source_row_id")
    assert again.loc["f31", "project_key"] == winner


def test_bundle_and_checks(cfg, tmp_path):
    m = IdentityMap(cfg, run_id="t1")
    res = m.resolve_batch(rows())
    key = res.set_index("source_row_id").loc["r1", "project_key"]
    obs = pd.DataFrame({
        "project_key": [key, key, key],
        "period": pd.to_datetime(["2014-04-01", "2016-01-01", "2026-04-01"]),
        "sector": ["Road Transport"] * 3,
        "physical_progress_pct": [5.0, 20.0, 78.0],
        "source_doc_id": ["D1", "D2", "D3"],
    })
    obs_path = tmp_path / "observations.parquet"
    obs.to_parquet(obs_path, index=False)
    paths = BundlePaths(observations=obs_path,
                        sector_context=tmp_path / "missing.parquet",
                        sources=tmp_path / "missing2.parquet",
                        predictions_glob=str(tmp_path / "predictions_*.parquet"),
                        events=tmp_path / "missing3.parquet",
                        signals=tmp_path / "missing4.parquet")
    b = get_project_bundle(key, m, paths)
    assert b["project_key"] == key
    assert [o["physical_progress_pct"] for o in b["observations"]] == [5.0, 20.0, 78.0]
    assert len(b["aliases"]) == 3
    assert b["scores"] is None

    portal = res[(res.source_report_type == "flash") & (res.source_period == "2026-04-01")]
    report = run_all(m, obs, portal)
    assert report["unique_observations"]["duplicate_key_period"] == 0
    assert report["portal_one_to_one"]["accepted"] == 3
    # the whole history is NOT a portal frame: same project appears in 3 reports
    with pytest.raises(IdentityCheckError):
        run_all(m, obs, res)
    with pytest.raises(IdentityCheckError):
        run_all(m, pd.concat([obs, obs.iloc[[0]]]), None)
