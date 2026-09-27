import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import registry  # noqa: E402


def entry(model, pr_auc, ece, folds=("2024-01-01", "2024-04-01"), gold="g1", run="R1", flash=None):
    m = {"pooled": {"pr_auc": pr_auc, "ece": ece}, "folds": [{"cutoff": c} for c in folds]}
    if flash is not None:
        m.update(flash={"pr_auc": flash, "ece": ece}, flash_folds=[{"cutoff": "2025-07-01"}])
    return {"entry_id": f"{run}/{model}/y_any_h2", "run_id": run, "model": model, "target": "y_any", "horizon": 2,
            "gold_version": gold, "created_at": run, "metrics": m}


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
    margin = registry.NOISE_SDS * registry.SEED_SD["y_any_h2"]
    reg = {"runs": [], "champions": {}, "decisions": []}
    assert add(reg, entry("lightgbm", 0.70, 0.05, flash=0.75)) == "promoted"
    assert add(reg, entry("logreg", 0.70 + margin / 2, 0.05, flash=0.75, run="R2")) == "rejected"   # inside noise
    assert add(reg, entry("logreg", 0.75, 0.05, flash=0.749, run="R3")) == "rejected"   # worse on the flash block
    assert add(reg, entry("logreg", 0.70, 0.05, flash=0.75 + margin, run="R4")) == "promoted"   # flash gain alone
    assert reg["champions"]["y_any_h2"]["entry_id"] == "R4/logreg/y_any_h2"
    assert "flash -0.0010" in reg["decisions"][2]["reason"]
    # a champion scored without the flash block has other folds: only its own model type may take over
    assert add(reg, entry("lightgbm", 0.99, 0.01, run="R5")) == "rejected"
