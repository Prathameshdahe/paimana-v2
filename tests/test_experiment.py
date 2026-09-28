import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import backtest, experiment, registry  # noqa: E402


def test_weighted_average_precision_matches_sklearn():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 400)
    p = np.round(rng.random(400), 2)                       # many tied scores
    W = rng.integers(0, 4, (5, 400))
    assert np.allclose(experiment.ap_weighted(y, p, np.ones(400)), average_precision_score(y, p))
    want = [average_precision_score(y, p, sample_weight=w) for w in W]
    assert np.allclose(experiment.ap_weighted(y, p, W), want)


def test_bootstrap_of_identical_models_is_zero_and_a_better_one_is_above_zero():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 600)
    groups = np.repeat(np.arange(200), 3)
    noise = [rng.random(600) for _ in range(2)]
    same = experiment.paired_bootstrap(y, groups, noise, noise, n_boot=200)
    assert np.allclose(same, 0)
    good = [0.6 * y + 0.4 * n for n in noise]
    lo, hi = experiment.ci(experiment.paired_bootstrap(y, groups, noise, good, n_boot=200))
    assert 0 < lo < hi


def test_bootstrap_resamples_projects_not_rows():
    """The challenger wins on one big project only: drawing whole projects makes the interval much wider than
    drawing rows would."""
    rng = np.random.default_rng(2)
    n = 1000
    y = rng.integers(0, 2, n)
    champ = rng.random(n)
    chall = champ.copy()
    big = np.arange(200)                                   # rows of project 0
    chall[big] = 0.5 * y[big] + 0.5 * champ[big]
    clustered = np.r_[np.zeros(200, int), np.arange(1, n - 199)]
    rows = np.arange(n)
    width = lambda g: np.diff(experiment.ci(experiment.paired_bootstrap(y, g, [champ], [chall], n_boot=400)))[0]
    assert width(clustered) > 2 * width(rows)


def test_rule_needs_both_blocks_a_margin_and_calibration():
    m = 0.01
    assert registry.rule({"val": 0.0, "flash": 0.02}, m, 0.08, 0.08)[0]
    assert not registry.rule({"val": -0.001, "flash": 0.05}, m, 0.08, 0.08)[0]       # lower on a block
    assert not registry.rule({"val": 0.005, "flash": 0.009}, m, 0.08, 0.08)[0]       # inside the noise margin
    assert not registry.rule({"val": 0.02, "flash": 0.02}, m, 0.101, 0.08)[0]        # ECE > champion + 0.02
    ok, why = registry.rule({"val": 0.02, "flash": 0.0}, m, 0.09, 0.08)
    assert ok and "val +0.0200" in why and "clears" in why


PERIODS = pd.date_range("2021-01-01", "2026-07-01", freq="QS").astype("datetime64[us]")


def synthetic(n_keys=240, seed=4):
    """A gold-like panel: one feature x, y_any_h2 labels driven by x, a reliable coverage table (the validation
    block ends 2024-10, the flash block starts 2025-07) and a manifest."""
    rng = np.random.default_rng(seed)
    keys = [f"PRJ-{k:06d}" for k in range(n_keys)]
    feats = pd.DataFrame({"project_key": np.repeat(keys, len(PERIODS)), "period": np.tile(PERIODS, n_keys)})
    feats["x"] = rng.normal(size=len(feats))
    feats["noise"] = rng.normal(size=len(feats))
    feats["is_completed"] = False
    lab = feats[["project_key", "period"]].assign(target_period=feats.period + pd.DateOffset(months=6))
    lab = lab[lab.target_period <= PERIODS[-1]]
    z = feats.loc[lab.index, "x"] + rng.normal(size=len(lab))
    lab = lab.assign(y_any=(z > 0.3).astype("Int8"), y_date_push=(z > 0.3).astype("Int8"),
                     y_cost_rev=(z > 1.5).astype("Int8"))
    cov = pd.DataFrame({"period": PERIODS, "anticipated_completion": 0.95, "anticipated_cost_cr": 0.95})
    cov.loc[cov.period >= "2025-01-01", ["anticipated_completion", "anticipated_cost_cr"]] = 0.5
    man = {"gold_version": "test", "features": {g: [] for _, gs in backtest.ABLATION for g in gs},
           "categorical": []}
    man["features"]["state"] = ["noise"]
    return feats, {2: lab, 4: lab.iloc[:0]}, cov, man


@pytest.fixture
def harness(monkeypatch, tmp_path):
    data = synthetic()
    monkeypatch.setattr(backtest, "load", lambda: data)
    monkeypatch.setattr(registry, "load", lambda: {"runs": [], "champions": {}, "decisions": []})
    monkeypatch.setattr(experiment, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(backtest, "LGB_PARAMS", {**backtest.LGB_PARAMS, "n_estimators": 60, "learning_rate": 0.1,
                                                          "n_jobs": 1})
    return data, tmp_path


def test_harness_null_candidate_has_zero_deltas_and_fails(harness):
    _, tmp = harness
    t = experiment.run("null", seeds=(0, 1), targets=["y_any_h2"], n_boot=50, out=tmp)
    assert set(t.block) == {"val", "flash"} and (t.delta_pr_auc == 0).all() and (t.ci_lo == 0).all()
    assert (t.decision == "fail").all() and (tmp / "null.csv").exists()
    assert t.set_index("block").loc["flash", "n_folds"] == 3                   # 2025-07 .. 2026-01
    again = experiment.run("null", seeds=(0, 1), targets=["y_any_h2"], n_boot=50, out=tmp)   # from the cache
    pd.testing.assert_frame_equal(t.drop(columns="runtime_s"), again.drop(columns="runtime_s"))


def test_harness_passes_an_informative_point_in_time_column(harness):
    (feats, *_), tmp = harness
    cand = experiment.Candidate("x itself", extra=lambda ctx: ctx.feats[backtest.PK + ["x"]])
    t = experiment.run("x", cand, seeds=(0,), targets=["y_any_h2"], n_boot=50, out=tmp)
    assert (t.delta_pr_auc > 0.05).all() and (t.ci_lo > 0).all() and (t.decision == "pass").all()
    assert '"identical": true' in t.point_in_time.iloc[0]


def test_harness_refuses_a_column_that_reads_the_future(harness):
    _, tmp = harness
    leak = experiment.Candidate("key mean of x over all periods", extra=lambda ctx: ctx.feats[backtest.PK].assign(
        xbar=ctx.feats.groupby("project_key").x.transform("mean")))
    with pytest.raises(AssertionError, match="change when the data are cut"):
        experiment.run("leak", leak, seeds=(0,), targets=["y_any_h2"], n_boot=10, out=tmp)


def test_ship_guard_needs_a_ci_above_zero_on_a_block_that_clears_the_margin():
    b = lambda d, lo: {"delta_pr_auc": d, "ci_lo": lo}
    assert experiment.robust(True, [b(0.02, 0.001), b(0.0, -0.01)], 0.01)
    assert not experiment.robust(True, [b(0.02, -0.001), b(0.005, 0.001)], 0.01)   # the CI above 0 is under margin
    assert not experiment.robust(False, [b(0.02, 0.01)], 0.01)                     # the rule failed
