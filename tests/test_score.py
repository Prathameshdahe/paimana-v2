import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import score  # noqa: E402


def test_tiers_are_sized_by_rank():
    p = np.random.default_rng(0).random(200)
    t = score.tiers(p, np.zeros(200, bool))
    assert t.tier.value_counts().to_dict() == {"Critical": 10, "High": 30, "Medium": 60, "Low": 100}
    assert (t.tier == t.tier_by_rank).all() and not t.stagnation_override.any()
    order = t.tier.map(score.TIERS.index).to_numpy()[np.argsort(-p)]
    assert (np.diff(order) >= 0).all()                                 # riskier scores never get a lower tier
    assert t.tier_rank_pct.min() == 1 / 200 and t.tier_rank_pct.max() == 1


def test_stagnation_override_lifts_at_most_one_tier():
    p = np.linspace(1, 0, 100)
    t = score.tiers(p, np.ones(100, bool))
    lift = t.tier_by_rank.map(score.TIERS.index) - t.tier.map(score.TIERS.index)
    assert set(lift) == {0, 1}
    assert (lift[t.tier_by_rank == "Critical"] == 0).all()             # never above Critical
    assert (t.stagnation_override == (lift == 1)).all()
    assert t.tier.value_counts()["Critical"] == 20                     # 5 by rank + 15 lifted from High


def test_log_append_is_idempotent(tmp_path):
    path = tmp_path / "log.parquet"
    rows = pd.DataFrame({"project_key": ["PRJ-1", "PRJ-2"], "asof": pd.Timestamp("2026-07-01"), "model_version": "m1",
                         "p_any_2q": [0.9, 0.1], "p_date_push_2q": [0.8, 0.1], "p_cost_rev_2q": [0.2, 0.0],
                         "tier": ["Critical", "Low"]})
    first = score.append_log(rows, path)
    assert len(first) == 2 and first.y_any_2q.isna().all()
    assert len(score.append_log(rows, path)) == 2                      # same key again: nothing added
    later = rows.assign(model_version="m2")
    log = score.append_log(later, path)
    assert len(log) == 4 and not log.duplicated(score.LOG_KEY).any()
    pd.testing.assert_frame_equal(pd.read_parquet(path), log.reset_index(drop=True))
