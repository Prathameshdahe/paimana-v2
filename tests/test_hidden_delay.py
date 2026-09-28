"""pipeline/hidden_delay.py: the stratified group-minus-baseline difference, its bootstrap, Holm and the phrasing;
plus the checklist lines it feeds (ml/risk_profile.py)."""
import numpy as np
import pandas as pd

from pipeline import hidden_delay as H
from pipeline import parivesh as P


def rows(n_proj, per, stratum, value, key):
    return pd.DataFrame({"project_key": [f"{key}{i}" for i in range(n_proj) for _ in range(per)],
                         "s": stratum, "y": value})


def test_difference_is_taken_within_strata_not_across_them():
    # the group sits mostly in stratum b, where everyone slips more: its raw mean is high, its within-stratum lift 1
    g = pd.concat([rows(5, 2, "a", 2.0, "ga"), rows(20, 2, "b", 11.0, "gb")])
    b = pd.concat([rows(40, 2, "a", 1.0, "ba"), rows(10, 2, "b", 10.0, "bb")])
    est, lo, hi, p, gm, bm, matched = H.stratified_diff(g, b, "y", "s", np.random.default_rng(0), n_boot=200)
    assert est == 1.0 and lo == hi == 1.0 and matched == 1.0                     # no noise inside strata
    assert gm == (5 * 2 * 2 + 20 * 2 * 11) / 50 and bm == (10 * 1 + 40 * 10) / 50  # baseline reweighted to the group
    # a stratum without baseline rows drops out of the estimate
    c = pd.concat([g, rows(5, 1, "c", 99.0, "gc")])
    assert H.stratified_diff(c, b, "y", "s", np.random.default_rng(0), n_boot=50)[0] == 1.0


def test_bootstrap_ci_covers_a_null_effect_and_excludes_a_real_one():
    rng = np.random.default_rng(1)
    g = pd.DataFrame({"project_key": np.repeat([f"g{i}" for i in range(30)], 3), "s": "a",
                      "y": rng.normal(0, 1, 90)})
    b = pd.DataFrame({"project_key": np.repeat([f"b{i}" for i in range(300)], 3), "s": "a",
                      "y": rng.normal(0, 1, 900)})
    est, lo, hi, p, *_ = H.stratified_diff(g, b, "y", "s", np.random.default_rng(2), n_boot=400)
    assert lo < 0 < hi and p > 0.05
    est, lo, hi, p, *_ = H.stratified_diff(g.assign(y=g["y"] + 3), b, "y", "s", np.random.default_rng(2), n_boot=400)
    assert lo > 2 and p <= 0.01


def test_holm_steps_down_and_keeps_nan():
    got = H.holm([0.01, 0.04, np.nan, 0.03])
    assert np.allclose(got.dropna().tolist(), [0.03, 0.06, 0.06]) and np.isnan(got.iloc[2])


def test_text_says_too_few_no_measurable_or_the_estimate():
    base = {"measurable": True, "n_projects": 38, "extra_months": 2.5, "extra_months_lo": 0.5, "extra_months_hi": 4.3,
            "extra_push": 0.19, "extra_push_lo": 0.07, "extra_push_hi": 0.30}
    assert H.text(pd.Series(base)) == ("+3 months over the next year (CI +1 to +4) and +19 pts date-push risk "
                                       "(CI +7 to +30), measured on 38 projects")
    null = base | {"extra_months": 1.2, "extra_months_lo": -1.0, "extra_push_lo": -0.02}
    assert H.text(pd.Series(null)).startswith("no measurable extra delay (+1 month over the next year, CI -1 to +4")
    assert (H.fmt(-0.3), H.fmt(0.5), H.fmt(-2.5)) == ("0", "+1", "-3")
    assert H.text(pd.Series({"measurable": False, "n_projects": 13})) == "too few projects to measure (13, need 15)"
    assert H.text(None).startswith("too few projects to measure (0")


def test_only_measurable_groups_get_an_estimate():
    d = pd.DataFrame({"project_key": [f"p{i}" for i in range(40)], "period": pd.Timestamp("2020-01-01"),
                      "y_months": 1.0, "y_date_push": 0.0, "stratum_sy": "Roads|2020", "stratum_dl": "0-6",
                      "fc_group": ["fc_central"] * 5 + [None] * 35, "fc_base": [False] * 5 + [True] * 35,
                      "la_group": None, "la_base": False, "cx_group": None, "cx_base": False,
                      "cx_nh_group": None, "cx_nh_base": False})
    t = H.priors(d, n_boot=20).set_index("group")
    assert not t.loc["fc_central", "measurable"] and pd.isna(t.loc["fc_central", "extra_months"])
    assert t.loc["fc_central", "n_projects"] == 5 and t.loc["fc_central", "garvit_band"] == "28-63 (median 46)"


def test_stage1_rule_limit_follows_the_rules_in_force_at_filing():
    norms = P.load_norms()
    m, rule = P.norm(P.STAGE_ORDER[0], pd.Timestamp("2020-03-09"), 133.69, "Mining", pd.Timestamp("2026-07-01"), norms)
    assert round(m, 1) == 9.9 and "300 days" in rule
    m, rule = P.norm(P.STAGE_ORDER[0], pd.Timestamp("2019-01-01"), 12.0, "Road", pd.Timestamp("2026-07-01"), norms)
    assert round(m, 1) == 8.4 and "255 days" in rule
    assert np.isnan(P.norm(P.STAGE_ORDER[0], pd.Timestamp("2022-09-01"), 12.0, "Road", pd.Timestamp("2026-07-01"),
                           norms)[0])                                                  # 2022 rules: screening only
    m, rule = P.norm(P.STAGE_ORDER[1], pd.Timestamp("2015-01-01"), 3.0, "Road", pd.Timestamp("2026-07-01"), norms)
    assert round(m) == 60 and "may be revoked after 5 years" in rule                   # the 2025 amendment
    m, _ = P.norm(P.STAGE_ORDER[1], pd.Timestamp("2015-01-01"), 3.0, "Road", pd.Timestamp("2024-07-01"), norms)
    assert round(m) == 24                                                             # before it: 2 years
