"""
File model registry (docs/IMPLEMENTATION_GUIDE_v2.md A.2 and B 3.4): model/registry.json + model/runs/<run_id>/.

Run from repo root after the gold build:  python -m pipeline.run train

One train run backtests every target (ml/backtest.py), refits logistic regression and LightGBM on every realised
label, saves them into the run folder and registers one entry per (model, target, horizon). Promotion: a challenger
replaces the champion of its (target, horizon) only when both were scored on the same validation folds of the same
gold version, its pooled PR-AUC is higher and its ECE is at most the champion's + ECE_SLACK. When the folds differ,
only a fresh entry of the champion's own model type may take over (the same model re-scored on the new folds).
Every decision and its reason is recorded in registry.json.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest  # noqa: E402

REGISTRY = backtest.ROOT / "model" / "registry.json"
ECE_SLACK = 0.02
CANDIDATES = {"logreg": backtest.fit_logreg, "lightgbm": backtest.fit_lgbm}   # logistic is the first-run incumbent


def load(path=REGISTRY):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"runs": [], "champions": {}, "decisions": []}


def jsonable(o):
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, pd.Timestamp):
        return o.date().isoformat()
    if isinstance(o, (np.integer, np.floating)):
        o = o.item()
    if isinstance(o, float) and np.isnan(o):
        return None
    return o


def fold_ids(entry):
    return [f["cutoff"] for f in entry["metrics"]["folds"]]


def promote(reg, entry):
    """Apply the champion/challenger rule to one new entry; record and return the decision."""
    key = f"{entry['target']}_h{entry['horizon']}"
    cur_id = reg["champions"].get(key, {}).get("entry_id")
    cur = next((r for r in reg["runs"] if r["entry_id"] == cur_id), None)
    new = entry["metrics"]["pooled"]
    if cur is None:
        ok, why = True, "no champion yet"
    elif fold_ids(cur) != fold_ids(entry) or cur["gold_version"] != entry["gold_version"]:
        ok = cur["model"] == entry["model"]
        why = ("folds or gold_version differ; same model type re-scored on the new folds" if ok else
               "folds or gold_version differ from the champion's; not comparable, champion kept")
    else:
        old = cur["metrics"]["pooled"]
        better, calibrated = new["pr_auc"] > old["pr_auc"], new["ece"] <= old["ece"] + ECE_SLACK
        ok = better and calibrated
        why = (f"pooled PR-AUC {new['pr_auc']:.4f} vs champion {old['pr_auc']:.4f} "
               f"({'higher' if better else 'not higher'}); ECE {new['ece']:.4f} vs {old['ece']:.4f} + {ECE_SLACK} "
               f"({'ok' if calibrated else 'too high'})")
    decision = {"at": entry["created_at"], "target": entry["target"], "horizon": entry["horizon"],
                "challenger": entry["entry_id"], "champion_before": cur_id,
                "decision": "promoted" if ok else "rejected", "reason": why}
    reg["decisions"].append(decision)
    if ok:
        reg["champions"][key] = {"entry_id": entry["entry_id"], "run_id": entry["run_id"], "model": entry["model"],
                                 "since": entry["created_at"]}
    return decision


def main():
    t0 = time.time()
    run_id, res = backtest.main()
    run_dir = backtest.RUNS / run_id
    man, cols, cats = res["manifest"], res["features"], res["categorical"]
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params = {"lightgbm": backtest.LGB_PARAMS, "logreg": {**backtest.LOGREG_PARAMS, "onehot_min_frequency":
              backtest.ONEHOT_MIN, "numeric": "median impute + missing flags + standardise"},
              "windows": {"reliable_min": backtest.RELIABLE, "n_val": backtest.N_VAL, "n_test": backtest.N_TEST,
                          "min_rows": backtest.MIN_ROWS},
              "final_fit": "all label rows (every realised outcome), completed projects excluded",
              "targets": [f"{y}_h{h}" for y, h in backtest.TARGETS], "features": cols, "categorical": cats,
              "feature_groups": res["groups"], "gold_version": man["gold_version"],
              "silver_version": man["silver_version"], "ece_slack": ECE_SLACK}
    (run_dir / "params.json").write_text(json.dumps(jsonable(params), indent=2), encoding="utf-8")
    shared = {f: f"model/runs/{run_id}/{f}" for f in ["backtest_folds.csv", "backtest_summary.csv", "ablation.csv",
                                                      "calibration.csv", "shap_summary.csv", "windows.json",
                                                      "params.json"]}
    reg = load()
    for (y, h), d in res["frames"].items():
        key = f"{y}_h{h}"
        champ = reg["champions"].get(key, {}).get("model")
        for name in sorted(CANDIDATES, key=lambda n: n != champ):    # the champion's own type goes first
            m, _ = CANDIDATES[name](d, cols, cats, y)
            if name == "lightgbm":
                model_file = f"lightgbm_{key}.txt"
                m.booster_.save_model(run_dir / model_file)
            else:
                model_file = f"logreg_{key}.joblib"
                joblib.dump(m, run_dir / model_file)
            entry = {"entry_id": f"{run_id}/{name}/{key}", "run_id": run_id, "model": name, "target": y,
                     "horizon": h, "gold_version": man["gold_version"], "silver_version": man["silver_version"],
                     "params": params[name], "feature_list": cols, "categorical": cats,
                     "metrics": {"pooled": res["metrics"][key, "val", name]["pooled"],
                                 "folds": res["metrics"][key, "val", name]["folds"],
                                 "test": res["metrics"][key, "test", name]["pooled"]},
                     "windows": {k: res["windows"][key][k] for k in ["validation", "test"]},
                     "artifacts": {"model": f"model/runs/{run_id}/{model_file}", **shared},
                     "n_final_fit": len(d), "created_at": created}
            entry = jsonable(entry)
            reg["runs"].append(entry)
            dec = promote(reg, entry)
            print(f"  {key} {name}: {dec['decision']} ({dec['reason']})")
    REGISTRY.write_text(json.dumps(jsonable(reg), indent=2), encoding="utf-8")
    print(f"train {run_id}: {time.time() - t0:.0f}s, registry {REGISTRY}")
