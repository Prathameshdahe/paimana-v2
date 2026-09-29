"""
Score the current portfolio (docs/IMPLEMENTATION_GUIDE_v2.md B 3.5).

Run from repo root after train:  python -m pipeline.run score

Inputs   gold/features.parquet, gold/labels_h{2,4}.parquet, gold/manifest.json, model/registry.json,
         silver/observations.parquet, silver/project_master.parquet
Outputs  gold/predictions_<model_version>_<asof YYYY-MM>.parquet, gold/predictions_latest.json,
         gold/prediction_log.parquet (appended, idempotent on project_key + asof + model_version)

At asof (default: the latest period) the current projects are those in the latest report with a feature row at asof
that are not completed. Each target's champion from the registry is refitted (its type, feature list and own params,
registry.fitter) on every label row realised by asof (t + h <= asof, from backtest.TRAIN_FROM where a target has
one) and scores them; a target in backtest.CALIBRATED goes through the Platt calibrator the champion's train run
stored (backtest.PLATT_FILE, fitted on the folds realised by that run's latest period). LightGBM quantile regressors
(5/50/95) trained on the same h=2 rows give the slip-months and cost-% intervals. The runway curve
(runway_any_1q .. runway_any_6q: P(first date push or cost revision by 3, 6, ..., 18 months) comes from one
discrete-time survival model (ml/survival.py) with the p_any_2q champion's features and params, next to the
per-horizon scores p_any_1q, p_any_2q, p_any_4q and p_any_6q; the tiers still rank p_any_2q. SHAP top-5 (log-odds
contributions) come from the p_any_2q model. Tiers go by rank of p_any_2q, not by threshold. The stagnation rule (no
progress for 2+ quarters, not at >= 95% progress) is only a flag, stagnation_override, shown as a badge: it used to
lift the tier, but flagged projects slipped at or below the base rate in the backtest and every lifted tier got less
precise. A score whose model never saw one of the row's null features in training is left null (see unseen_missing):
today that is the date-based scores of projects with no anticipated completion date (no_completion_date). Those
projects are in the Watch tier, outside the rank shares; the API orders them by flagged checklist rows, then
p_cost_rev_2q, an order no backtest has validated (their slip label needs a date).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest, registry  # noqa: E402

GOLD, SILVER, PK = backtest.GOLD, backtest.SILVER, backtest.PK
LOG = GOLD / "prediction_log.parquet"
PROBS = {"p_date_push_2q": ("y_date_push", 2), "p_cost_rev_2q": ("y_cost_rev", 2), "p_any_2q": ("y_any", 2),
         "p_any_4q": ("y_any", 4), "p_any_1q": ("y_any", 1), "p_any_6q": ("y_any", 6)}
RUNWAY = True               # the survival model's runway_any_1q..6q curve (ml/survival.py), next to the per-horizon scores
QUANTILES = {name: y for name, (y, _) in backtest.QUANTILE_TARGETS.items()}     # h = 2 regression targets
ALPHAS = backtest.ALPHAS
TIERS = ["Critical", "High", "Medium", "Low"]
WATCH = "Watch"             # the tier of a project with no anticipated completion date (no date-based score)
TIER_TOP = [0.05, 0.20, 0.50, 1.0]      # cumulative rank share at the bottom of each tier
STAGNANT_Q, STAGNANT_ELAPSED = 2, 0.3
NEAR_DONE_PCT = 95          # a project this far along is finishing, not stagnating: no override
SHAP_K = 5
SHORT = {"lightgbm": "lgbm", "logreg": "logreg"}
LOG_KEY = ["project_key", "asof", "model_version"]
LOG_COLS = LOG_KEY + ["p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "tier"]
REALISED = {"y_any_2q": "Int8", "y_date_push_2q": "Int8", "y_cost_rev_2q": "Int8", "realised_period": "datetime64[us]"}
DISPLAY = ["project_name", "sector", "state", "agency", "ministry", "anticipated_cost_cr", "expenditure_cr",
           "physical_progress_pct", "anticipated_completion"]


def tiers(p, stagnant, no_date=None):
    """Rank tiers of scores p (1 = riskiest; ties broken by position). A null score is not counted in the rank shares:
    with no completion date (no_date) its tier is WATCH, otherwise it has none. stagnation_override is the stagnation
    rule's flag as given; it does not change the tier. Returns tier_rank_pct, tier_by_rank, tier,
    stagnation_override."""
    p = pd.Series(np.asarray(p, float))
    scored = p.notna().to_numpy()
    rank_pct = p.rank(method="first", ascending=False).to_numpy() / max(scored.sum(), 1)
    names = np.array(TIERS, dtype=object)[np.searchsorted(TIER_TOP, np.nan_to_num(rank_pct), side="left")]
    by_rank = np.where(scored, names, None)
    watch = ~scored & (np.zeros(len(p), bool) if no_date is None else np.asarray(no_date, bool))
    return pd.DataFrame({"tier_rank_pct": rank_pct, "tier_by_rank": by_rank, "tier": np.where(watch, WATCH, by_rank),
                         "stagnation_override": np.asarray(stagnant, bool)})


def stagnant(cur):
    """Stagnation override rule: no progress for STAGNANT_Q+ quarters at >= STAGNANT_ELAPSED elapsed, and progress
    below NEAR_DONE_PCT (null progress does not block it)."""
    return ((cur.stagnation_quarters >= STAGNANT_Q) & (cur.elapsed_ratio >= STAGNANT_ELAPSED)
            & ~(cur.physical_progress_pct >= NEAR_DONE_PCT)).to_numpy()


def unseen_missing(train, X, cols):
    """Rows of X with a null in a feature that is never null in train. LightGBM keeps no missing branch for such a
    feature and reads the null as 0 (months_to_anticipated_completion = 0: deadline this month), and imputing it is
    no better, so these rows are not scored."""
    never = [c for c in cols if train[c].notna().all()]
    return X[never].isna().any(axis=1).to_numpy()


def champion(reg, y, h):
    return next(r for r in reg["runs"] if r["entry_id"] == reg["champions"][f"{y}_h{h}"]["entry_id"])


def model_version(reg):
    """The served model version: the p_any_2q champion's type and run, then "+run" for each other run a champion of
    PROBS comes from (targets are promoted one by one, and the briefs and the prediction log key on this string)."""
    lead = champion(reg, "y_any", 2)
    runs = sorted({champion(reg, y, h)["run_id"] for y, h in PROBS.values()} - {lead["run_id"]})
    return (f"{SHORT[registry.family(lead['model'])]}-any2q-{lead['run_id'].removeprefix('ML-')}"
            + "".join(f"+{r.removeprefix('ML-')}" for r in runs))


def calibrator(entry):
    """The Platt parameters of entry's model and target from its run folder, or None (raw scores)."""
    path = backtest.RUNS / entry["run_id"] / backtest.PLATT_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get(f"{entry['target']}_h{entry['horizon']}", {}).get(
        entry["model"])


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
    mv = model_version(reg)
    out = cur[["project_key"]].assign(asof=asof, model_version=mv, gold_version=man["gold_version"],
                                      silver_version=man["silver_version"])
    fitted = {}
    for col, (y, h) in PROBS.items():
        e = champion(reg, y, h)
        d = backtest.frame(feats, labels[h], y, h)
        d = d[d.target_period <= asof]
        fitted[col], predict = registry.fitter(e)(d, e["feature_list"], e["categorical"], y)
        skip = unseen_missing(d, cur, e["feature_list"])
        cal = calibrator(e) if (y, h) in backtest.CALIBRATED else None
        out[col] = np.where(skip, np.nan, backtest.platt_apply(cal, predict(cur)))
        print(f"  {col}: {e['model']} ({e['entry_id']}) refit on {len(d)} rows, {skip.sum()} rows not scored, "
              f"calibration {'Platt a=%.3f b=%.3f' % (cal['a'], cal['b']) if cal and 'a' in cal else 'none'}")

    cols, cats = lead["feature_list"], lead["categorical"]
    Xc = backtest.lgb_X(cur, cols, cats)
    for name, y in QUANTILES.items():
        d = backtest.qframe(feats, labels[2][labels[2].target_period <= asof], y)
        q = backtest.fit_quantiles(d, y, cols, cats)(cur)      # sorted, so p05 <= p50 <= p95
        q[unseen_missing(d, cur, cols)] = np.nan
        for i, s in enumerate(ALPHAS):
            out[f"{name}_{s}"] = q[:, i]
        print(f"  {name}: quantile LightGBM on {len(d)} rows")

    if RUNWAY:
        from ml import survival
        rw, n_pp = survival.runway(feats, asof, cur, cols, cats, lead.get("params") or backtest.lgb_params("y_any", 2),
                                   skip=unseen_missing)
        out = pd.concat([out, rw], axis=1)
        print(f"  runway: hazard LightGBM on {n_pp} person-periods, {rw.isna().any(axis=1).sum()} rows not scored")

    out["no_completion_date"] = cur.months_to_anticipated_completion.isna()
    out = pd.concat([out, tiers(out.p_any_2q, stagnant(cur), out.no_completion_date)], axis=1)
    m = fitted["p_any_2q"]
    # ponytail: SHAP only for a LightGBM champion; a logistic champion leaves the column null
    out["shap_top5_json"] = shap_top5(m.booster_, Xc) if registry.family(lead["model"]) == "lightgbm" else None
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
    print(out.tier.fillna("no tier").value_counts().reindex(TIERS + [WATCH, "no tier"]).to_string(),
          f"\n  stagnation flags: {out.stagnation_override.sum()}, no completion date: {out.no_completion_date.sum()}")
    print("p_any_2q distribution:\n" + out.p_any_2q.describe(percentiles=[.05, .25, .5, .75, .95]).round(3).to_string())
    top = out.nlargest(10, "p_any_2q").assign(top_shap=lambda x: x.shap_top5_json.map(
        lambda s: json.loads(s)[0]["feature"] if s else None))
    print("top 10 by p_any_2q:\n" + top[["project_key", "project_name", "sector", "p_any_2q", "tier", "top_shap"]]
          .to_string(index=False, max_colwidth=50))
    print(f"score: {path.name}, prediction_log {len(log)} rows, {time.time() - t0:.1f}s")
    return out


if __name__ == "__main__":
    main()
