"""
Discrete-time survival model: one LightGBM hazard model over person-periods (project, t, k), k = 1..K quarters
ahead, whose cumulative hazard gives P(first deterioration by k) for every k from one fit: the runway curve
(3, 6, 12 and 18 months from one model, monotone in k by construction), with censoring handled properly (an
ongoing project contributes every quarter it was observed, instead of being dropped for lacking an observation
at t + h).

Measured against the per-horizon champions by the harness:  python -m ml.experiment s1_survival
Served (the runway columns of the predictions file):        python -m pipeline.run score  (ml/score.py)

Frame. For a feature row (key, t) the gold labels y_h1 .. y_hK (pipeline/gold.py build_labels: deteriorated against
the value at t by t + h, a date pushed >= 3 months or the cost up >= 5%; null when there is no observation at t + h
or the printed basis changed) give the person-periods: k = 1, 2, ... while the row is at risk; the event at k is
y_hk; the row leaves the frame after its first event (k = its event time) or at the first k whose label is unknown
(censored). A label unknown at k but known 0 at a later k' reads as 0 at k: no deterioration against t by k' means
none by k, up to the 1-2% of pushes that revert (gold manifest, label_noise); such a filled period is realised at
t + k', not t + k, so the backtest never reads it before the observation it comes from.

Model. LightGBM binary on the features at t plus k (a numeric feature, so the hazard may rise or fall with the
quarter ahead), the target's own LightGBM params. P(event by h) = 1 - prod_{k <= h} (1 - hazard_k).

Point in time. A person-period (t, k) is realised at its target_period t + k (t + k' when filled): at cutoff c the
model trains on the person-periods with target_period <= c, and the harness fit function reads c from the champion's
training rows (their newest outcome quarter), so both models see the same information.
"""
import functools
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest as bt  # noqa: E402

K = 6                      # quarters ahead: 18 months, the longest runway horizon
PK = bt.PK
KCOL = "k"


@functools.lru_cache(maxsize=1)
def labels():
    """The gold labels of horizons 1..K (cached for the process)."""
    return bt.load(horizons=range(1, K + 1))[1]


def wide(rows, labs, y, k=K):
    """[n, k] float array of the target y of rows at horizons 1..k (NaN: unknown), from the labels frames labs."""
    Y = np.full((len(rows), k), np.nan)
    for h in range(1, k + 1):
        lab = labs[h][PK + [y]].rename(columns={y: "_y"})
        Y[:, h - 1] = rows[PK].merge(lab, on=PK, how="left", validate="1:1")["_y"].astype("float64").to_numpy()
    return Y


def at_risk(Y):
    """From the wide labels: (risk, event, source) arrays [n, k]. risk marks the person-periods in the frame (at risk
    at k: no event and a known label at every earlier k, and a known label at k), event the deterioration at k, and
    source the horizon whose observation the label comes from (k itself, or the later k' of a filled zero)."""
    Y, n, k = Y.copy(), *Y.shape
    src = np.tile(np.arange(1, k + 1), (n, 1)).astype(float)
    for j in range(k - 2, -1, -1):                       # a known 0 at j + 1 fills an unknown j
        fill = np.isnan(Y[:, j]) & (Y[:, j + 1] == 0)
        Y[fill, j], src[fill, j] = 0, src[fill, j + 1]
    known, ev = ~np.isnan(Y), Y == 1
    alive, risk = np.ones(n, bool), np.zeros((n, k), bool)
    for j in range(k):
        risk[:, j] = alive & known[:, j]
        alive = risk[:, j] & ~ev[:, j]
    return risk, ev, src


def person_period(rows, labs, y, k=K):
    """The long frame: each row of rows (features at t) repeated for every k it is at risk at, with k, event and
    target_period (the quarter the label is realised: t + source)."""
    risk, ev, src = at_risk(wide(rows, labs, y, k))
    i, j = np.nonzero(risk)
    out = rows.iloc[i].reset_index(drop=True)
    out[KCOL] = (j + 1).astype("float64")
    out["event"] = ev[i, j].astype("int64")
    out["target_period"] = (out.period.dt.to_period("Q") + src[i, j].astype(int)).dt.to_timestamp()
    out["target_period"] = out.target_period.astype(out.period.dtype)
    return out


def fit_hazard(pp, cols, cats, params=None):
    """LightGBM hazard model on the person-period frame pp: the features cols plus k."""
    params = {k_: v for k_, v in (params or bt.LGB_PARAMS).items() if k_ != "half_life_q"}
    return lgb.LGBMClassifier(**params).fit(bt.lgb_X(pp, cols + [KCOL], cats), pp.event)


def curve(m, d, cols, cats, k=K):
    """[n, k] cumulative probabilities of an event by 1..k quarters for the rows of d: 1 - prod(1 - hazard)."""
    haz = np.column_stack([m.predict_proba(bt.lgb_X(d.assign(**{KCOL: float(j)}), cols + [KCOL], cats))[:, 1]
                           for j in range(1, k + 1)])
    return 1 - np.cumprod(1 - haz, axis=1)


class Hazard:
    """The hazard models of one target over cutoffs: fit once per (cutoff, columns, params) and reused, since the
    same model gives every horizon (the harness runs the four y_any horizons one after the other)."""

    def __init__(self, feats, labs, y, k=K):
        self.pp = person_period(feats[~feats.is_completed.astype(bool)], labs, y, k)
        self.k, self.models = k, {}

    def fitted(self, cutoff, cols, cats, params):
        key = (pd.Timestamp(cutoff), tuple(cols), tuple(cats), json.dumps(params, sort_keys=True, default=str))
        if key not in self.models:
            self.models[key] = fit_hazard(self.pp[self.pp.target_period <= cutoff], cols, cats, params)
        return self.models[key]

    def fit(self, h, params):
        """A backtest fit function for horizon h: (tr, cols, cats, y) -> (model, predict P(event by h)); the cutoff
        is tr's newest outcome quarter, so the person-periods used are realised by it."""
        def fit(tr, cols, cats, y):
            m = self.fitted(tr.target_period.max(), cols, cats, params)
            return m, lambda d: curve(m, d, cols, cats, h)[:, h - 1]
        return fit


def runway(feats, asof, cur, cols, cats, params, y="y_any", k=K, skip=None):
    """The served curve: the hazard model on every person-period realised by asof, and P(event by 1..k) for the
    current rows cur as a frame of runway_<y>_<k>q columns. skip(train, cur, cols) -> bool mask of rows not to score
    (ml/score.py passes unseen_missing: a null in a feature never null in training, the classifiers' rule)."""
    hz = Hazard(feats, labels(), y, k)
    pp = hz.pp[hz.pp.target_period <= asof]
    m = fit_hazard(pp, cols, cats, params)
    c = curve(m, cur, cols, cats, k)
    if skip is not None:
        c[np.asarray(skip(pp, cur, cols), bool)] = np.nan
    return pd.DataFrame({f"runway_{y.removeprefix('y_')}_{j}q": c[:, j - 1] for j in range(1, k + 1)},
                        index=cur.index), len(pp)
