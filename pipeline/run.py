"""
Pipeline entry point:  python -m pipeline.run <step>

  identity   resolve clean rows to PRJ keys (pipeline/build_identity.py)
  silver     identity, then the silver build (pipeline/silver.py)
  external   delay events from the report remarks (pipeline/external.py)
  gold       features and labels from silver (pipeline/gold.py)
  train      backtest, refit and register the models (ml/backtest.py, ml/registry.py)
  score      score the current portfolio, then analogues and scenarios (ml/score.py, ml/analogues.py)
  profile    canonical agencies and the agency matrix (pipeline/agency.py), then the risk-profile checklist and the
             external early-notice summary (ml/risk_profile.py), which writes the serving version file last
  all        silver, external, gold, train, score and profile in order
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import agency, build_identity, external, gold, silver  # noqa: E402

ALL = ["silver", "external", "gold", "train", "score", "profile"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.run")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("identity", help="resolve clean rows to PRJ keys")
    sub.add_parser("silver", help="identity, then typed rows, quarantine and the panel")
    sub.add_parser("external", help="delay events from the report remarks")
    sub.add_parser("gold", help="point-in-time features, horizon labels and the gold manifest")
    sub.add_parser("train", help="rolling-origin backtest, model refit and file registry")
    sub.add_parser("score", help="predictions, intervals, SHAP and rank tiers for the current portfolio")
    sub.add_parser("profile", help="agency matrix, 12 checks + external composite per project, early-notice summary")
    sub.add_parser("all", help="silver, external, gold, train, score and profile")
    args = ap.parse_args(argv)
    steps = ALL if args.step == "all" else [args.step]
    t0 = time.time()
    if steps[0] in ("identity", "silver"):
        build_identity.main([])
    if "silver" in steps:
        silver.main()
    if "external" in steps:
        external.main()
    if "gold" in steps:
        gold.main()
    # the model steps import sklearn and LightGBM, so only when they run
    if "train" in steps:
        from ml import registry
        registry.main()
    if "score" in steps:
        from ml import analogues, score
        score.main()
        analogues.main()
    if "profile" in steps:
        from ml import risk_profile
        agency.main()
        risk_profile.main()
    print(f"{args.step}: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
