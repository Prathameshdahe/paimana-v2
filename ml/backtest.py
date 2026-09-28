"""
Rolling-origin backtest: naive, old rule score, logistic regression and LightGBM (docs/IMPLEMENTATION_GUIDE_v2.md
B 3.1-3.3).

Run from repo root after the gold build:  python -m pipeline.run train

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, silver/coverage.parquet
Outputs  model/runs/<run_id>/: windows.json, backtest_folds.csv, backtest_summary.csv (b table), ablation.csv
         (c table), calibration.csv, shap_summary.csv, platt.json (the served calibrators), intervals.csv

Windows come from coverage, never from fixed years: a quarter is reliable for a target when the fields its label
compares are >= 80% complete, and a cutoff c is usable when c and c + h are both reliable and c has labelled rows.
The newest usable cutoff is the test fold; the N_VAL usable cutoffs before it that sit in the newest reliable block
are the validation folds. At every cutoff c the models train on label rows whose outcome quarter t + h is <= c (the
label was known by c) and predict the rows at t = c. Completed projects are left out: there is nothing to warn about.

The validation block is quarterly-report (QPISR) era: anticipated vs anticipated dates, and 0% remarks or progress at
some folds. Live scoring and the test fold are the flash-report era (revised vs revised, a higher slip rate), where
val rankings have flipped. So a second block, flash, holds every cutoff from FLASH_FROM with >= MIN_ROWS labelled rows
(these fail the coverage rule: flash reports print no anticipated fields). For the 2-quarter targets it includes the
test cutoff, so there the test fold is no longer independent of promotion. Every pooled row also reports the
not-yet-due slice (nyd_*): rows whose anticipated completion falls after the outcome quarter t + h, the projects an
early warning is for (the top 50 of a fold is otherwise almost all projects already due inside the horizon).

A target in TRAIN_FROM trains on rows from that date only (none today). A target in CALIBRATED gets a Platt
calibrator fitted per cutoff on the model's own predictions at the PLATT_FOLDS cutoffs whose labels are realised by
it; the summary's calibration column says which. The ablation table compares the raw LightGBM scores.

The score step's intervals (LightGBM quantile regressors at 5/50/95% of the months pushed and the cost change % by
t + 2q, fit_quantiles) are backtested the same way on the validation and flash cutoffs of their binary counterparts
(y_date_push, y_cost_rev): intervals.csv has the p05-p95 coverage (nominal 90%), the share below p05 and above p95,
the mean width and the pinball loss at each quantile. A conformal widening from folds realised by the cutoff was
tried and left out (docs/MODEL_UPGRADES_2026-09.md): those folds already cover >= 90%, so it moved nothing.
"""
import functools
import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "dataset" / "gold"
SILVER = ROOT / "dataset" / "silver"
RUNS = ROOT / "model" / "runs"

TARGETS = [("y_any", 2), ("y_date_push", 2), ("y_cost_rev", 2), ("y_any", 4)]   # first is the primary target
# y_any_h2 has its own model: 1 - (1 - p_date)(1 - p_cost) from the date and cost models (which train on more rows)
# lost 0.020 validation PR-AUC [-0.027, -0.013], and its mean with the direct model 0.009 [-0.013, -0.004]
NEEDS = {"y_date_push": ["anticipated_completion"], "y_cost_rev": ["anticipated_cost_cr"],
         "y_any": ["anticipated_completion", "anticipated_cost_cr"]}
RELIABLE = 0.8      # field completeness that makes a quarter reliable
N_VAL = 6           # validation cutoffs
N_TEST = 1          # newest usable cutoffs held out as test
MIN_ROWS = 100      # a cutoff needs this many labelled rows
FLASH_FROM = pd.Timestamp("2025-07-01")     # first flash-report quarter (the serving format)
# target -> first training quarter. Empty: training y_any_h4 on t >= 2014 only gained 0.023 validation PR-AUC but
# lost 0.024 [-0.043, -0.006] on the flash block (3 seeds, paired project bootstrap; one fold of 335 rows), and the
# 2-quarter targets lost on flash as well (y_any_h2 -0.014), so every target keeps every row.
TRAIN_FROM = {}
# Platt scaling, fitted on each model's predictions at the PLATT_FOLDS cutoffs c - h, ..., c - h - PLATT_FOLDS + 1,
# whose labels are all realised by c. Only the cost revision: for y_any_h2 and y_date_push_h2 it halved validation
# ECE but doubled flash-block ECE (0.061 -> 0.135, 0.065 -> 0.125) and lowered flash PR-AUC (-0.004, -0.007):
# calibrators fitted on quarterly-report folds pull scores down where the flash-era slip rate is higher. y_any_h4 got worse on
# validation (its folds are 4-7 quarters old).
CALIBRATED = {("y_cost_rev", 2)}
PLATT_FOLDS = 4
PLATT_FILE = "platt.json"
KS = (50, 100)
ECE_BINS = 10
PK = ["project_key", "period"]
LGB_PARAMS = dict(objective="binary", n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=0,
                  n_jobs=8, verbose=-1)
# target -> LightGBM params that differ from LGB_PARAMS for that target alone. One enters only after it passed the
# promotion rule on that target in ml/experiment.py (3 seeds, paired project bootstrap) with a CI above 0 on a block.
# half_life_q is not a LightGBM param: fit_lgbm turns it into sample weights that halve every half_life_q quarters
# of row age. Tried and left out (docs/MODEL_UPGRADES_2026-09.md): the y_any_h2 validation search's picks lost
# 0.038-0.055 flash PR-AUC on y_any_h2 and y_date_push_h2 (early stopping on an inner time split kept 20-400 trees)
# and 0.018-0.024 validation on y_any_h4; the mean of 5 seeds stayed inside the noise everywhere (y_any_h2 flash
# +0.0048 against a 0.0076 margin); age weights lost on both blocks for y_any_h2 and y_cost_rev_h2 and on the flash
# block for y_date_push_h2; flash-report rows weighted 3x cleared the noise nowhere (y_cost_rev_h2 flash -0.010).
TARGET_PARAMS = {}
LOGREG_PARAMS = dict(C=1.0, max_iter=2000)
ONEHOT_MIN = 20     # categories rarer than this in training share one "infrequent" column
ABLATION = [("state", ["state"]), ("+dynamics", ["state", "dynamics"]), ("+context", ["state", "dynamics", "context"]),
            ("+freshness", ["state", "dynamics", "context", "freshness"]),
            ("+external", ["state", "dynamics", "context", "freshness", "external"])]
ABLATION_MODEL = {"state": "lgbm_state", "+dynamics": "lgbm_state_dyn", "+context": "lgbm_state_dyn_ctx",
                  "+freshness": "lgbm_state_dyn_ctx_fresh", "+external": "lightgbm"}
ABLATION_GAINS = ["pr_auc", "precision_50", "recall_100"]     # each step minus the step before
MAIN = ["naive", "rule", "logreg", "lightgbm"]
# the score step's interval models: name -> (h = 2 regression label, the binary target whose windows it is tested on)
QUANTILE_TARGETS = {"months": ("y_months", "y_date_push"), "cost_pct": ("y_cost_pct", "y_cost_rev")}
ALPHAS = {"p05": 0.05, "p50": 0.5, "p95": 0.95}
WINDOW_RULE = ("A quarter is reliable for a target when every field its label compares (needs) is >= reliable_min "
               "complete in silver/coverage.parquet. A cutoff c is usable when c and c + h are reliable and c has "
               f">= {MIN_ROWS} labelled rows. test = the newest {N_TEST} usable cutoff(s). validation = the last "
               f"{N_VAL} usable cutoffs before test inside the newest reliable block that still has usable cutoffs. "
               "Each fold trains on every label row with target_period <= cutoff (outcome known by the cutoff, any "
               "quarter, reliable or not) and scores the rows at period == cutoff. Completed projects are excluded. "
               f"flash = every cutoff from {FLASH_FROM.date()} with >= {MIN_ROWS} labelled rows (reliability not "
               "required), scored the same way as a second validation block.")


def qindex(s):
    """Quarter number of datetimes (Series or DatetimeIndex) for quarter arithmetic."""
    s = pd.Series(s)
    return s.dt.year * 4 + (s.dt.month - 1) // 3


def load():
    feats = pd.read_parquet(GOLD / "features.parquet")
    labels = {h: pd.read_parquet(GOLD / f"labels_h{h}.parquet") for h in sorted({h for _, h in TARGETS})}
    manifest = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    return feats, labels, pd.read_parquet(SILVER / "coverage.parquet"), manifest


def frame(feats, labels, y, h=None):
    """Labelled rows for target y at horizon h joined to their features at t; completed projects and rows before
    the target's TRAIN_FROM dropped."""
    d = labels[PK + ["target_period", y]].dropna(subset=[y]).merge(feats, on=PK, how="inner")
    d = d[~d.is_completed.astype(bool) & (d.period >= TRAIN_FROM.get((y, h), d.period.min()))].copy()
    d[y] = d[y].astype(int)
    return d.sort_values(PK, ignore_index=True)


def blocks(qs):
    """Runs of consecutive quarter numbers as [(first, last)]."""
    qs, out = sorted(qs), []
    for q in qs:
        if out and q == out[-1][1] + 1:
            out[-1][1] = q
        else:
            out.append([q, q])
    return [tuple(b) for b in out]


def windows(coverage, d, y, h):
    """Validation and test cutoffs for target y at horizon h from field coverage (see module docstring)."""
    q = qindex(coverage.period)
    date_of = dict(zip(q, coverage.period))
    rel = set(q[coverage[NEEDS[y]].ge(RELIABLE).all(axis=1).to_numpy()])
    n = d.groupby("period").size()
    nq = qindex(n.index)
    ok = (n.to_numpy() >= MIN_ROWS) & nq.isin(rel).to_numpy() & (nq + h).isin(rel).to_numpy()
    usable = list(n.index[ok])
    test, rest = usable[-N_TEST:], usable[:-N_TEST]
    last = qindex([rest[-1]])[0]
    block = next(b for b in blocks(rel) if b[0] <= last <= b[1])
    val = [c for c in rest if qindex([c])[0] >= block[0]][-N_VAL:]
    flash = [c for c in n.index if c >= FLASH_FROM and n[c] >= MIN_ROWS]
    iso = lambda p: pd.Timestamp(p).date().isoformat()
    return {
        "target": y, "horizon": h, "needs": NEEDS[y], "reliable_min": RELIABLE,
        "reliable_blocks": [[iso(date_of[a]), iso(date_of[b])] for a, b in blocks(rel)],
        "usable_cutoffs": [iso(c) for c in usable],
        "validation_block": [iso(date_of[block[0]]), iso(date_of[block[1]])],
        "validation": [iso(c) for c in val], "test": [iso(c) for c in test], "flash": [iso(c) for c in flash],
        "rows_per_cutoff": {iso(c): int(n[c]) for c in sorted(set(val + test + flash))},
        "train_rule": f"label rows with target_period (t + {h}q) <= cutoff",
    }


def cat_cols(cols, cats):
    return [c for c in cols if c in cats]


def lgb_X(d, cols, cats):
    """LightGBM frame: categoricals as pandas category. At predict time LightGBM maps them onto the training
    categories stored in the model, so a category unseen in training becomes missing."""
    X = d[cols].copy()
    for c in cat_cols(cols, cats):
        X[c] = X[c].astype("category")
    return X


def fit_naive(tr, cols, cats, y):
    """Slipped last period, slips next: training positive rate for each slipped_last_period value."""
    key = lambda d: d.slipped_last_period.fillna(0)
    rate, prior = tr[y].groupby(key(tr)).mean(), tr[y].mean()
    return rate.to_dict(), lambda d: key(d).map(rate).fillna(prior).to_numpy(float)


def fit_rule(tr, cols, cats, y):
    """Old composite rule score (pipeline/build_real_projects.py), mapped to a probability by a one-feature
    logistic fit on the training rows; the ranking is the rule score's own."""
    m = LogisticRegression().fit(tr[["rule_score"]].fillna(0), tr[y])
    return m, lambda d: m.predict_proba(d[["rule_score"]].fillna(0))[:, 1]


def fit_logreg(tr, cols, cats, y):
    """Logistic regression: median impute + missing flags + standardise numerics, one-hot categoricals."""
    cat = cat_cols(cols, cats)
    num = [c for c in cols if c not in cat]
    prep = ColumnTransformer([
        ("num", make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                              StandardScaler()), num),
        ("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=ONEHOT_MIN), cat)])
    m = make_pipeline(prep, LogisticRegression(**LOGREG_PARAMS))

    def X(d):
        x = d[cols].copy()
        x[cat] = x[cat].fillna("NA").astype(object)
        return x

    m.fit(X(tr), tr[y])
    return m, lambda d: m.predict_proba(X(d))[:, 1]


def lgb_params(y, h):
    """The LightGBM params of target (y, h): LGB_PARAMS with its TARGET_PARAMS."""
    return {**LGB_PARAMS, **TARGET_PARAMS.get((y, h), {})}


def fit_lgbm(tr, cols, cats, y, params=None, weight=None):
    """LightGBM with LGB_PARAMS, or with params (a target's lgb_params, a registry entry's own). A half_life_q in
    params weights each training row 0.5 ** (age / half_life_q), age = quarters from its t to the newest training t;
    weight(tr) multiplies in any other sample weights."""
    params = dict(params or LGB_PARAMS)
    half = params.pop("half_life_q", None)
    w = np.ones(len(tr))
    if half:
        q = qindex(tr.period).to_numpy()
        w = w * 0.5 ** ((q.max() - q) / half)
    if weight is not None:
        w = w * weight(tr)
    m = lgb.LGBMClassifier(**params).fit(lgb_X(tr, cols, cats), tr[y],
                                         sample_weight=None if half is None and weight is None else w)
    return m, lambda d: m.predict_proba(lgb_X(d, cols, cats))[:, 1]


def qframe(feats, lab, y):
    """Rows with a known regression label y joined to their features, completed projects dropped."""
    d = lab[PK + ["target_period", y]].dropna(subset=[y]).merge(feats, on=PK, how="inner")
    return d[~d.is_completed.astype(bool)].sort_values(PK, ignore_index=True)


def fit_quantiles(tr, y, cols, cats):
    """One LightGBM quantile regressor of y per ALPHAS level (LGB_PARAMS). Returns predict(d) -> (rows x levels),
    sorted along each row so the quantiles never cross."""
    X = lgb_X(tr, cols, cats)
    ms = [lgb.LGBMRegressor(**{**LGB_PARAMS, "objective": "quantile", "alpha": a}).fit(X, tr[y])
          for a in ALPHAS.values()]
    return lambda d: np.sort(np.column_stack([m.predict(lgb_X(d, cols, cats)) for m in ms]), axis=1)


def quantile_backtest(d, y, cutoffs, cols, cats):
    """Rolling origin for fit_quantiles: at each cutoff c, fitted on rows with target_period <= c, the rows at c."""
    out = []
    for c in cutoffs:
        tr, te = d[d.target_period <= c], d[d.period == c]
        q = fit_quantiles(tr, y, cols, cats)(te)
        out.append(pd.DataFrame({"cutoff": c, "project_key": te.project_key.to_numpy(), "y": te[y].to_numpy(float),
                                 **{s: q[:, i] for i, s in enumerate(ALPHAS)}}))
    return pd.concat(out, ignore_index=True)


def pinball(y, q, a):
    u = np.asarray(y, float) - np.asarray(q, float)
    return float(np.mean(np.maximum(a * u, (a - 1) * u)))


def interval_metrics(p):
    """p05-p95 coverage, the shares below and above, mean width and the pinball loss at each ALPHAS level."""
    inside = (p.y >= p.p05) & (p.y <= p.p95)
    return {"n": len(p), "coverage": float(inside.mean()), "below_p05": float((p.y < p.p05).mean()),
            "above_p95": float((p.y > p.p95).mean()), "mean_width": float((p.p95 - p.p05).mean()),
            **{f"pinball_{s}": pinball(p.y, p[s], a) for s, a in ALPHAS.items()}}


def topk(y, p, k):
    """Positives among the k highest scores; rows tied at the k-th score share the remaining slots pro rata."""
    k = min(k, len(p))
    kth = np.sort(p)[::-1][k - 1]
    above, tied = p > kth, p == kth
    return float(y[above].sum() + (k - above.sum()) * y[tied].mean())


def ece(y, p, bins=ECE_BINS):
    """Expected calibration error over equal-width probability bins."""
    t = calibration(y, p, bins)
    return float((t.n * (t.obs_rate - t.mean_pred).abs()).sum() / len(y))


def calibration(y, p, bins=ECE_BINS):
    b = np.minimum((np.asarray(p) * bins).astype(int), bins - 1)
    t = pd.DataFrame({"bin": b, "y": y, "p": p}).groupby("bin").agg(n=("y", "size"), mean_pred=("p", "mean"),
                                                                     obs_rate=("y", "mean"))
    return t.reset_index()


def score(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    both = 0 < y.mean() < 1
    r = {"n": len(y), "n_pos": int(y.sum()), "base_rate": float(y.mean()),
         "pr_auc": float(average_precision_score(y, p)) if both else np.nan,
         "roc_auc": float(roc_auc_score(y, p)) if both else np.nan,
         "brier": float(brier_score_loss(y, p)), "ece": ece(y, p)}
    for k in KS:
        r[f"hits_{k}"] = topk(y, p, k)
        r[f"recall_{k}"] = r[f"hits_{k}"] / max(r["n_pos"], 1)
    r["precision_50"] = r["hits_50"] / min(50, len(y))
    return r


def not_yet_due(d):
    """Rows whose anticipated completion is after the outcome quarter t + h (a null date is not in the slice)."""
    if "months_to_anticipated_completion" not in d:
        return np.zeros(len(d), bool)
    h_months = (d.target_period.dt.year - d.period.dt.year) * 12 + d.target_period.dt.month - d.period.dt.month
    return (d.months_to_anticipated_completion > h_months).to_numpy()


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def platt_fit(y, p):
    """Platt scaling p -> sigmoid(a * logit(p) + b) fitted on (y, p), or None when there are fewer than MIN_ROWS rows
    or only one class (the scores then stay raw)."""
    y = np.asarray(y, int)
    if len(y) < MIN_ROWS or y.min() == y.max():
        return None
    m = LogisticRegression(C=1e6).fit(logit(p)[:, None], y)
    return {"a": float(m.coef_[0, 0]), "b": float(m.intercept_[0]), "n": int(len(y)), "n_pos": int(y.sum())}


def platt_apply(cal, p):
    """Scores p through a platt_fit result (None or no "a": unchanged)."""
    p = np.asarray(p, float)
    return p if not cal or "a" not in cal else 1 / (1 + np.exp(-(cal["a"] * logit(p) + cal["b"])))


def calibration_folds(c, h, k=PLATT_FOLDS):
    """The k newest cutoffs whose labels are all realised by c: c - h, ..., c - h - k + 1 quarters."""
    return [pd.Timestamp(c) - pd.DateOffset(months=3 * (h + j)) for j in range(k)]


def calibrate(preds, pool, h):
    """Each (cutoff, model) of preds through a Platt fit on the same model's pool predictions at the cutoff's
    calibration folds, whose labels are realised by the cutoff (no leakage). Ranks within a fold are unchanged."""
    out = []
    for (c, name), g in preds.groupby(["cutoff", "model"], sort=False):
        src = pool[(pool.model == name) & pool.cutoff.isin(calibration_folds(c, h))]
        out.append(g.assign(p=platt_apply(platt_fit(src.y, src.p), g.p)))
    return pd.concat(out).loc[preds.index]


def rescore(preds, folds):
    """folds with the metric columns recomputed from preds (after calibration)."""
    s = pd.DataFrame([{"cutoff": c, "model": m, **score(g.y, g.p)}
                      for (c, m), g in preds.groupby(["cutoff", "model"], sort=False)])
    return folds[["cutoff", "model", "n_train", "max_train_target"]].merge(s, on=["cutoff", "model"], how="left")


def backtest(d, y, cutoffs, models):
    """Rolling origin. models = {name: (fit_fn, cols, cats)}. At each cutoff c every model is fitted on rows with
    target_period <= c and scores the rows at period == c. Returns (predictions, folds, fitted models)."""
    preds, folds, fitted = [], [], {}
    for c in cutoffs:
        tr, te = d[d.target_period <= c], d[d.period == c]
        for name, (fn, cols, cats) in models.items():
            m, predict = fn(tr, cols, cats, y)
            p = predict(te)
            fitted[c, name] = m
            preds.append(pd.DataFrame({"cutoff": c, "model": name, "project_key": te.project_key.to_numpy(),
                                       "y": te[y].to_numpy(), "p": p, "not_yet_due": not_yet_due(te)}))
            folds.append({"cutoff": c, "model": name, "n_train": len(tr), "max_train_target": tr.target_period.max(),
                          **score(te[y], p)})
    return pd.concat(preds, ignore_index=True), pd.DataFrame(folds), fitted


def lead_times(preds, h, k=100):
    """Mean quarters from a project's first top-k flag in any fold to the slip it was flagged for, over top-k true
    positives. The slip is dated at the outcome quarter t + h (the report that first shows it), so the value is at
    least h and at most h + the number of earlier folds; a project flagged earlier for a different slip counts from
    that earlier flag. Ties in the top-k are broken by project_key."""
    out = {}
    for name, d in preds.groupby("model"):
        d = d.sort_values(["cutoff", "p", "project_key"], ascending=[True, False, True])
        top = d[d.groupby("cutoff").cumcount() < k]
        first = top.groupby("project_key").cutoff.transform("min")
        tp = top.y == 1
        lead = qindex(top.cutoff[tp]).to_numpy() + h - qindex(first[tp]).to_numpy()
        out[name] = float(lead.mean()) if len(lead) else np.nan
    return out


def slice_metrics(d, prefix="nyd_"):
    """PR-AUC and precision@50 (each fold's own top 50) of the rows of one model's predictions d."""
    both = len(d) and 0 < d.y.mean() < 1
    folds = [(g.y.to_numpy(float), g.p.to_numpy(float)) for _, g in d.groupby("cutoff")]
    slots = sum(min(50, len(y)) for y, _ in folds)
    return {f"{prefix}n": len(d), f"{prefix}base_rate": float(d.y.mean()) if len(d) else np.nan,
            f"{prefix}pr_auc": float(average_precision_score(d.y, d.p)) if both else np.nan,
            f"{prefix}precision_50": sum(topk(y, p, 50) for y, p in folds) / slots if slots else np.nan}


def pooled(preds, folds, h):
    """Pooled metrics per model: PR-AUC, ROC-AUC, Brier and ECE on all fold rows together; Recall@k and
    precision@50 as total top-k hits over total positives (or slots), so each fold keeps its own top-k; nyd_* the
    same on the not-yet-due slice."""
    lead = lead_times(preds, h)
    rows = []
    for name, d in preds.groupby("model", sort=False):
        f = folds[folds.model == name]
        r = score(d.y, d.p)
        for k in KS:
            r[f"hits_{k}"] = f[f"hits_{k}"].sum()
            r[f"recall_{k}"] = r[f"hits_{k}"] / max(f.n_pos.sum(), 1)
        r["precision_50"] = r["hits_50"] / np.minimum(50, f.n).sum()
        rows.append({"model": name, "n_folds": len(f), **r, "pr_auc_fold_mean": f.pr_auc.mean(),
                     "lead_time_q": lead[name], **slice_metrics(d[d.not_yet_due.astype(bool)])})
    return pd.DataFrame(rows)


def deltas(summary):
    """(b) table: each model's pooled metrics minus each baseline's, within target, horizon and split."""
    out = []
    for _, g in summary.groupby(["target", "horizon", "split"], sort=False):
        g = g.set_index("model")
        for b in ["naive", "rule", "logreg"]:
            for m in ["pr_auc", "recall_100", "brier"]:
                g[f"{m}_vs_{b}"] = g[m] - g.loc[b, m]
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)


def model_cols(groups):
    """The model's feature list: every group of the ABLATION step that ABLATION_MODEL maps to "lightgbm"."""
    return [f for step, gs in ABLATION if ABLATION_MODEL[step] == "lightgbm" for g in gs for f in groups[g]]


def run(run_dir, extra=None):
    """Backtest every target in TARGETS and write the tables into run_dir. extra = {target key: {name: (fit_fn, cols,
    cats)}} adds models to a target's main table (the registry's re-scored incumbent). Returns what the registry
    needs."""
    extra = extra or {}
    t0 = time.time()
    feats, labels, coverage, manifest = load()
    groups, cats = manifest["features"], manifest["categorical"]
    step_cols = {ABLATION_MODEL[step]: [f for g in gs for f in groups[g]] for step, gs in ABLATION}
    cols = step_cols["lightgbm"]
    assert cols == model_cols(groups)
    wins, all_folds, summary, abl, calib, shap, frames, fold_metrics, platt = {}, [], [], [], [], [], {}, {}, {}
    latest = feats.period.max()
    for y, h in TARGETS:
        key = f"{y}_h{h}"
        fit = functools.partial(fit_lgbm, params=lgb_params(y, h))
        main = {"naive": (fit_naive, [], cats), "rule": (fit_rule, [], cats), "logreg": (fit_logreg, cols, cats),
                "lightgbm": (fit, cols, cats)}
        abl_models = {name: (fit, c, cats) for name, c in step_cols.items() if name != "lightgbm"}
        d = frame(feats, labels[h], y, h)
        frames[y, h] = d
        w = wins[key] = windows(coverage, d, y, h)
        val, test, flash = (pd.to_datetime(w[k]) for k in ["validation", "test", "flash"])
        models, names = {**main, **extra.get(key, {})}, MAIN + list(extra.get(key, {}))
        pv, fv, fitted = backtest(d, y, val, {**models, **abl_models})
        splits = {"val": (pv[pv.model.isin(names)], fv[fv.model.isin(names)]),
                  "test": backtest(d, y, test, models)[:2]}
        if len(flash):
            splits["flash"] = backtest(d, y, flash, models)[:2]
        method = "none"
        if (y, h) in CALIBRATED:
            method = f"platt_k{PLATT_FOLDS}"
            done = {c for p, _ in splits.values() for c in p.cutoff}
            want = {c for x in [*done, latest] for c in calibration_folds(x, h)}
            more = sorted(c for c in want - done if (d.period == c).any())
            pool = pd.concat([p for p, _ in splits.values()] + ([backtest(d, y, more, models)[0]] if more else []))
            pool = pool.drop_duplicates(["cutoff", "model", "project_key"])    # val and flash can share cutoffs
            for split, (p, f) in splits.items():
                cp = calibrate(p, pool, h)
                splits[split] = (cp, rescore(cp, f))
            # the serving calibrator: the folds realised by the latest period
            now = pool[pool.cutoff.isin(calibration_folds(latest, h))]
            platt[key] = {name: {**(platt_fit(g.y, g.p) or {}),
                                 "fit_cutoffs": sorted(str(c.date()) for c in g.cutoff.unique())}
                          for name, g in now.groupby("model")}
        for split, (p, f) in splits.items():
            f = f.assign(target=y, horizon=h, split=split)
            all_folds.append(f)
            s = pooled(p, f, h).assign(target=y, horizon=h, split=split, calibration=method)
            summary.append(s)
            for name in names:
                fold_metrics[key, split, name] = {"pooled": s[s.model == name].iloc[0].drop(
                    ["target", "horizon", "split", "model"]).to_dict(), "folds": f[f.model == name].to_dict("records")}
        # the ablation compares raw LightGBM scores; the calibration table shows the served (calibrated) ones
        all_folds.append(fv[~fv.model.isin(names)].assign(target=y, horizon=h, split="val"))
        s, prev = pooled(pv, fv, h).assign(target=y, horizon=h), None
        for step, gs in ABLATION:
            r = s[s.model == ABLATION_MODEL[step]].iloc[0].to_dict()
            r.update(step=step, groups="+".join(gs), n_features=len(step_cols[ABLATION_MODEL[step]]),
                     **{f"{m}_gain": np.nan if prev is None else r[m] - prev[m] for m in ABLATION_GAINS})
            prev = r
            abl.append(r)
        pc = splits["val"][0]
        for name in names:
            q = pc[pc.model == name]
            calib.append(calibration(q.y, q.p).assign(target=y, horizon=h, model=name))
        contrib = [fitted[c, "lightgbm"].booster_.predict(lgb_X(d[d.period == c], cols, cats),
                                                          pred_contrib=True)[:, :-1] for c in val]
        mean_abs = np.abs(np.vstack(contrib)).mean(axis=0)
        group_of = {f: g for g, fs in groups.items() for f in fs}
        shap.append(pd.DataFrame({"target": y, "horizon": h, "feature": cols,
                                  "group": [group_of[c] for c in cols], "mean_abs_shap": mean_abs})
                    .sort_values("mean_abs_shap", ascending=False))
        print(f"  {key}: val {w['validation'][0]}..{w['validation'][-1]} test {w['test']} flash {w['flash']} "
              f"calibration {method}  {time.time() - t0:.0f}s")

    ivals = []
    for name, (y, like) in QUANTILE_TARGETS.items():
        d = qframe(feats, labels[2], y)
        for split, k in (("val", "validation"), ("flash", "flash")):
            cs = pd.to_datetime(wins.get(f"{like}_h2", {}).get(k, []))
            if len(cs):
                ivals.append({"target": name, "label": y, "split": split, "n_folds": len(cs),
                              **interval_metrics(quantile_backtest(d, y, cs, cols, cats))})
    ivals = pd.DataFrame(ivals)
    if len(ivals):
        print("  intervals: " + "  ".join(f"{r.target} {r.split} coverage {r.coverage:.3f} pinball p50 "
                                          f"{r.pinball_p50:.3f}" for r in ivals.itertuples())
              + f"  {time.time() - t0:.0f}s")

    run_dir.mkdir(parents=True, exist_ok=True)
    lead = ["target", "horizon"]
    folds = pd.concat(all_folds, ignore_index=True)
    folds = folds[lead + ["split"] + [c for c in folds.columns if c not in lead + ["split"]]]
    summary = deltas(pd.concat(summary, ignore_index=True))
    summary = summary[lead + ["split"] + [c for c in summary.columns if c not in lead + ["split"]]]
    abl = pd.DataFrame(abl)
    abl = abl[lead + ["step", "groups", "n_features", "model"] +
              [c for c in abl.columns if c not in lead + ["step", "groups", "n_features", "model", "split"]]]
    calib = pd.concat(calib, ignore_index=True)[lead + ["model", "bin", "n", "mean_pred", "obs_rate"]]
    folds.to_csv(run_dir / "backtest_folds.csv", index=False)
    summary.to_csv(run_dir / "backtest_summary.csv", index=False)
    ivals.to_csv(run_dir / "intervals.csv", index=False)
    abl.to_csv(run_dir / "ablation.csv", index=False)
    calib.to_csv(run_dir / "calibration.csv", index=False)
    pd.concat(shap, ignore_index=True).to_csv(run_dir / "shap_summary.csv", index=False)
    (run_dir / PLATT_FILE).write_text(json.dumps({"asof": str(latest.date()), "method": f"platt_k{PLATT_FOLDS}",
                                                  **platt}, indent=2), encoding="utf-8")
    (run_dir / "windows.json").write_text(json.dumps({
        "rule": WINDOW_RULE,
        "gold_version": manifest["gold_version"], "silver_version": manifest["silver_version"], **wins},
        indent=2), encoding="utf-8")
    return {"windows": wins, "frames": frames, "features": cols, "groups": groups, "categorical": cats,
            "metrics": fold_metrics, "summary": summary, "ablation": abl, "manifest": manifest, "platt": platt,
            "intervals": ivals}


def main(run_id=None, extra=None):
    run_id = run_id or time.strftime("ML-%Y%m%d-%H%M%S", time.gmtime())
    res = run(RUNS / run_id, extra)
    print(f"backtest {run_id}: {RUNS / run_id}")
    return run_id, res
