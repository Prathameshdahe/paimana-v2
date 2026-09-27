import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import backtest  # noqa: E402

Q = pd.date_range("2020-01-01", periods=16, freq="QS").astype("datetime64[us]")


def labelled(h, n_keys=30, seed=3):
    """Synthetic modelling frame: every key has a row at each quarter whose outcome quarter t + h is still in Q."""
    rng = np.random.default_rng(seed)
    t = Q[:-h]
    d = pd.DataFrame({"project_key": np.repeat([f"PRJ-{k:06d}" for k in range(n_keys)], len(t)),
                      "period": np.tile(t, n_keys)})
    d["target_period"] = d.period + pd.DateOffset(months=3 * h)
    d["x"] = rng.normal(size=len(d))
    d["y"] = (d.x + rng.normal(size=len(d)) > 0).astype(int)
    d["slipped_last_period"] = rng.integers(0, 2, len(d)).astype(float)
    return d


def test_no_training_row_is_realised_after_the_cutoff():
    for h in (2, 4):
        d = labelled(h)
        seen = []

        def spy(tr, cols, cats, y):
            seen.append(tr)
            return None, lambda te: np.full(len(te), tr[y].mean())

        cutoffs = Q[h + 3:h + 7]
        models = {"spy": (spy, ["x"], []), "naive": (backtest.fit_naive, [], []),
                  "logreg": (backtest.fit_logreg, ["x"], [])}
        preds, folds, _ = backtest.backtest(d, "y", cutoffs, models)
        assert len(seen) == len(cutoffs)
        for c, tr in zip(cutoffs, seen):
            assert (tr.period + pd.DateOffset(months=3 * h) <= c).all()      # t + h <= cutoff for every row
            assert tr.period.max() == c - pd.DateOffset(months=3 * h)        # and the rule is not stricter
            assert (tr.period < c).all()
        assert (folds.max_train_target <= folds.cutoff).all()
        for c in cutoffs:                                                    # scored rows are the rows at t = c
            assert (preds[preds.cutoff == c].groupby("model").size() == (d.period == c).sum()).all()


def test_windows_come_from_coverage():
    periods = list(pd.date_range("2010-01-01", "2012-10-01", freq="QS")) + \
        list(pd.date_range("2015-01-01", "2016-10-01", freq="QS"))
    cov = pd.DataFrame({"period": pd.to_datetime(periods).astype("datetime64[us]"),
                        "anticipated_completion": 0.9, "anticipated_cost_cr": 1.0})
    cov.loc[cov.period == "2016-01-01", "anticipated_completion"] = 0.5
    have = set(cov.period)
    t = [p for p in cov.period if p + pd.DateOffset(months=6) in have]      # labels need an observation at t + 2
    d = pd.DataFrame({"period": np.repeat(t, 150)})
    w = backtest.windows(cov, d, "y_date_push", 2)
    assert w["test"] == ["2016-04-01"]
    assert w["validation_block"] == ["2015-01-01", "2015-10-01"]
    assert w["validation"] == ["2015-01-01", "2015-04-01", "2015-10-01"]     # 2015-07 + 2q = 2016-01 is unreliable
    assert backtest.windows(cov, d, "y_cost_rev", 2)["validation_block"] == ["2015-01-01", "2016-10-01"]


def test_topk_shares_tied_slots():
    y, p = np.array([1, 0, 1, 0]), np.array([0.9, 0.5, 0.5, 0.5])
    assert backtest.topk(y, p, 2) == 1 + 1 / 3
    assert backtest.ece(np.array([0, 1] * 5), np.full(10, 0.5)) == 0
