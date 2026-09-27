"""
Rolling-origin backtest: naive, old rule score, logistic regression and LightGBM (docs/IMPLEMENTATION_GUIDE_v2.md
B 3.1-3.3).

Run from repo root after the gold build:  python -m pipeline.run train

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, silver/coverage.parquet
Outputs  model/runs/<run_id>/: windows.json, backtest_folds.csv, backtest_summary.csv (b table), ablation.csv
         (c table), calibration.csv, shap_summary.csv

Windows come from coverage, never from fixed years: a quarter is reliable for a target when the fields its label
compares are >= 80% complete, and a cutoff c is usable when c and c + h are both reliable and c has labelled rows.
The newest usable cutoff is the test fold; the N_VAL usable cutoffs before it that sit in the newest reliable block
are the validation folds. At every cutoff c the models train on label rows whose outcome quarter t + h is <= c (the
label was known by c) and predict the rows at t = c. Completed projects are left out: there is nothing to warn about.
"""
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
NEEDS = {"y_date_push": ["anticipated_completion"], "y_cost_rev": ["anticipated_cost_cr"],
         "y_any": ["anticipated_completion", "anticipated_cost_cr"]}
RELIABLE = 0.8      # field completeness that makes a quarter reliable
N_VAL = 6           # validation cutoffs
N_TEST = 1          # newest usable cutoffs held out as test
MIN_ROWS = 100      # a cutoff needs this many labelled rows
KS = (50, 100)
ECE_BINS = 10
PK = ["project_key", "period"]
LGB_PARAMS = dict(objective="binary", n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=0,
                  n_jobs=8, verbose=-1)
LOGREG_PARAMS = dict(C=1.0, max_iter=2000)
ONEHOT_MIN = 20     # categories rarer than this in training share one "infrequent" column
ABLATION = [("state", ["state"]), ("+dynamics", ["state", "dynamics"]),
            ("+context", ["state", "dynamics", "context"]), ("+freshness", ["state", "dynamics", "context", "freshness"])]
ABLATION_MODEL = {"state": "lgbm_state", "+dynamics": "lgbm_state_dyn", "+context": "lgbm_state_dyn_ctx",
                  "+freshness": "lightgbm"}
MAIN = ["naive", "rule", "logreg", "lightgbm"]
WINDOW_RULE = ("A quarter is reliable for a target when every field its label compares (needs) is >= reliable_min "
               "complete in silver/coverage.parquet. A cutoff c is usable when c and c + h are reliable and c has "
               f">= {MIN_ROWS} labelled rows. test = the newest {N_TEST} usable cutoff(s). validation = the last "
               f"{N_VAL} usable cutoffs before test inside the newest reliable block that still has usable cutoffs. "
               "Each fold trains on every label row with target_period <= cutoff (outcome known by the cutoff, any "
               "quarter, reliable or not) and scores the rows at period == cutoff. Completed projects are excluded.")


def qindex(s):
    """Quarter number of datetimes (Series or DatetimeIndex) for quarter arithmetic."""
    s = pd.Series(s)
    return s.dt.year * 4 + (s.dt.month - 1) // 3


def load():
    feats = pd.read_parquet(GOLD / "features.parquet")
    labels = {h: pd.read_parquet(GOLD / f"labels_h{h}.parquet") for h in sorted({h for _, h in TARGETS})}
    manifest = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    return feats, labels, pd.read_parquet(SILVER / "coverage.parquet"), manifest


def frame(feats, labels, y):
    """Labelled rows for target y joined to their features at t; completed projects dropped."""
    d = labels[PK + ["target_period", y]].dropna(subset=[y]).merge(feats, on=PK, how="inner")
    d = d[~d.is_completed.astype(bool)].copy()
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
    iso = lambda p: pd.Timestamp(p).date().isoformat()
    return {
        "target": y, "horizon": h, "needs": NEEDS[y], "reliable_min": RELIABLE,
        "reliable_blocks": [[iso(date_of[a]), iso(date_of[b])] for a, b in blocks(rel)],
        "usable_cutoffs": [iso(c) for c in usable],
        "validation_block": [iso(date_of[block[0]]), iso(date_of[block[1]])],
        "validation": [iso(c) for c in val], "test": [iso(c) for c in test],
        "rows_per_cutoff": {iso(c): int(n[c]) for c in val + test},
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


def fit_lgbm(tr, cols, cats, y):
    m = lgb.LGBMClassifier(**LGB_PARAMS).fit(lgb_X(tr, cols, cats), tr[y])
    return m, lambda d: m.predict_proba(lgb_X(d, cols, cats))[:, 1]


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
                                       "y": te[y].to_numpy(), "p": p}))
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


def pooled(preds, folds, h):
    """Pooled metrics per model: PR-AUC, ROC-AUC, Brier and ECE on all fold rows together; Recall@k and
    precision@50 as total top-k hits over total positives (or slots), so each fold keeps its own top-k."""
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
                     "lead_time_q": lead[name]})
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


def run(run_dir):
    """Backtest every target in TARGETS and write the tables into run_dir. Returns what the registry needs."""
    t0 = time.time()
    feats, labels, coverage, manifest = load()
    groups, cats = manifest["features"], manifest["categorical"]
    step_cols = {ABLATION_MODEL[step]: [f for g in gs for f in groups[g]] for step, gs in ABLATION}
    cols = step_cols["lightgbm"]
    main = {"naive": (fit_naive, [], cats), "rule": (fit_rule, [], cats), "logreg": (fit_logreg, cols, cats),
            "lightgbm": (fit_lgbm, cols, cats)}
    ablation = {name: (fit_lgbm, c, cats) for name, c in step_cols.items() if name != "lightgbm"}
    wins, all_folds, summary, abl, calib, shap, frames, fold_metrics = {}, [], [], [], [], [], {}, {}
    for y, h in TARGETS:
        key = f"{y}_h{h}"
        d = frame(feats, labels[h], y)
        frames[y, h] = d
        w = wins[key] = windows(coverage, d, y, h)
        val, test = pd.to_datetime(w["validation"]), pd.to_datetime(w["test"])
        pv, fv, fitted = backtest(d, y, val, {**main, **ablation})
        pt, ft, _ = backtest(d, y, test, main)
        for split, p, f in [("val", pv, fv), ("test", pt, ft)]:
            f = f.assign(target=y, horizon=h, split=split)
            all_folds.append(f)
            s = pooled(p, f, h).assign(target=y, horizon=h, split=split)
            summary.append(s[s.model.isin(MAIN)])
            for name in MAIN:
                fold_metrics[key, split, name] = {"pooled": s[s.model == name].iloc[0].drop(
                    ["target", "horizon", "split", "model"]).to_dict(), "folds": f[f.model == name].to_dict("records")}
            if split == "val":
                prev = None
                for step, gs in ABLATION:
                    r = s[s.model == ABLATION_MODEL[step]].iloc[0].to_dict()
                    r.update(step=step, groups="+".join(gs), n_features=len(step_cols[ABLATION_MODEL[step]]),
                             pr_auc_gain=np.nan if prev is None else r["pr_auc"] - prev)
                    prev = r["pr_auc"]
                    abl.append(r)
                for name in MAIN:
                    q = p[p.model == name]
                    calib.append(calibration(q.y, q.p).assign(target=y, horizon=h, model=name))
                contrib = [fitted[c, "lightgbm"].booster_.predict(lgb_X(d[d.period == c], cols, cats),
                                                                  pred_contrib=True)[:, :-1] for c in val]
                mean_abs = np.abs(np.vstack(contrib)).mean(axis=0)
                group_of = {f: g for g, fs in groups.items() for f in fs}
                shap.append(pd.DataFrame({"target": y, "horizon": h, "feature": cols,
                                          "group": [group_of[c] for c in cols], "mean_abs_shap": mean_abs})
                            .sort_values("mean_abs_shap", ascending=False))
        print(f"  {key}: val {w['validation'][0]}..{w['validation'][-1]} test {w['test']}  {time.time() - t0:.0f}s")

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
    abl.to_csv(run_dir / "ablation.csv", index=False)
    calib.to_csv(run_dir / "calibration.csv", index=False)
    pd.concat(shap, ignore_index=True).to_csv(run_dir / "shap_summary.csv", index=False)
    (run_dir / "windows.json").write_text(json.dumps({
        "rule": WINDOW_RULE,
        "gold_version": manifest["gold_version"], "silver_version": manifest["silver_version"], **wins},
        indent=2), encoding="utf-8")
    return {"windows": wins, "frames": frames, "features": cols, "groups": groups, "categorical": cats,
            "metrics": fold_metrics, "summary": summary, "ablation": abl, "manifest": manifest}


def main(run_id=None):
    run_id = run_id or time.strftime("ML-%Y%m%d-%H%M%S", time.gmtime())
    res = run(RUNS / run_id)
    print(f"backtest {run_id}: {RUNS / run_id}")
    return run_id, res
