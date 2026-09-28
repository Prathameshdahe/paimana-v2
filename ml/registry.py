"""
File model registry (docs/IMPLEMENTATION_GUIDE_v2.md A.2 and B 3.4): model/registry.json + model/runs/<run_id>/.

Run from repo root after the gold build:  python -m pipeline.run train

One train run backtests every target (ml/backtest.py), refits logistic regression and LightGBM on every realised
label, saves them into the run folder and registers one entry per (model, target, horizon). Promotion: a challenger
replaces the champion of its (target, horizon) only when both were scored on the same validation and flash folds of
the same gold version, its within-cutoff PR-AUC (GAIN, the mean of each fold's own PR-AUC) is not lower on either
block (validation, flash) and higher on at least one by NOISE_SDS seed standard deviations, and its validation ECE is
at most the champion's + ECE_SLACK (rule). The gain is within-cutoff because a served score is only ever ranked
against the other projects of the same as-of date: pooled PR-AUC over several folds also rewards a model whose score
level follows each fold's base rate, which is calibration, not ranking (ECE guards that).

A new gold version (new data, new or changed features) makes the champion's metrics incomparable. The run then also
backtests the champion's own configuration (model type, feature list, categoricals, params: config) on the new gold
and folds as the incumbent, named <type>_incumbent, unless a candidate of the run already has that configuration.
The re-scored champion configuration takes over first (the same model on the new folds; nothing else may take over
across gold versions or folds), and every new configuration then has to beat it under the rule. A champion whose
features are no longer in the gold is retired and the run starts from no champion. Every decision and its reason is
recorded in registry.json. Scoring refits each champion with its entry's own params (fitter).
"""
import functools
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
GAIN = "pr_auc_fold_mean"      # the promotion metric: each fold's PR-AUC, averaged over the block's folds
# sd of pooled validation PR-AUC over 5 LightGBM seeds of the unchanged champion (research audit 2026-09-27 on
# ML-20260927-174106's features and folds; seed 0 was the luckiest of the 5). A single-seed gain inside NOISE_SDS of
# these is noise. Re-measure when the features or folds change a lot. (Measured on pooled PR-AUC; they set the GAIN
# margin until the within-cutoff metric's own are measured.)
SEED_SD = {"y_any_h2": 0.0038, "y_date_push_h2": 0.0025, "y_cost_rev_h2": 0.0022, "y_any_h4": 0.0011}
NOISE_SDS = 2
BLOCKS = {"val": ("pooled", "folds"), "flash": ("flash", "flash_folds")}    # block -> (pooled key, folds key)
CANDIDATES = {"logreg": backtest.fit_logreg, "lightgbm": backtest.fit_lgbm}   # logistic is the first-run incumbent
INCUMBENT = "_incumbent"    # model-name suffix of the champion configuration re-scored in a run


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


def family(model):
    """Model type of a model name: lightgbm_incumbent is a lightgbm."""
    return model.removesuffix(INCUMBENT)


def fitter(entry):
    """The backtest fit function of a registry entry: its model type, a LightGBM with the entry's own params."""
    fam = family(entry["model"])
    if fam == "lightgbm" and entry.get("params"):
        return functools.partial(backtest.fit_lgbm, params=entry["params"])
    return CANDIDATES[fam]


def config(entry):
    """What a model is apart from its data: type, feature list, categoricals and params."""
    return family(entry["model"]), entry.get("feature_list"), entry.get("categorical"), jsonable(entry.get("params"))


def fold_ids(entry):
    return {b: [f["cutoff"] for f in entry["metrics"].get(folds) or []] for b, (_, folds) in BLOCKS.items()}


def pr_auc_gains(new, old):
    """block -> challenger minus champion within-cutoff PR-AUC (GAIN), for the blocks both have a value on."""
    get = lambda e, k: (e["metrics"].get(k) or {}).get(GAIN)
    return {b: get(new, k) - get(old, k) for b, (k, _) in BLOCKS.items()
            if get(new, k) is not None and get(old, k) is not None}


def rule(gains, margin, ece_new, ece_old):
    """The promotion rule on block -> within-cutoff PR-AUC gain: not lower on any block, at least margin on one, and
    validation ECE at most ece_old + ECE_SLACK. Returns (ok, reason). Shared with the experiment harness
    (ml/experiment.py)."""
    not_worse = all(g >= 0 for g in gains.values())
    better = any(g >= margin for g in gains.values())
    calibrated = ece_new <= ece_old + ECE_SLACK
    why = ("within-cutoff PR-AUC gain " + ", ".join(f"{b} {g:+.4f}" for b, g in gains.items())
           + f" ({'not lower on any block' if not_worse else 'lower on a block'}, "
           f"{'clears' if better else 'no block clears'} the noise margin {margin:.4f}); "
           f"ECE {ece_new:.4f} vs {ece_old:.4f} + {ECE_SLACK} ({'ok' if calibrated else 'too high'})")
    return not_worse and better and calibrated, why


def promote(reg, entry):
    """Apply the champion/challenger rule to one new entry; record and return the decision."""
    key = f"{entry['target']}_h{entry['horizon']}"
    cur_id = reg["champions"].get(key, {}).get("entry_id")
    cur = next((r for r in reg["runs"] if r["entry_id"] == cur_id), None)
    new = entry["metrics"]["pooled"]
    if cur is None:
        ok, why = True, "no champion yet"
    elif fold_ids(cur) != fold_ids(entry) or cur["gold_version"] != entry["gold_version"]:
        ok = config(cur) == config(entry)
        why = ("folds or gold_version differ; the champion's configuration re-scored on the new folds" if ok else
               "folds or gold_version differ from the champion's and so does the configuration; not comparable, "
               "champion kept")
    else:
        old = cur["metrics"]["pooled"]
        ok, why = rule(pr_auc_gains(entry, cur), NOISE_SDS * SEED_SD.get(key, 0.0), new["ece"], old["ece"])
        why = (f"validation PR-AUC fold mean {new[GAIN]:.4f} vs champion {old[GAIN]:.4f} (pooled {new['pr_auc']:.4f} "
               f"vs {old['pr_auc']:.4f}); " + why)
    decision = {"at": entry["created_at"], "target": entry["target"], "horizon": entry["horizon"],
                "challenger": entry["entry_id"], "champion_before": cur_id,
                "decision": "promoted" if ok else "rejected", "reason": why}
    reg["decisions"].append(decision)
    if ok:
        reg["champions"][key] = {"entry_id": entry["entry_id"], "run_id": entry["run_id"], "model": entry["model"],
                                 "since": entry["created_at"]}
    return decision


def incumbents(reg, man, configs):
    """target key -> the champion entry to re-score in this run: it was scored on another gold version and no
    candidate of the run (configs: target key -> {name: config tuple}) has its configuration. A champion with a
    feature that the gold no longer has cannot be re-scored: it is retired (a recorded decision) and the target has
    no champion."""
    have = {f for fs in man["features"].values() for f in fs}
    out = {}
    for y, h in backtest.TARGETS:
        key = f"{y}_h{h}"
        cur_id = reg["champions"].get(key, {}).get("entry_id")
        cur = next((r for r in reg["runs"] if r["entry_id"] == cur_id), None)
        if cur is None or cur["gold_version"] == man["gold_version"] or config(cur) in configs[key].values():
            continue
        missing = sorted(set(cur.get("feature_list") or []) - have)
        if missing:
            reg["champions"].pop(key)
            reg["decisions"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "target": y,
                                     "horizon": h, "challenger": None, "champion_before": cur_id,
                                     "decision": "retired", "reason": f"features no longer in gold: {missing}"})
            continue
        out[key] = cur
    return out


def register(reg, run_id, res, params, inc, created):
    """Final fit, model file, entry and promotion decision for every (target, candidate), the re-scored incumbent
    first where there is one. params: target key -> model name -> params; inc: incumbents(). Returns the
    decisions."""
    run_dir = backtest.RUNS / run_id
    man, cols, cats = res["manifest"], res["features"], res["categorical"]
    shared = {f: f"model/runs/{run_id}/{f}" for f in ["backtest_folds.csv", "backtest_summary.csv", "ablation.csv",
                                                      "calibration.csv", "shap_summary.csv", "windows.json",
                                                      "params.json", backtest.PLATT_FILE, "intervals.csv"]}
    out = []
    for (y, h), d in res["frames"].items():
        key = f"{y}_h{h}"
        champ = family(reg["champions"].get(key, {}).get("model", ""))
        spec = {name: {"model": name, "feature_list": cols, "categorical": cats, "params": params[key][name]}
                for name in sorted(CANDIDATES, key=lambda n: n != champ)}     # the champion's own type goes first
        if key in inc:
            cur, name = inc[key], family(inc[key]["model"]) + INCUMBENT
            spec = {name: {"model": name, "feature_list": cur["feature_list"], "categorical": cur["categorical"],
                           "params": cur["params"], "rescored_from": cur["entry_id"]}, **spec}
        for name, e in spec.items():
            m, _ = fitter(e)(d, e["feature_list"], e["categorical"], y)
            if family(name) == "lightgbm":
                model_file = f"{name}_{key}.txt"
                m.booster_.save_model(run_dir / model_file)
            else:
                model_file = f"{name}_{key}.joblib"
                joblib.dump(m, run_dir / model_file)
            flash = res["metrics"].get((key, "flash", name), {})
            entry = {"entry_id": f"{run_id}/{name}/{key}", "run_id": run_id, "target": y, "horizon": h,
                     "gold_version": man["gold_version"], "silver_version": man["silver_version"], **e,
                     "metrics": {"pooled": res["metrics"][key, "val", name]["pooled"],
                                 "folds": res["metrics"][key, "val", name]["folds"],
                                 "test": res["metrics"][key, "test", name]["pooled"],
                                 "flash": flash.get("pooled"), "flash_folds": flash.get("folds", [])},
                     "windows": {k: res["windows"][key][k] for k in ["validation", "test", "flash"]},
                     "artifacts": {"model": f"model/runs/{run_id}/{model_file}", **shared},
                     "n_final_fit": len(d), "created_at": created}
            entry = jsonable(entry)
            reg["runs"].append(entry)
            dec = promote(reg, entry)
            out.append(dec)
            print(f"  {key} {name}: {dec['decision']} ({dec['reason']})")
    return out


def main():
    t0 = time.time()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    man = json.loads((backtest.GOLD / "manifest.json").read_text(encoding="utf-8"))
    cols, cats = backtest.model_cols(man["features"]), man["categorical"]
    logreg = {**backtest.LOGREG_PARAMS, "onehot_min_frequency": backtest.ONEHOT_MIN,
              "numeric": "median impute + missing flags + standardise"}
    params = {f"{y}_h{h}": {"lightgbm": backtest.lgb_params(y, h), "logreg": logreg} for y, h in backtest.TARGETS}
    reg = load()
    inc = incumbents(reg, man, {k: {n: config({"model": n, "feature_list": cols, "categorical": cats, "params": p})
                                    for n, p in ps.items()} for k, ps in params.items()})
    run_id, res = backtest.main(extra={k: {family(e["model"]) + INCUMBENT: (fitter(e), e["feature_list"],
                                                                            e["categorical"])}
                                       for k, e in inc.items()})
    assert res["features"] == cols and res["manifest"]["gold_version"] == man["gold_version"]
    info = {"lightgbm": backtest.LGB_PARAMS, "logreg": logreg,
            "target_params": {f"{y}_h{h}": p for (y, h), p in backtest.TARGET_PARAMS.items()},
            "windows": {"reliable_min": backtest.RELIABLE, "n_val": backtest.N_VAL, "n_test": backtest.N_TEST,
                        "min_rows": backtest.MIN_ROWS},
            "final_fit": "all label rows (every realised outcome), completed projects excluded, rows before "
                         "train_from dropped",
            "train_from": {f"{y}_h{h}": t for (y, h), t in backtest.TRAIN_FROM.items()},
            "calibration": {"method": f"platt_k{backtest.PLATT_FOLDS}", "file": backtest.PLATT_FILE,
                            "targets": sorted(f"{y}_h{h}" for y, h in backtest.CALIBRATED),
                            "rule": "each cutoff c: Platt on the model's predictions at c - h .. c - h - "
                                    f"{backtest.PLATT_FOLDS - 1} quarters (labels realised by c); the served "
                                    "calibrator uses the folds realised by the latest period"},
            "targets": [f"{y}_h{h}" for y, h in backtest.TARGETS], "features": cols, "categorical": cats,
            "feature_groups": res["groups"], "gold_version": man["gold_version"],
            "silver_version": man["silver_version"], "ece_slack": ECE_SLACK,
            "promotion": {"gain": GAIN, "seed_sd": SEED_SD, "noise_sds": NOISE_SDS, "flash_from": backtest.FLASH_FROM},
            "incumbents": {k: {"rescored_from": e["entry_id"], "model": family(e["model"]) + INCUMBENT,
                               "n_features": len(e["feature_list"]), "params": e["params"]} for k, e in inc.items()}}
    (backtest.RUNS / run_id / "params.json").write_text(json.dumps(jsonable(info), indent=2), encoding="utf-8")
    register(reg, run_id, res, params, inc, created)
    REGISTRY.write_text(json.dumps(jsonable(reg), indent=2), encoding="utf-8")
    print(f"train {run_id}: {time.time() - t0:.0f}s, registry {REGISTRY}")
