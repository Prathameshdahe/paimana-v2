"""
Score the current portfolio (docs/IMPLEMENTATION_GUIDE_v2.md B 3.5).

Run from repo root after train:  python -m pipeline.run score

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, model/registry.json,
         silver/observations.parquet, silver/project_master.parquet
Outputs  gold/predictions_<model_version>_<asof YYYY-MM>.parquet, gold/predictions_latest.json,
         gold/prediction_log.parquet (appended, idempotent on project_key + asof + model_version)

At asof (default: the latest period) the current projects are those in the latest report with a feature row at
asof that are not completed. Each target's champion type from the registry is refitted on every label row realised
by asof (t + h <= asof) and scores them; LightGBM quantile regressors (5/50/95) trained on the same h=2 rows give
the slip-months and cost-% intervals. SHAP top-5 (log-odds contributions) come from the p_any_2q model. Tiers go
by rank of p_any_2q, not by threshold; the stagnation override lifts a project one tier.
A score whose model never saw one of the row's null features in training is left null (see unseen_missing): today
that is the date-based scores of projects with no anticipated completion date (no_completion_date). A project
without p_any_2q gets no tier.
"""
import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest, registry  # noqa: E402

GOLD, SILVER, PK = backtest.GOLD, backtest.SILVER, backtest.PK
LOG = GOLD / "prediction_log.parquet"
PROBS = {"p_date_push_2q": ("y_date_push", 2), "p_cost_rev_2q": ("y_cost_rev", 2), "p_any_2q": ("y_any", 2),
         "p_any_4q": ("y_any", 4)}
QUANTILES = {"months": "y_months", "cost_pct": "y_cost_pct"}     # h = 2 regression targets
ALPHAS = {"p05": 0.05, "p50": 0.5, "p95": 0.95}
TIERS = ["Critical", "High", "Medium", "Low"]
TIER_TOP = [0.05, 0.20, 0.50, 1.0]      # cumulative rank share at the bottom of each tier
STAGNANT_Q, STAGNANT_ELAPSED = 2, 0.3
SHAP_K = 5
SHORT = {"lightgbm": "lgbm", "logreg": "logreg"}
LOG_KEY = ["project_key", "asof", "model_version"]
LOG_COLS = LOG_KEY + ["p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "tier"]
REALISED = {"y_any_2q": "Int8", "y_date_push_2q": "Int8", "y_cost_rev_2q": "Int8", "realised_period": "datetime64[us]"}
DISPLAY = ["project_name", "sector", "state", "agency", "ministry", "anticipated_cost_cr", "expenditure_cr",
           "physical_progress_pct", "anticipated_completion"]


def tiers(p, stagnant):
    """Rank tiers of scores p (1 = riskiest; ties broken by position) and the stagnation override, which lifts a
    flagged project one tier, never above Critical. A null score gets no tier and is not counted in the rank shares.
    Returns tier_rank_pct, tier_by_rank, tier, stagnation_override."""
    p = pd.Series(np.asarray(p, float))
    scored = p.notna().to_numpy()
    rank_pct = p.rank(method="first", ascending=False).to_numpy() / max(scored.sum(), 1)
    by_rank = np.searchsorted(TIER_TOP, np.nan_to_num(rank_pct), side="left")
    lifted = np.asarray(stagnant, bool) & (by_rank > 0) & scored
    names = np.array(TIERS, dtype=object)
    name = lambda i: np.where(scored, names[i], None)
    return pd.DataFrame({"tier_rank_pct": rank_pct, "tier_by_rank": name(by_rank), "tier": name(by_rank - lifted),
                         "stagnation_override": lifted})


def unseen_missing(train, X, cols):
    """Rows of X with a null in a feature that is never null in train. LightGBM keeps no missing branch for such a
    feature and reads the null as 0 (months_to_anticipated_completion = 0: deadline this month), and imputing it is
    no better, so these rows are not scored."""
    never = [c for c in cols if train[c].notna().all()]
    return X[never].isna().any(axis=1).to_numpy()


def champion(reg, y, h):
    return next(r for r in reg["runs"] if r["entry_id"] == reg["champions"][f"{y}_h{h}"]["entry_id"])


def shap_top5(booster, X, k=SHAP_K):
    """Per row, the k features with the largest |SHAP| as JSON [{feature, value, contribution}]."""
    c = booster.predict(X, pred_contrib=True)[:, :-1]
    top = np.argsort(-np.abs(c), axis=1, kind="stable")[:, :k]
    vals = X.astype(object).where(X.notna(), None).to_numpy()
    show = lambda v: round(v, 4) if isinstance(v, float) else v
    return [json.dumps([{"feature": X.columns[j], "value": show(vals[i, j]), "contribution": round(float(c[i, j]), 4)}
                        for j in row]) for i, row in enumerate(top)]


def append_log(new, path=LOG):
    """Append scored rows to the prediction log; a (project_key, asof, model_version) already there is kept as is,
    so a re-run adds nothing and never wipes realised outcomes."""
    new = new[LOG_COLS].assign(**{c: pd.Series(pd.NA, index=new.index, dtype=t) for c, t in REALISED.items()})
    if path.exists():
        new = pd.concat([pd.read_parquet(path), new], ignore_index=True).drop_duplicates(LOG_KEY, keep="first")
    new.to_parquet(path, index=False)
    return new


def current(feats, obs, master, asof):
    """Feature rows at asof of the latest report's projects, completed ones dropped, with the display fields.
    The display agency is the printed name (the feature frame's is the normalised one, not a model input)."""
    keys = master.loc[master.in_latest_report, "project_key"]
    cur = feats[(feats.period == asof) & feats.project_key.isin(keys) & ~feats.is_completed.astype(bool)]
    show = obs.loc[obs.period == asof, ["project_key"] + [c for c in DISPLAY if c not in cur or c == "agency"]]
    return cur.drop(columns="agency").merge(show, on="project_key", how="left", validate="1:1").sort_values(
        "project_key", ignore_index=True)


def main(asof=None):
    t0 = time.time()
    feats, labels, _, man = backtest.load()
    obs = pd.read_parquet(SILVER / "observations.parquet")
    master = pd.read_parquet(SILVER / "project_master.parquet")
    reg = registry.load()
    asof = pd.Timestamp(asof) if asof else feats.period.max()
    cur = current(feats, obs, master, asof)

    lead = champion(reg, "y_any", 2)
    mv = f"{SHORT[lead['model']]}-any2q-{lead['run_id'].removeprefix('ML-')}"
    out = cur[["project_key"]].assign(asof=asof, model_version=mv, gold_version=man["gold_version"],
                                      silver_version=man["silver_version"])
    fitted = {}
    for col, (y, h) in PROBS.items():
        e = champion(reg, y, h)
        d = backtest.frame(feats, labels[h], y)
        d = d[d.target_period <= asof]
        fitted[col], predict = registry.CANDIDATES[e["model"]](d, e["feature_list"], e["categorical"], y)
        skip = unseen_missing(d, cur, e["feature_list"])
        out[col] = np.where(skip, np.nan, predict(cur))
        print(f"  {col}: {e['model']} ({e['entry_id']}) refit on {len(d)} rows, {skip.sum()} rows not scored")

    cols, cats = lead["feature_list"], lead["categorical"]
    Xc = backtest.lgb_X(cur, cols, cats)
    for name, y in QUANTILES.items():
        lab = labels[2]
        d = lab.loc[lab.target_period <= asof, PK + ["target_period", y]].dropna(subset=[y]).merge(feats, on=PK)
        d = d[~d.is_completed.astype(bool)].sort_values(PK, ignore_index=True)
        X = backtest.lgb_X(d, cols, cats)
        q = np.column_stack([lgb.LGBMRegressor(**{**backtest.LGB_PARAMS, "objective": "quantile", "alpha": a})
                             .fit(X, d[y]).predict(Xc) for a in ALPHAS.values()])
        q = np.sort(q, axis=1)          # crossing quantiles are reordered, so p05 <= p50 <= p95
        q[unseen_missing(d, cur, cols)] = np.nan
        for i, s in enumerate(ALPHAS):
            out[f"{name}_{s}"] = q[:, i]
        print(f"  {name}: quantile LightGBM on {len(d)} rows")

    stagnant = (cur.stagnation_quarters >= STAGNANT_Q) & (cur.elapsed_ratio >= STAGNANT_ELAPSED)
    out = pd.concat([out, tiers(out.p_any_2q, stagnant)], axis=1)
    out["no_completion_date"] = cur.months_to_anticipated_completion.isna()
    m = fitted["p_any_2q"]
    # ponytail: SHAP only for a LightGBM champion; a logistic champion leaves the column null
    out["shap_top5_json"] = shap_top5(m.booster_, Xc) if lead["model"] == "lightgbm" else None
    out["shap_top5_json"] = out.shap_top5_json.where(out.p_any_2q.notna(), None)
    out = pd.concat([out, cur[["stagnation_quarters", "elapsed_ratio"] + DISPLAY]], axis=1)

    path = GOLD / f"predictions_{mv}_{asof:%Y-%m}.parquet"
    out.to_parquet(path, index=False)
    pointer = {"path": path.relative_to(backtest.ROOT).as_posix(), "asof": str(asof.date()), "model_version": mv,
               "gold_version": man["gold_version"],
               "models": {c: champion(reg, y, h)["entry_id"] for c, (y, h) in PROBS.items()}}
    (GOLD / "predictions_latest.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
    log = append_log(out)

    print(f"scored {len(out)} current projects at {asof.date()} ({mv}); tier counts:")
    print(out.tier.fillna("no tier").value_counts().reindex(TIERS + ["no tier"]).to_string(),
          f"\n  stagnation overrides: {out.stagnation_override.sum()}, no completion date: {out.no_completion_date.sum()}")
    print("p_any_2q distribution:\n" + out.p_any_2q.describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())
    top = out.nlargest(10, "p_any_2q").assign(top_shap=lambda x: x.shap_top5_json.map(
        lambda s: json.loads(s)[0]["feature"] if s else None))
    print("top 10 by p_any_2q:\n" + top[["project_key", "project_name", "sector", "p_any_2q", "tier", "top_shap"]]
          .to_string(index=False, max_colwidth=50))
    print(f"score: {path.name}, prediction_log {len(log)} rows, {time.time() - t0:.1f}s")
    return out


if __name__ == "__main__":
    main()
