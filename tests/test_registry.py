import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import backtest, registry  # noqa: E402


def entry(model, pr_auc, ece, folds=("2024-01-01", "2024-04-01"), gold="g1", run="R1", flash=None, features=None,
          cats=None, params=None, pooled=None):
    """pr_auc and flash are the within-cutoff PR-AUCs the rule compares (registry.GAIN); pooled PR-AUC is pr_auc
    unless given."""
    m = {"pooled": {registry.GAIN: pr_auc, "pr_auc": pr_auc if pooled is None else pooled, "ece": ece},
         "folds": [{"cutoff": c} for c in folds]}
    if flash is not None:
        m.update(flash={registry.GAIN: flash, "pr_auc": flash, "ece": ece}, flash_folds=[{"cutoff": "2025-07-01"}])
    return {"entry_id": f"{run}/{model}/y_any_h2", "run_id": run, "model": model, "target": "y_any", "horizon": 2,
            "gold_version": gold, "created_at": run, "metrics": m, "feature_list": features, "categorical": cats,
            "params": params}


def add(reg, e):
    reg["runs"].append(e)
    return registry.promote(reg, e)["decision"]


def test_promotion_rule():
    reg = {"runs": [], "champions": {}, "decisions": []}
    assert add(reg, entry("logreg", 0.50, 0.05)) == "promoted"                 # no champion yet
    assert add(reg, entry("lightgbm", 0.60, 0.08)) == "rejected"               # better PR-AUC, ECE > +0.02
    assert add(reg, entry("lightgbm", 0.50, 0.05, run="R2")) == "rejected"     # PR-AUC must be strictly higher
    assert add(reg, entry("lightgbm", 0.60, 0.07, run="R3")) == "promoted"     # ECE within +0.02
    assert reg["champions"]["y_any_h2"]["entry_id"] == "R3/lightgbm/y_any_h2"
    other = entry("logreg", 0.90, 0.01, folds=("2024-04-01",), run="R4")
    assert add(reg, other) == "rejected"                                       # different folds: not comparable
    assert add(reg, entry("lightgbm", 0.40, 0.10, gold="g2", run="R5")) == "promoted"   # champion type re-scored
    assert len(reg["decisions"]) == 6 and all(d["reason"] for d in reg["decisions"])


def test_promotion_needs_both_blocks_and_a_noise_margin():
    margin, flash_margin = registry.margins("y_any_h2")["val"], registry.margins("y_any_h2")["flash"]
    reg = {"runs": [], "champions": {}, "decisions": []}
    assert add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75)) == "promoted"
    assert add(reg, entry("logreg", 0.70 + margin / 2, 0.05, flash=0.75, run="R2")) == "rejected"   # inside noise
    assert add(reg, entry("logreg", 0.75, 0.05, flash=0.749, run="R3")) == "rejected"   # worse on the flash block
    assert add(reg, entry("logreg", 0.70, 0.05, flash=0.75 + flash_margin * 0.9, run="R4x")) == "rejected"
    assert add(reg, entry("logreg", 0.70, 0.05, flash=0.75 + flash_margin + 1e-9, run="R4")) == "promoted"  # flash
    assert reg["champions"]["y_any_h2"]["entry_id"] == "R4/logreg/y_any_h2"
    assert "flash -0.0010" in reg["decisions"][2]["reason"]
    assert f"flash +{flash_margin:.4f} (margin {flash_margin:.4f})" in reg["decisions"][-1]["reason"]
    assert "a block clears" in reg["decisions"][-1]["reason"]
    # a champion scored without the flash block has other folds: only its own model type may take over
    assert add(reg, entry("lightgbm", 0.99, 0.01, run="R5")) == "rejected"


def test_promotion_compares_within_cutoff_pr_auc_not_pooled():
    """A challenger with a higher pooled PR-AUC but a lower fold mean (it follows each fold's base rate, it does not
    rank better inside a fold) is rejected; the reverse is promoted."""
    reg = {"runs": [], "champions": {}, "decisions": []}
    assert add(reg, entry("lightgbm", 0.88, 0.05, flash=0.87, pooled=0.869)) == "promoted"
    assert add(reg, entry("lightgbm", 0.876, 0.05, flash=0.87, pooled=0.881, run="R2")) == "rejected"
    assert "within-cutoff PR-AUC gain val -0.0040" in reg["decisions"][-1]["reason"]
    assert add(reg, entry("lightgbm", 0.90, 0.05, flash=0.87, pooled=0.860, run="R3")) == "promoted"


P = {**backtest.LGB_PARAMS, "n_estimators": 5, "n_jobs": 1}


def test_a_new_gold_version_needs_the_champion_configuration_rescored():
    reg = {"runs": [], "champions": {}, "decisions": []}
    assert add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75, features=["a", "b"], cats=[], params=P)) == "promoted"
    more = dict(features=["a", "b", "c"], cats=[], params=P, gold="g2", flash=0.80)
    assert add(reg, entry("lightgbm", 0.90, 0.05, run="R2", **more)) == "rejected"      # new features, new gold
    assert "not comparable" in reg["decisions"][-1]["reason"]
    tuned = entry("lightgbm", 0.90, 0.05, run="R3", flash=0.8, features=["a", "b"], cats=[], params={**P, "x": 1},
                  gold="g2")
    assert add(reg, tuned) == "rejected"                                                  # other params, new gold
    old = dict(features=["a", "b"], cats=[], params=P, gold="g2", flash=0.70)
    assert add(reg, entry("lightgbm_incumbent", 0.60, 0.05, run="R4", **old)) == "promoted"   # re-scored champion
    assert "re-scored" in reg["decisions"][-1]["reason"]
    margin = registry.margins("y_any_h2")["val"]
    assert add(reg, entry("lightgbm", 0.60 + margin / 2, 0.05, run="R5", **{**more, "flash": 0.70})) == "rejected"
    assert add(reg, entry("lightgbm", 0.60 + margin + 1e-9, 0.05, run="R6", **{**more, "flash": 0.70})) == "promoted"


def test_incumbents_only_for_a_champion_of_another_gold_and_configuration():
    champ = entry("lightgbm", 0.70, 0.05, flash=0.75, features=["a", "b"], cats=[], params=P)
    reg = {"runs": [champ], "champions": {"y_any_h2": {"entry_id": champ["entry_id"], "model": "lightgbm"}},
           "decisions": []}
    man = {"gold_version": "g2", "features": {"state": ["a", "b", "c"]}}
    keys = [f"{y}_h{h}" for y, h in backtest.TARGETS]
    new = {k: {"lightgbm": registry.config({"model": "lightgbm", "feature_list": ["a", "b", "c"], "categorical": [],
                                             "params": P})} for k in keys}
    assert list(registry.incumbents(reg, man, new)) == ["y_any_h2"]
    same = {k: {"lightgbm": registry.config(champ)} for k in keys}
    assert registry.incumbents(reg, man, same) == {}                                      # same configuration
    assert registry.incumbents(reg, {**man, "gold_version": "g1"}, new) == {}             # same gold
    same_folds = {k: {"val": ["2024-01-01", "2024-04-01"], "flash": ["2025-07-01"]} for k in keys}
    assert registry.incumbents(reg, {**man, "gold_version": "g1"}, new, same_folds) == {}
    moved = {**same_folds, "y_any_h2": {"val": ["2023-10-01", "2024-01-01"], "flash": ["2025-07-01"]}}
    assert list(registry.incumbents(reg, {**man, "gold_version": "g1"}, new, moved)) == ["y_any_h2"]   # new folds
    assert registry.incumbents(reg, {**man, "gold_version": "g1"}, same, moved) == {}    # a candidate has its config
    assert registry.incumbents(reg, {**man, "features": {"state": ["a", "c"]}}, new) == {}
    assert "y_any_h2" not in reg["champions"] and reg["decisions"][-1]["decision"] == "retired"


def test_fitter_uses_the_entry_params():
    rng = np.random.default_rng(0)
    d = pd.DataFrame({"a": rng.normal(size=200)})
    d["y"] = (d.a + rng.normal(size=200) > 0).astype(int)
    m, _ = registry.fitter({"model": "lightgbm_incumbent", "params": {**P, "n_estimators": 3}})(d, ["a"], [], "y")
    assert m.booster_.num_trees() == 3 and registry.family("lightgbm_incumbent") == "lightgbm"
    assert registry.fitter({"model": "logreg", "params": {"C": 1.0}}) is backtest.fit_logreg


def test_register_scores_the_incumbent_first_and_gates_the_new_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest, "RUNS", tmp_path)
    (tmp_path / "R2").mkdir()
    rng = np.random.default_rng(1)
    d = pd.DataFrame(rng.normal(size=(300, 3)), columns=["a", "b", "c"])
    d["y_any"] = (d.a + rng.normal(size=300) > 0).astype(int)
    reg = {"runs": [], "champions": {}, "decisions": []}
    add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75, features=["a", "b"], cats=[], params=P))
    folds = [{"cutoff": c} for c in ("2024-01-01", "2024-04-01")]
    margin = min(registry.margins("y_any_h2").values())
    metrics = {}
    for name, v in {"lightgbm_incumbent": 0.60, "lightgbm": 0.60 + margin / 2, "logreg": 0.50}.items():
        metrics["y_any_h2", "val", name] = {"pooled": {"pr_auc": v, registry.GAIN: v, "ece": 0.05}, "folds": folds}
        metrics["y_any_h2", "test", name] = {"pooled": {"pr_auc": v}}
        metrics["y_any_h2", "flash", name] = {"pooled": {"pr_auc": v, registry.GAIN: v, "ece": 0.05},
                                              "folds": [{"cutoff": "2025-07-01"}]}
    man = {"gold_version": "g2", "silver_version": "s1", "features": {"state": ["a", "b", "c"]}}
    res = {"frames": {("y_any", 2): d}, "manifest": man, "features": ["a", "b", "c"], "categorical": [],
           "metrics": metrics, "windows": {"y_any_h2": {"validation": [], "test": [], "flash": []}}}
    params = {"lightgbm": P, "logreg": {}}
    configs = {n: registry.config({"model": n, "feature_list": ["a", "b", "c"], "categorical": [], "params": p})
               for n, p in params.items()}
    inc = registry.incumbents(reg, man, {f"{y}_h{h}": configs for y, h in backtest.TARGETS})
    decs = registry.register(reg, "R2", res, {"y_any_h2": params}, inc, "now")
    assert [(x["challenger"], x["decision"]) for x in decs] == [
        ("R2/lightgbm_incumbent/y_any_h2", "promoted"), ("R2/lightgbm/y_any_h2", "rejected"),
        ("R2/logreg/y_any_h2", "rejected")]
    champ = reg["champions"]["y_any_h2"]
    assert champ["entry_id"] == "R2/lightgbm_incumbent/y_any_h2" and champ["model"] == "lightgbm_incumbent"
    e = next(r for r in reg["runs"] if r["entry_id"] == champ["entry_id"])
    assert e["feature_list"] == ["a", "b"] and e["rescored_from"] == "R1/lightgbm/y_any_h2"
    assert (tmp_path / "R2" / "lightgbm_incumbent_y_any_h2.txt").exists()


def test_revert_restores_the_champion_a_promotion_replaced():
    reg = {"runs": [], "champions": {}, "decisions": []}
    add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75))
    add(reg, entry("lightgbm", 0.80, 0.05, flash=0.80, run="R2", params={"num_leaves": 63}))
    assert reg["champions"]["y_any_h2"]["entry_id"] == "R2/lightgbm/y_any_h2"
    d = registry.revert(reg, "y_any_h2", "fails the corrected rule", at="now")
    assert reg["champions"]["y_any_h2"] == {"entry_id": "R1/lightgbm/y_any_h2", "run_id": "R1", "model": "lightgbm",
                                            "since": "now"}
    assert d["decision"] == "reverted" and d["champion_before"] == "R2/lightgbm/y_any_h2"
    assert d["challenger"] == "R1/lightgbm/y_any_h2" and "fails the corrected rule" in d["reason"]
    assert add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75, run="R3")) == "rejected"    # the gate goes on from R1
    try:
        registry.revert(reg, "y_any_h2", "again")                  # R1 replaced no champion: nothing to go back to
        raise RuntimeError("revert should refuse")
    except AssertionError as e:
        assert "nothing to revert to" in str(e)


def test_revert_cli_writes_the_registry(tmp_path, monkeypatch):
    reg = {"runs": [], "champions": {}, "decisions": []}
    add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75))
    add(reg, entry("lightgbm", 0.80, 0.05, flash=0.80, run="R2", params={"num_leaves": 63}))
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(reg), encoding="utf-8")
    monkeypatch.setattr(registry, "REGISTRY", path)
    monkeypatch.setattr(registry, "load", lambda: json.loads(path.read_text(encoding="utf-8")))
    registry.cli(["revert", "y_any_h2", "--reason", "harness CSV"])
    out = json.loads(path.read_text(encoding="utf-8"))
    assert out["champions"]["y_any_h2"]["entry_id"] == "R1/lightgbm/y_any_h2"
    assert out["decisions"][-1]["decision"] == "reverted"


def test_revert_skips_rescores_of_the_same_configuration():
    """R2's params were promoted over R1's, then re-scored on new folds as R3: reverting R3 undoes R2's promotion."""
    reg = {"runs": [], "champions": {}, "decisions": []}
    add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75, features=["a"], cats=[], params=P))
    tuned = dict(features=["a"], cats=[], params={**P, "num_leaves": 63})
    add(reg, entry("lightgbm", 0.80, 0.05, flash=0.80, run="R2", **tuned))
    assert add(reg, entry("lightgbm", 0.60, 0.05, flash=0.70, run="R3", folds=("2023-10-01",), **tuned)) == "promoted"
    d = registry.revert(reg, "y_any_h2", "the tuned params fail", at="now")
    assert reg["champions"]["y_any_h2"]["entry_id"] == "R1/lightgbm/y_any_h2"
    assert d["champion_before"] == "R3/lightgbm/y_any_h2" and "promotion of R2/lightgbm/y_any_h2" in d["reason"]
