"""
Pipeline entry point:  python -m pipeline.run <step>

  identity   resolve clean rows to PRJ keys (pipeline/build_identity.py)
  silver     identity, then the silver build (pipeline/silver.py)
  gold       features and labels from silver (pipeline/gold.py)
  train      rolling-origin backtest of the models (ml/backtest.py)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml import backtest  # noqa: E402
from pipeline import build_identity, gold, silver  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.run")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("identity", help="resolve clean rows to PRJ keys")
    sub.add_parser("silver", help="identity, then typed rows, quarantine and the panel")
    sub.add_parser("gold", help="point-in-time features, horizon labels and the gold manifest")
    sub.add_parser("train", help="rolling-origin backtest into model/runs/<run_id>")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.step in ("identity", "silver"):
        build_identity.main([])
    if args.step == "silver":
        silver.main()
    if args.step == "gold":
        gold.main()
    if args.step == "train":
        backtest.main()
    print(f"{args.step}: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
