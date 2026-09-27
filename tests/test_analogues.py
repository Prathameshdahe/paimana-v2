import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import analogues as A  # noqa: E402

ASOF = pd.Timestamp("2026-07-01")


def test_pool_keeps_only_outcomes_known_by_asof():
    keys = ["PRJ-1", "PRJ-2", "PRJ-3"]
    lab = pd.DataFrame({"project_key": keys, "period": pd.to_datetime(["2025-01-01", "2025-07-01", "2025-01-01"]),
                        "target_period": pd.to_datetime(["2026-01-01", "2026-07-01", "2026-01-01"]),
                        "y_months": [12.0, 0.0, 3.0], "y_cost_pct": 0.0, "y_any": pd.array([1, 0, pd.NA], "Int8"),
                        "y_date_push": 1, "y_cost_rev": 0})
    feats = lab[["project_key", "period"]].assign(sector="Roads", **{c: 1.0 for c in A.STAGE})
    d, Z, _ = A.pool(feats, lab, pd.Timestamp("2026-04-01"))
    assert d.project_key.tolist() == ["PRJ-1"]                  # PRJ-2 realised after asof, PRJ-3 outcome unknown
    assert Z.shape == (1, len(A.STAGE))


def test_nearest_one_row_per_other_project():
    rng = np.random.default_rng(1)
    n_keys = A.MIN_SECTOR + 5
    keys = np.repeat([f"PRJ-{i:03d}" for i in range(n_keys)], 3)
    cands = pd.DataFrame({"project_key": keys, "sector": np.where(np.arange(len(keys)) < 3 * (A.MIN_SECTOR + 1), "S", "T")})
    cands["_code"] = pd.factorize(cands.project_key)[0]
    Z = rng.normal(size=(len(cands), len(A.STAGE)))
    q = Z[4] + 0.01                                             # nearest row belongs to PRJ-001
    pos, dist, basis = A.nearest(q, "PRJ-001", "S", cands, Z, k=10)
    rows = A.as_rows(cands, pos, dist, basis)
    assert basis == "sector" and (rows.sector == "S").all()     # S has exactly MIN_SECTOR others
    assert "PRJ-001" not in set(rows.project_key) and rows.project_key.is_unique and len(rows) == 10
    assert (np.diff(rows.distance) >= 0).all() and rows["rank"].tolist() == list(range(1, 11))
    # each analogue project is represented by its closest row
    for key, d in zip(rows.project_key, rows.distance):
        own = Z[(cands.project_key == key).to_numpy()]
        assert np.isclose(d, np.sqrt(((own - q) ** 2).mean(axis=1)).min())
    _, _, basis = A.nearest(q, "PRJ-000", "T", cands, Z)
    assert basis == "all"                                       # T has only 4 projects
    q_nan = q.copy()
    q_nan[1:] = np.nan                                          # only the first feature counts
    pos, dist, _ = A.nearest(q_nan, "PRJ-001", "S", cands, Z, k=3)
    assert np.allclose(dist, np.abs(Z[pos, 0] - q[0]))


def test_scenarios_capped_and_agency_fallback():
    n = A.MIN_ROWS
    hist = pd.DataFrame({"project_key": [f"PRJ-{i}" for i in range(n)], "period": ASOF, "is_completed": False,
                         "progress_velocity_4q": 2.0, "progress_velocity_2q": np.nan, "elapsed_ratio": 0.55,
                         "sector": "S", "agency": "AG", "physical_progress_pct": 50.0})
    cur = pd.DataFrame({"project_key": ["PRJ-X", "PRJ-Y"], "period": ASOF, "is_completed": False,
                        "progress_velocity_4q": [10.0, np.nan], "progress_velocity_2q": [np.nan, 1.0],
                        "elapsed_ratio": 0.55, "sector": "S", "agency": ["AG", "OTHER"],
                        "physical_progress_pct": [95.0, 40.0]})
    ctx = {"asof": ASOF, "feats": pd.concat([hist, cur], ignore_index=True),
           "span": pd.Series([120.0, 120.0], index=["PRJ-X", "PRJ-Y"])}
    t = A.scenario_table(cur, ctx)
    x, y = t[t.project_key == "PRJ-X"], t[t.project_key == "PRJ-Y"]
    assert len(x) == A.STEPS and x.quarter.iloc[0] == pd.Timestamp("2026-10-01")
    assert (x["continue"] == 100).all() and t[["continue", "recover", "agency"]].max().max() <= 100
    assert np.allclose(y["continue"], 40 + 1.0 * np.arange(1, A.STEPS + 1))     # 2q velocity when 4q is missing
    assert np.isclose(y.recover.iloc[0], 42.0)                  # sector median velocity 2.0 over the recent rows
    # AG has MIN_ROWS rows in the 0.5-0.6 bin; the step at 0.575 uses them, OTHER falls back to the sector
    assert x.agency_basis.iloc[0] == "agency" and np.isclose(x.agency.iloc[0], 97.0)
    assert y.agency_basis.iloc[0] == "sector"
    assert x.agency_basis.iloc[-1] == "all"                     # elapsed 0.75 at step 8: no history in that bin
