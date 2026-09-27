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
