import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import backtest, survival  # noqa: E402

Q = pd.date_range("2020-01-01", periods=12, freq="QS").astype("datetime64[us]")
PK = backtest.PK


def labs_from(Y, keys, t):
    """Labels frames {h: PK + y_any} from a wide array Y [n, K] (NaN unknown) for rows (keys[i], t)."""
    out = {}
    for h in range(1, Y.shape[1] + 1):
        v = Y[:, h - 1]
        out[h] = pd.DataFrame({"project_key": keys, "period": t, "y_any": pd.array(v, dtype="Float64")})
        out[h] = out[h][out[h].y_any.notna()].assign(y_any=lambda d: d.y_any.astype("Int8"),
                                                    target_period=t + pd.DateOffset(months=3 * h))
    return out


def test_person_periods_stop_at_the_event_or_the_first_unknown_and_fill_zeros_backwards():
    keys = [f"P{i}" for i in range(5)]
    n = np.nan
    Y = np.array([[0, 0, 1, 0, 0, 0],       # event at k = 3: at risk 1..3, event at 3 only
                  [0, 0, 0, 0, 0, 0],       # never: 6 periods, no event
                  [0, n, n, n, n, n],       # censored after k = 1
                  [n, 0, n, 1, n, n],       # k = 1 filled from k = 2 (realised at t + 2q); k = 3 unknown: censored
                  [1, 1, 1, 1, 1, 1]])      # event at k = 1: one period
    rows = pd.DataFrame({"project_key": keys, "period": Q[0], "x": np.arange(5.0), "is_completed": False})
    pp = survival.person_period(rows, labs_from(Y, keys, Q[0]), "y_any")
    got = pp.groupby("project_key").agg(ks=("k", list), ev=("event", list))
    assert got.loc["P0"].ks == [1, 2, 3] and got.loc["P0"].ev == [0, 0, 1]
    assert got.loc["P1"].ks == [1, 2, 3, 4, 5, 6] and got.loc["P1"].ev == [0] * 6
    assert got.loc["P2"].ks == [1] and got.loc["P2"].ev == [0]
    assert got.loc["P3"].ks == [1, 2] and got.loc["P3"].ev == [0, 0]
    assert got.loc["P4"].ks == [1] and got.loc["P4"].ev == [1]
    p3 = pp[pp.project_key == "P3"].set_index("k").target_period
    assert p3[1.0] == p3[2.0] == Q[2]                       # the filled k = 1 is realised with the k = 2 observation
    p1 = pp[pp.project_key == "P1"].set_index("k").target_period
    assert p1.tolist() == list(Q[1:7])
    assert (pp.x == pp.project_key.str[1:].astype(float)).all()     # the features at t travel with every period


def synthetic(n_keys=300, seed=0):
    """Feature rows over several t whose hazard rises with x; labels by horizon from the simulated event time."""
    rng = np.random.default_rng(seed)
    t = np.repeat(Q[:6], n_keys)
    keys = np.tile([f"PRJ-{i:04d}" for i in range(n_keys)], 6)
    x = rng.normal(size=len(t))
    feats = pd.DataFrame({"project_key": keys, "period": t, "x": x, "is_completed": False})
    haz = 1 / (1 + np.exp(-(x - 1.5)))                              # per-quarter hazard
    Y = np.zeros((len(t), survival.K))
    for i in range(len(t)):
        ev = np.flatnonzero(rng.random(survival.K) < haz[i])
        if len(ev):
            Y[i, ev[0]:] = 1
        seen = 6 - int(np.searchsorted(Q, t[i]))                    # quarters observed after t within Q[:7]
        Y[i, max(seen, 0):] = np.nan
    return feats, {h: pd.concat([labs_from(Y[t == c], keys[t == c], c)[h] for c in Q[:6]], ignore_index=True)
                   for h in range(1, survival.K + 1)}


def test_curve_is_monotone_ranks_by_hazard_and_matches_the_horizon_labels():
    feats, labs = synthetic()
    hz = survival.Hazard(feats, labs, "y_any")
    params = {**backtest.LGB_PARAMS, "n_estimators": 60, "n_jobs": 1}
    m = hz.fitted(Q[6], ["x"], [], params)
    d = feats[feats.period == Q[0]]
    c = survival.curve(m, d, ["x"], [])
    assert c.shape == (len(d), survival.K) and (np.diff(c, axis=1) >= -1e-12).all() and (c <= 1).all()
    assert np.corrcoef(c[:, 1], d.x)[0, 1] > 0.8                  # higher x, higher P(by 2q)
    lab2 = labs[2][labs[2].period == Q[0]].merge(d, on=PK)
    p2 = survival.curve(m, lab2, ["x"], [], 2)[:, 1]
    from sklearn.metrics import average_precision_score
    assert average_precision_score(lab2.y_any.astype(int), p2) > 0.6


def test_hazard_fit_reads_only_person_periods_realised_by_the_cutoff():
    feats, labs = synthetic()
    params = {**backtest.LGB_PARAMS, "n_estimators": 40, "n_jobs": 1}
    c = Q[3]
    a = survival.Hazard(feats, labs, "y_any").fitted(c, ["x"], [], params)
    flipped = {h: lab.assign(y_any=pd.array(np.where(lab.target_period > c, 1 - lab.y_any.astype(int),
                                                     lab.y_any.astype(int)), dtype="Int8"))
               for h, lab in labs.items()}
    b = survival.Hazard(feats, flipped, "y_any").fitted(c, ["x"], [], params)
    d = feats[feats.period == c]
    assert np.allclose(survival.curve(a, d, ["x"], []), survival.curve(b, d, ["x"], []))
    # the backtest fit function takes its cutoff from the champion's training rows
    tr = backtest.frame(feats, labs[2], "y_any", 2)
    tr = tr[tr.target_period <= c]
    m, predict = survival.Hazard(feats, labs, "y_any").fit(2, params)(tr, ["x"], [], "y_any")
    assert np.allclose(predict(d), survival.curve(a, d, ["x"], [], 2)[:, 1])


def test_hazard_models_are_reused_across_horizons():
    feats, labs = synthetic(n_keys=80)
    hz = survival.Hazard(feats, labs, "y_any")
    params = {**backtest.LGB_PARAMS, "n_estimators": 10, "n_jobs": 1}
    tr = backtest.frame(feats, labs[2], "y_any", 2)
    tr = tr[tr.target_period <= Q[4]]
    hz.fit(2, params)(tr, ["x"], [], "y_any")
    hz.fit(4, params)(tr, ["x"], [], "y_any")
    assert len(hz.models) == 1
