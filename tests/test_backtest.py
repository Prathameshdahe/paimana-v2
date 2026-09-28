import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

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


def test_flash_block_takes_every_cutoff_with_enough_rows():
    periods = pd.date_range("2024-01-01", "2026-07-01", freq="QS").astype("datetime64[us]")
    cov = pd.DataFrame({"period": periods, "anticipated_completion": 0.9, "anticipated_cost_cr": 1.0})
    cov.loc[cov.period >= backtest.FLASH_FROM, "anticipated_completion"] = 0.6    # flash prints no anticipated date
    t = [p for p in periods if p + pd.DateOffset(months=6) <= periods[-1]]
    d = pd.DataFrame({"period": np.repeat(t, [50 if p == pd.Timestamp("2025-10-01") else 150 for p in t])})
    w = backtest.windows(cov, d, "y_date_push", 2)
    assert w["test"] == ["2024-10-01"] and "2025-07-01" not in w["validation"]
    assert w["flash"] == ["2025-07-01", "2026-01-01"]                          # 2025-10 has < MIN_ROWS rows
    assert w["rows_per_cutoff"]["2026-01-01"] == 150


def test_validation_and_flash_blocks_never_share_a_cutoff():
    """The cost fields stay reliable into the flash era, so the cost revision's usable cutoffs run up to the test
    fold; its validation block still stops before FLASH_FROM."""
    periods = pd.date_range("2022-01-01", "2026-07-01", freq="QS").astype("datetime64[us]")
    cov = pd.DataFrame({"period": periods, "anticipated_completion": 0.9, "anticipated_cost_cr": 1.0})
    cov.loc[cov.period >= backtest.FLASH_FROM, "anticipated_completion"] = 0.6
    t = [p for p in periods if p + pd.DateOffset(months=6) <= periods[-1]]
    d = pd.DataFrame({"period": np.repeat(t, 150)})
    w = backtest.windows(cov, d, "y_cost_rev", 2)
    assert w["test"] == ["2026-01-01"] and "2025-07-01" in w["usable_cutoffs"]
    assert w["validation"] == ["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01", "2025-01-01", "2025-04-01"]
    assert not set(w["validation"]) & set(w["flash"])
    assert w["flash"] == ["2025-07-01", "2025-10-01", "2026-01-01"]


def test_not_yet_due_slice():
    d = labelled(2)
    d["months_to_anticipated_completion"] = np.tile([3.0, 12.0, np.nan], len(d))[:len(d)]
    assert backtest.not_yet_due(d.iloc[:3]).tolist() == [False, True, False]  # due by t + 2q, after it, unknown
    cutoffs = Q[5:8]
    preds, folds, _ = backtest.backtest(d, "y", cutoffs, {"logreg": (backtest.fit_logreg, ["x"], [])})
    s = backtest.pooled(preds, folds, 2).iloc[0]
    rows = d[d.period.isin(cutoffs) & (d.months_to_anticipated_completion > 6)]
    assert s.nyd_n == len(rows) and s.nyd_base_rate == rows.y.mean()
    assert 0 < s.nyd_pr_auc <= 1 and 0 <= s.nyd_precision_50 <= 1


def test_train_from_cuts_only_its_own_target(monkeypatch):
    periods = pd.date_range("2012-01-01", periods=12, freq="QS").astype("datetime64[us]")
    feats = pd.DataFrame({"project_key": "PRJ-000001", "period": periods, "is_completed": False, "x": 1.0})
    labels = feats[["project_key", "period"]].assign(target_period=periods + pd.DateOffset(months=12), y_any=1)
    assert len(backtest.frame(feats, labels, "y_any", 4)) == 12                 # no target has a start today
    monkeypatch.setattr(backtest, "TRAIN_FROM", {("y_any", 4): pd.Timestamp("2014-01-01")})
    assert backtest.frame(feats, labels, "y_any", 4).period.min() == pd.Timestamp("2014-01-01")
    assert len(backtest.frame(feats, labels, "y_any", 2)) == len(backtest.frame(feats, labels, "y_any")) == 12


def test_platt_folds_are_realised_by_the_cutoff_and_fix_a_skew():
    c = pd.Timestamp("2024-07-01")
    for h in (2, 4):
        folds = backtest.calibration_folds(c, h)
        assert len(folds) == backtest.PLATT_FOLDS and max(folds) == c - pd.DateOffset(months=3 * h)
    rng = np.random.default_rng(0)
    true = rng.uniform(0.05, 0.6, 4000)
    y = (rng.random(4000) < true).astype(int)
    skewed = np.clip(true + 0.25, 0, 0.99)                     # over-predicts by 25 points
    cal = backtest.platt_fit(y, skewed)
    fixed = backtest.platt_apply(cal, skewed)
    assert abs(fixed.mean() - y.mean()) < 0.01 < abs(skewed.mean() - y.mean())
    assert (np.argsort(fixed) == np.argsort(skewed)).all()      # ranks unchanged
    assert backtest.platt_fit(np.ones(500), skewed[:500]) is None
    assert (backtest.platt_apply(None, skewed) == skewed).all()


def test_calibrate_reads_only_folds_realised_by_the_cutoff():
    rng = np.random.default_rng(1)
    q = pd.date_range("2023-01-01", periods=8, freq="QS")
    pool = pd.concat([pd.DataFrame({"cutoff": c, "model": "m", "project_key": [f"P{i}" for i in range(300)],
                                    "y": rng.integers(0, 2, 300), "p": rng.uniform(0.2, 0.8, 300)}) for c in q])
    c = q[-1]
    target = pool[pool.cutoff == c]
    a = backtest.calibrate(target, pool, 2)
    late = pool.cutoff > c - pd.DateOffset(months=6)            # c - 1q and c itself: labels not realised by c
    noisy = pool.assign(y=np.where(late, 1 - pool.y, pool.y), p=np.where(late, 0.99, pool.p))
    b = backtest.calibrate(target, noisy, 2)
    assert np.allclose(a.p, b.p) and not np.allclose(a.p, target.p)


def test_half_life_weights_and_target_params(monkeypatch):
    d = labelled(2, n_keys=60)
    params = {**backtest.LGB_PARAMS, "n_estimators": 20, "n_jobs": 1}
    q = backtest.qindex(d.period).to_numpy()
    w = 0.5 ** ((q.max() - q) / 8)
    want = lgb.LGBMClassifier(**params).fit(backtest.lgb_X(d, ["x"], []), d.y, sample_weight=w)
    got, _ = backtest.fit_lgbm(d, ["x"], [], "y", params={**params, "half_life_q": 8})
    plain, _ = backtest.fit_lgbm(d, ["x"], [], "y", params=params)
    p = lambda m: m.predict_proba(d[["x"]])[:, 1]
    assert np.allclose(p(got), p(want)) and not np.allclose(p(plain), p(want))
    monkeypatch.setattr(backtest, "TARGET_PARAMS", {("y_any", 4): {"half_life_q": 8}})
    assert backtest.lgb_params("y_any", 4)["half_life_q"] == 8 and "half_life_q" not in backtest.lgb_params("y_any", 2)


def test_interval_backtest_trains_on_realised_rows_and_scores_coverage_and_pinball():
    d = labelled(2, n_keys=80)
    d["y_months"] = 3 * d.x + np.random.default_rng(5).normal(size=len(d))
    cutoffs = Q[6:8]
    p = backtest.quantile_backtest(d, "y_months", cutoffs, ["x"], [])
    assert (p.groupby("cutoff").size() == 80).all() and (p.p05 <= p.p50).all() and (p.p50 <= p.p95).all()
    m = backtest.interval_metrics(p)
    assert 0.6 < m["coverage"] < 1 and m["coverage"] + m["below_p05"] + m["above_p95"] == pytest.approx(1)
    assert m["pinball_p50"] == pytest.approx(0.5 * np.mean(np.abs(p.y - p.p50)))
    late = d.assign(y_months=np.where(d.target_period > cutoffs[0], 1e6, d.y_months))   # outcomes after the cutoff
    q = backtest.quantile_backtest(late, "y_months", cutoffs[:1], ["x"], [])
    assert np.allclose(q[["p05", "p50", "p95"]], p[p.cutoff == cutoffs[0]][["p05", "p50", "p95"]])
