import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import gold  # noqa: E402

QUARTERS = pd.date_range("2014-01-01", "2019-10-01", freq="QS").astype("datetime64[us]")


def panel(n_keys=40, seed=7):
    """Synthetic silver observations: gappy quarterly rows, rising progress and spend, occasional cost
    revisions and completion pushes, three agencies, two sectors; some keys complete."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_keys):
        start = int(rng.integers(0, 8))
        periods = [p for p in QUARTERS[start:start + int(rng.integers(6, 18))] if rng.random() > 0.15]
        cost, prog, spend = float(rng.uniform(200, 8000)), 0.0, 0.0
        sanction = QUARTERS[start] - pd.DateOffset(months=int(rng.integers(0, 24)))
        sched = sanction + pd.DateOffset(months=int(rng.integers(24, 60)))
        ant = sched
        for i, p in enumerate(periods):
            prog = min(100.0, prog + float(rng.choice([0, 0.2, 5, 12, 25])))
            spend = min(1.2, spend + float(rng.uniform(0, 0.12)))
            if rng.random() < 0.2:
                cost *= 1.1
            if rng.random() < 0.25:
                ant = ant + pd.DateOffset(months=int(rng.integers(3, 12)))
            done = prog >= 100
            rows.append({
                "project_key": f"PRJ-{k:06d}", "period": p, "period_type": "quarterly",
                "original_cost_cr": 1000.0 if k % 5 else None, "anticipated_cost_cr": cost,
                "expenditure_cr": spend * cost, "physical_progress_pct": None if rng.random() < 0.1 else prog,
                "sanction_date": sanction, "scheduled_completion": sched,
                "anticipated_completion": None if rng.random() < 0.1 else ant, "is_completed": done,
                "cost_basis": "anticipated", "completion_basis": "anticipated",
                "agency": ["NHAI", "Rail Vikas [RVNL]", None][k % 3], "ministry": None,
                "sector": ["Roads & Highways", "Railways"][k % 2], "state": "Goa", "delay_months": None,
                "obs_count_in_quarter": 1, "months_since_last_obs": 3, "dq_score": 1.0})
            if done:
                break
    d = pd.DataFrame(rows)
    for c in ("period", "sanction_date", "scheduled_completion", "anticipated_completion"):
        d[c] = pd.to_datetime(d[c]).astype("datetime64[us]")
    d["months_since_last_obs"] = d["months_since_last_obs"].astype("Int64")
    return d


def sectors():
    return pd.DataFrame({"sector": "Railways", "period": QUARTERS, "actual_target_ratio": 0.9,
                         "yoy_growth_pct": 4.0, "trend_4q": 3.5})


def at(f, t):
    return f[f["period"] == t].sort_values("project_key", ignore_index=True)


def test_key_features_ignore_its_later_rows():
    full = panel()
    key = full["project_key"].value_counts().index[0]
    rows = full[full["project_key"] == key]
    t = rows["period"].iloc[len(rows) // 2]
    cut = full[(full["project_key"] != key) | (full["period"] <= t)]
    a = gold.build_features(cut, sectors=sectors())
    b = gold.build_features(full, sectors=sectors())
    a, b = (f[(f["project_key"] == key)].reset_index(drop=True) for f in (a, b))
    pd.testing.assert_frame_equal(a, b.iloc[:len(a)])
    assert len(b) > len(a)


def test_velocity_and_stagnation():
    d = panel(1).iloc[:0]
    base = {c: None for c in d.columns}
    prog = [10, 20, 20.2, 20.4, 40]
    rows = [base | {"project_key": "PRJ-000001", "period": QUARTERS[i], "physical_progress_pct": p,
                    "anticipated_cost_cr": 100.0, "is_completed": False, "sector": "Railways",
                    "period_type": "quarterly", "obs_count_in_quarter": 1, "dq_score": 1.0}
            for i, p in enumerate(prog)]
    d = pd.DataFrame(rows).astype({"period": "datetime64[us]", "sanction_date": "datetime64[us]",
                                   "scheduled_completion": "datetime64[us]",
                                   "anticipated_completion": "datetime64[us]"})
    f = gold.build_features(d, sectors=sectors())
    assert f["progress_velocity_2q"].tolist()[2:] == pytest.approx([5.1, 0.2, 9.9])
    assert f["stagnation_quarters"].tolist() == [0, 0, 1, 2, 0]


def obs_rows(key, rows, agency="NHAI"):
    """Minimal observations for one key: rows are (quarter index, cost, anticipated completion, completed)."""
    d = pd.DataFrame([{"project_key": key, "period": QUARTERS[q], "anticipated_cost_cr": c,
                       "anticipated_completion": a, "is_completed": done} for q, c, a, done in rows])
    d["anticipated_completion"] = pd.to_datetime(d["anticipated_completion"]).astype("datetime64[us]")
    template = panel(1).iloc[:0]
    d = pd.concat([template, d], ignore_index=True).assign(
        agency=agency, sector="Railways", period_type="quarterly", obs_count_in_quarter=1, dq_score=1.0,
        cost_basis="anticipated", completion_basis="anticipated",
        original_cost_cr=d["anticipated_cost_cr"], physical_progress_pct=50.0)
    return d.astype(template.dtypes.to_dict())


def test_labels_exact_horizon_and_null_inputs():
    d = pd.concat([obs_rows("PRJ-000001", [(0, 100.0, "2020-01", False), (1, 100.0, "2020-01", False),
                                           (2, 104.0, None, False), (3, 110.0, "2020-06", False),
                                           (4, 110.0, "2020-06", True)]),
                   obs_rows("PRJ-000002", [(0, 100.0, "2020-01", False), (1, 100.0, "2020-01", False),
                                           (3, 100.0, "2020-01", False)])], ignore_index=True)
    lab = gold.build_labels(d, 2).set_index(["project_key", "period"])
    assert list(lab.index) == [("PRJ-000001", QUARTERS[q]) for q in (0, 1, 2)] + [("PRJ-000002", QUARTERS[1])]
    rows = lab[["y_date_push", "y_cost_rev", "y_any"]].astype("float64").to_numpy().tolist()
    nan = float("nan")
    assert np.array_equal(rows, [[nan, 0, nan], [1, 1, 1], [nan, 1, nan], [0, 0, 0]], equal_nan=True)
    assert lab["y_months"].tolist()[1] == 5 and lab["y_cost_pct"].iloc[0] == pytest.approx(4.0)
    assert (lab["target_period"] == [QUARTERS[q] for q in (2, 3, 4, 3)]).all()


def test_labels_null_across_a_basis_change():
    rows = [(0, 100.0, "2020-01", False), (2, 150.0, "2020-09", False)]
    same = gold.build_labels(obs_rows("PRJ-000001", rows), 2)
    assert same[["y_date_push", "y_cost_rev", "y_any"]].iloc[0].tolist() == [1, 1, 1]
    d = obs_rows("PRJ-000001", rows)
    d.loc[1, "cost_basis"] = "revised"              # t + h prints revised cost, t printed anticipated
    lab = gold.build_labels(d, 2).iloc[0]
    assert pd.isna(lab["y_cost_rev"]) and pd.isna(lab["y_cost_pct"]) and pd.isna(lab["y_any"])
    assert lab["y_date_push"] == 1 and lab["y_months"] == 8
    d.loc[1, "completion_basis"] = "revised"
    lab = gold.build_labels(d, 2).iloc[0]
    assert pd.isna(lab["y_date_push"]) and pd.isna(lab["y_months"])


def test_cutoff_bounds_feature_frame():
    c = QUARTERS[12]
    f = gold.build_features(panel(), cutoff=c, sectors=sectors())
    assert f["period"].max() == c


def test_features_at_t_same_on_truncated_panel():
    full = panel()
    b = gold.build_features(full, sectors=sectors())
    for t in QUARTERS[3::2]:
        a = gold.build_features(full[full["period"] <= t], sectors=sectors())
        pd.testing.assert_frame_equal(at(a, t), at(b, t))
        pd.testing.assert_frame_equal(at(gold.build_features(full, cutoff=t, sectors=sectors()), t), at(b, t))


def test_agency_stats_count_only_realised_labels():
    # key 1 slips between q0 and q2; that outcome is known at q2, not at q1
    d = pd.concat([obs_rows("PRJ-000001", [(0, 100.0, "2020-01", False), (2, 100.0, "2020-09", False)]),
                   obs_rows("PRJ-000002", [(1, 100.0, "2021-01", False), (2, 100.0, "2021-01", False),
                                           (3, 100.0, "2021-01", False)])], ignore_index=True)
    f = gold.build_features(d, sectors=sectors()).set_index(["project_key", "period"])
    k2 = f.loc["PRJ-000002"]
    assert k2["agency_n"].tolist() == [0, 1, 2]
    assert k2["agency_slip_rate"].iloc[1] > k2["agency_slip_rate"].iloc[0] or pd.isna(k2["agency_slip_rate"].iloc[0])


def test_agency_n_matches_brute_force():
    full = panel()
    f = gold.build_features(full, sectors=sectors())
    lab = gold.build_labels(gold.base(full), gold.AGENCY_H).merge(f[["project_key", "period", "agency"]],
                                                                  on=["project_key", "period"])
    pairs = f[["project_key", "period", "agency"]].merge(lab.loc[lab["agency"].notna(), ["agency", "target_period"]],
                                                          on="agency")
    want = (pairs[pairs["target_period"] <= pairs["period"]].groupby(["project_key", "period"]).size()
            .reindex(pd.MultiIndex.from_frame(f[["project_key", "period"]]), fill_value=0))
    assert (f["agency_n"].to_numpy() == want.to_numpy()).all()
    assert f.loc[f["agency"].isna(), "agency_n"].eq(0).all()
