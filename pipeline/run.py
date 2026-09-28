"""
Pipeline entry point:  python -m pipeline.run <step>

  identity   resolve clean rows to PRJ keys (pipeline/build_identity.py)
  silver     identity, then the silver build (pipeline/silver.py)
  external   delay events from the report remarks (pipeline/external.py)
  research   the web research facts of dataset/raw/external/research (pipeline/research.py); evidence for the risk
             profile and the project page, not a gold feature, so it only has to run before profile (after external
             here, so `all` and the report watcher refresh its live flags with the new asof and keys)
  gold       features and labels from silver (pipeline/gold.py)
  train      backtest, refit and register the models (ml/backtest.py, ml/registry.py)
  score      score the current portfolio, then analogues and scenarios (ml/score.py, ml/analogues.py)
  profile    canonical agencies and the agency matrix (pipeline/agency.py), bottleneck clusters
             (pipeline/bottlenecks.py), the measured hidden-delay priors (pipeline/hidden_delay.py), then the
             risk-profile checklist and the external early-notice summary (ml/risk_profile.py), which writes the
             serving version file last
  all        silver, external, research, gold, train, score and profile in order

A failed step stops the run (its exception propagates; the later steps do not run), and the steps before it are
complete: each step reads only the outputs of the steps before it and writes only its own. What the serving side
sees is switched atomically: the backend loads a data version when gold/external_summary.json (written last by
profile) or gold/research_summary.json (written last by research, after its two tables) changes, and ml/score.py
writes predictions_latest.json before the scenarios, analogues and risk-profile files it points at, so a run that
fails halfway is never served (backend/serving.py); the report watcher pins the served version while a run goes and
keeps the previous scores when a step fails (backend/live/watcher.py). What is not atomic is a step's own files on
disk: silver, external, research, gold, score and profile write their parquet and JSON files in place (to_parquet,
write_text), so a crash in the middle of a write can leave that one file truncated. A running backend keeps serving
the old version, but a restart would fail to load it until the step is rerun; the fix is to run the step again.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import agency, bottlenecks, build_identity, external, gold, hidden_delay, research, silver  # noqa: E402

ALL = ["silver", "external", "research", "gold", "train", "score", "profile"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.run")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("identity", help="resolve clean rows to PRJ keys")
    sub.add_parser("silver", help="identity, then typed rows, quarantine and the panel")
    sub.add_parser("external", help="delay events from the report remarks")
    sub.add_parser("research", help="validated web research facts (evidence, not a model feature)")
    sub.add_parser("gold", help="point-in-time features, horizon labels and the gold manifest")
    sub.add_parser("train", help="rolling-origin backtest, model refit and file registry")
    sub.add_parser("score", help="predictions, intervals, SHAP and rank tiers for the current portfolio")
    sub.add_parser("profile", help="agency matrix, bottlenecks, hidden-delay priors, 12 checks + external composite, "
                                   "early-notice summary")
    sub.add_parser("all", help="silver, external, research, gold, train, score and profile")
    args = ap.parse_args(argv)
    steps = ALL if args.step == "all" else [args.step]
    t0 = time.time()
    if steps[0] in ("identity", "silver"):
        build_identity.main([])
    if "silver" in steps:
        silver.main()
    if "external" in steps:
        external.main()
    if "research" in steps:
        research.main()
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
        bottlenecks.main()
        hidden_delay.main()
        risk_profile.main()
    print(f"{args.step}: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
