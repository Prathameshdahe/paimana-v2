import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import silver  # noqa: E402


def raw(**over):
    """One clean-contract row that passes every rule; keyword args override columns."""
    row = {c: None for c in silver.TEXT + silver.DATES + silver.NUMBERS}
    row.update(source_report_type="monthly_flash", source_period="2012-05-01", source_row_id="r1",
               source_file="FR_MAY_2012.pdf", page=3, list_type="ongoing", project_name="Imphal Airport",
               doa_original="2008-03", doc_original="2012-03", cost_original_cr=500.0, cost_revised_cr=600.0,
               expenditure_cum_cr=300.0, physical_progress_pct=60.0, project_key="PRJ-000001",
               review_status="accepted")
    row.update(over)
    return row


def rules(*rows):
    d = silver.typed(pd.DataFrame(list(rows)))
    return {r: set(d.loc[m, "source_row_id"]) for r, (m, _) in silver.quarantine_rules(d).items()}


def test_typed_parses_and_flags():
    d = silver.typed(pd.DataFrame([raw(doc_original="2012-3x", cost_original_cr="n/a",
                                       doa_original="2008-03-15")]))
    assert d["doa_original"].iloc[0] == pd.Timestamp("2008-03-01")
    assert pd.isna(d["doc_original"].iloc[0]) and pd.isna(d["cost_original_cr"].iloc[0])
    assert d["dq_note"].iloc[0] == "parse_fail:doc_original;parse_fail:cost_original_cr"


def test_placeholders_become_null():
    d = silver.typed(pd.DataFrame([raw(physical_progress_pct=0.0, dq_note="placeholder_zero"),
                                   raw(source_row_id="r2", physical_progress_pct=0.0)]))
    assert pd.isna(d["physical_progress_pct"].iloc[0]) and d["physical_progress_pct"].iloc[1] == 0.0


def test_each_row_rule():
    hit = rules(raw(), raw(source_row_id="p", physical_progress_pct=104.0),
                raw(source_row_id="n", expenditure_cum_cr=-5.0),
                raw(source_row_id="x", expenditure_cum_cr=1900.0),       # > 3 x revised cost 600
                raw(source_row_id="c", doc_original="2007-12"),
                raw(source_row_id="z", doa_original="1999-01"))
    assert hit == {"progress_out_of_range": {"p"}, "negative_money": {"n"}, "expenditure_gt_3x_cost": {"x"},
                   "completion_before_sanction": {"c"}, "placeholder_date": {"z"}}


def test_expenditure_falls_back_to_original_cost():
    hit = rules(raw(cost_revised_cr=None, expenditure_cum_cr=1400.0),
                raw(source_row_id="y", cost_revised_cr=None, expenditure_cum_cr=1600.0))
    assert hit["expenditure_gt_3x_cost"] == {"y"}


def test_expenditure_uses_anticipated_cost_first():
    # old flash reports: revised blank, escalation printed as anticipated cost
    hit = rules(raw(cost_original_cr=2500.0, cost_revised_cr=None, cost_anticipated_cr=20000.0,
                    expenditure_cum_cr=10722.72),
                raw(source_row_id="y", cost_revised_cr=None, cost_anticipated_cr=400.0, expenditure_cum_cr=1300.0))
    assert hit["expenditure_gt_3x_cost"] == {"y"}


def test_duplicate_key_period_keeps_more_complete_row():
    d = silver.typed(pd.DataFrame([raw(source_row_id="a", state=None),
                                   raw(source_row_id="b", state="Manipur"),
                                   raw(source_row_id="c", list_type="other:delayed_wrt_original")]))
    rows, dups = silver.dedupe_reports(d)
    assert rows["source_row_id"].tolist() == ["b"]
    assert dups["source_row_id"].tolist() == ["a"] and dups["kept_row_id"].tolist() == ["b"]


def reports(*rows):
    rows, _ = silver.dedupe_reports(silver.typed(pd.DataFrame(list(rows))))
    return rows


def test_dedupe_prefers_ongoing_and_merges_missing_fields():
    d = reports(raw(source_row_id="a", list_type="other:additionally_delayed", state="Manipur", remarks="land"),
                raw(source_row_id="b", list_type="completed", remarks=None),
                raw(source_row_id="c", list_type="ongoing"))
    assert d["source_row_id"].tolist() == ["c"] and d["list_type"].tolist() == ["ongoing"]
    assert d["state"].tolist() == ["Manipur"] and d["remarks"].tolist() == ["land"]


def test_panel_takes_last_valid_value_in_quarter():
    d = reports(raw(source_row_id="a", source_period="2012-04-01", physical_progress_pct=40.0, state="Manipur"),
                raw(source_row_id="b", source_period="2012-05-01", physical_progress_pct=50.0),
                raw(source_row_id="c", source_period="2012-06-01", physical_progress_pct=None, page=9))
    p = silver.panel(d)
    assert len(p) == 1 and p["period"].iloc[0] == pd.Timestamp("2012-04-01")
    assert p["physical_progress_pct"].iloc[0] == 50.0 and p["state"].iloc[0] == "Manipur"
    assert p["source_page"].iloc[0] == 9 and p["obs_count_in_quarter"].iloc[0] == 3


def test_panel_one_row_per_key_period_and_months_since_last_obs():
    d = reports(raw(source_row_id="a", source_period="2012-04-01"),
                raw(source_row_id="b", source_period="2012-06-01"),
                raw(source_row_id="c", source_period="2012-08-01"),
                raw(source_row_id="d", source_period="2013-09-01"),
                raw(source_row_id="e", source_period="2012-06-01", source_report_type="quarterly_qpisr"),
                raw(source_row_id="f", source_period="2012-05-01", project_key="PRJ-000002"))
    p = silver.panel(d)
    assert not p.duplicated(["project_key", "period"]).any() and len(p) == 4
    one = p[p["project_key"].eq("PRJ-000001")]
    assert one["months_since_last_obs"].tolist() == [pd.NA, 2, 13]
    assert one["period_type"].tolist() == ["quarterly", "monthly", "monthly"]


def test_portal_only_where_no_flash_row_in_quarter():
    port = dict(source_report_type="portal", source_period="2026-07-01", source_file="portal/portal_projects.csv",
                page=None)
    d = reports(raw(source_row_id="a", source_report_type="paimana_flash", source_period="2026-07-01"),
                raw(source_row_id="p", **port),
                raw(source_row_id="q", project_key="PRJ-000002", **port))
    p = silver.panel(d)
    assert p.set_index("project_key")["period_type"].to_dict() == {"PRJ-000001": "flash", "PRJ-000002": "portal"}


def test_coverage_shares_and_counts():
    d = reports(raw(source_row_id="a", state="Manipur"), raw(source_row_id="b", project_key="PRJ-000002"))
    q = pd.DataFrame({"source_report_type": ["monthly_flash"], "source_period": ["2012-05-01"],
                      "source_row_id": ["zz"]})
    c = silver.coverage(silver.panel(d), q).iloc[0]
    assert (c["n_rows"], c["n_keys"], c["n_quarantined"], c["n_monthly"]) == (2, 2, 1, 2)
    assert c["state"] == 0.5 and c["original_cost_cr"] == 1.0
