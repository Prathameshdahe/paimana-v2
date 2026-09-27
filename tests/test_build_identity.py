import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.build_identity import adapt_clean, adapt_portal, row_ids  # noqa: E402


def frame():
    base = dict(source_report_type="monthly_flash", source_period="2012-05-01", source_file="FR_MAY_2012.pdf",
                page=3, list_type="ongoing", printed_code="N04000100")
    return pd.DataFrame([
        {**base, "tag": "a", "project_name": "Imphal Airport NITB", "original_cost_cr": 499.0},
        {**base, "tag": "b", "project_name": "Imphal Airport NITB", "original_cost_cr": 499.0},  # exact duplicate
        {**base, "tag": "c", "project_name": "Imphal Airport NITB", "original_cost_cr": 510.0},
        {**base, "tag": "d", "project_name": "Leh Airport", "original_cost_cr": None, "printed_code": None},
        {**base, "tag": "e", "source_period": "2012-06-01", "project_name": "Imphal Airport NITB",
         "original_cost_cr": 499.0},
    ])


def test_row_ids_are_content_hashes_unique_per_report():
    df = frame()
    ids = row_ids(df).set_axis(df["tag"])
    assert ids["b"] == ids["a"] + "#2" and len(ids["a"]) == 16
    assert ids["a"] != ids["c"]                      # different printed cost -> different row
    assert ids["e"] == ids["a"]                      # ids only need to be unique inside one report
    assert not pd.concat([df[["source_report_type", "source_period"]], ids.rename("i").reset_index(drop=True)],
                         axis=1).duplicated().any()
    # re-extraction: row order, spacing and case do not move ids
    shuffled = df.iloc[[3, 2, 4, 0, 1]].reset_index(drop=True)
    shuffled.loc[shuffled["tag"] == "c", "project_name"] = "IMPHAL  airport - NITB"
    assert row_ids(shuffled).set_axis(shuffled["tag"]).to_dict() == ids.to_dict()


def test_adapter_uses_only_code_anchored_clean_keys_as_codes():
    df = pd.DataFrame({
        "report_type": ["monthly_flash"] * 4, "report_period": ["2012-05", "2025-07", "2008-01", "2009-01"],
        "source_file": "f.pdf", "page": 1, "list_type": "ongoing",
        "project_code": ["N04000100", "706718", None, None],
        "project_key": ["OCMS:N04000100", "OCMS:N04000100", "NAME:abc", "OCMS:N04000100"],
        "key_source": ["printed_code", "crosswalk", "name_chain", "name_link_to_code"],
        "project_name": "Imphal Airport", "sector": "Civil Aviation", "state": "Manipur", "agency": "AAI",
        "ministry": None, "cost_original_cr": 499.0, "doa_original": ["2016-03", None, None, None],
    })
    out = adapt_clean(df)
    assert out["project_code"].tolist()[:2] == ["OCMS:N04000100", "OCMS:N04000100"]
    assert out["project_code"].iloc[2:].isna().all()
    assert out["printed_code"].tolist()[:2] == ["N04000100", "706718"]
    assert out["clean_project_key"].tolist() == df["project_key"].tolist()
    assert out["source_period"].iloc[0] == "2012-05-01" and out["sanction_year"].iloc[0] == 2016


def test_portal_code_follows_the_clean_crosswalk():
    master = pd.DataFrame({"project_key": ["OCMS:N04000100", "PAIMANA:700001"],
                           "project_codes": ["OCMS:N04000100;PAIMANA:706718", "PAIMANA:700001"]})
    sector_map = pd.DataFrame({"era": ["hml"], "sector_raw": ["Aviation & Aviation Infrastructure"],
                               "ministry": ["Ministry of Civil Aviation"], "sector": ["Civil Aviation"]})
    portal = pd.DataFrame({"project_code": [706718, 700001], "project_name": ["Imphal", "Rajahmundry"],
                           "sector": "Aviation & Aviation Infrastructure", "ministry": "Ministry of Civil Aviation",
                           "agency": "AAI", "cost_original_cr": [499, 347], "sanction_date": "2021-11-01"})
    out = adapt_portal(portal, master, sector_map)
    assert out["project_code"].tolist() == ["OCMS:N04000100", "PAIMANA:700001"]
    assert out["printed_code"].tolist() == ["706718", "700001"]
    assert out["sector"].tolist() == ["Civil Aviation"] * 2
    assert set(out["source_report_type"]) == {"portal"}


def test_entities_one_row_per_clean_key_with_mode_name():
    from pipeline.build_identity import entities
    rows = pd.DataFrame({
        "source_report_type": "monthly_flash",
        "source_period": ["2010-01-01", "2011-01-01", "2012-01-01", "2012-01-01"],
        "source_row_id": ["a", "b", "c", "d"],
        "clean_project_key": ["OCMS:1", "OCMS:1", "OCMS:1", None],
        "project_code": ["OCMS:1", "OCMS:1", "OCMS:1", "PAIMANA:9"],
        "project_name": ["Long OCMS Name", "Long OCMS Name", "Short", "Portal Only"],
        "sector": [None, "Roads", None, "Power"], "state": None, "agency": None, "ministry": None,
        "original_cost_cr": [None, 100.0, 120.0, 50.0], "sanction_year": None,
    })
    ent, row_entity = entities(rows)
    assert row_entity.tolist() == ["OCMS:1", "OCMS:1", "OCMS:1", "PAIMANA:9"]
    e = ent.set_index("source_row_id")
    assert e.loc["OCMS:1", "project_name"] == "Long OCMS Name"
    assert e.loc["OCMS:1", "source_period"] == "2010-01-01"
    assert e.loc["OCMS:1", "sector"] == "Roads" and e.loc["OCMS:1", "original_cost_cr"] == 100.0
    assert set(ent["source_report_type"]) == {"clean_key"}


def test_different_codes_never_link(tmp_path):
    from pipeline.identity import IdentityConfig, IdentityMap
    df = pd.DataFrame({
        "source_report_type": "clean_key", "source_period": ["2010-01-01", "2011-01-01"],
        "source_row_id": ["OCMS:1", "OCMS:2"], "project_name": ["Bina Kota Doubling"] * 2,
        "project_code": ["OCMS:1", "OCMS:2"], "sector": "Railways", "state": "Rajasthan",
        "agency": None, "ministry": None, "original_cost_cr": 900.0, "sanction_year": 2015,
    })
    res = IdentityMap(IdentityConfig(root=tmp_path)).resolve_batch(df)
    assert res["project_key"].nunique() == 2
    assert set(res["review_status"]) == {"accepted"}
