import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import registry  # noqa: E402


def entry(model, pr_auc, ece, folds=("2024-01-01", "2024-04-01"), gold="g1", run="R1"):
    return {"entry_id": f"{run}/{model}/y_any_h2", "run_id": run, "model": model, "target": "y_any", "horizon": 2,
            "gold_version": gold, "created_at": run,
            "metrics": {"pooled": {"pr_auc": pr_auc, "ece": ece}, "folds": [{"cutoff": c} for c in folds]}}


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
