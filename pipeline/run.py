"""
Pipeline entry point:  python -m pipeline.run <step>

  identity   resolve clean rows to PRJ keys (pipeline/build_identity.py)
  silver     identity, then the silver build (pipeline/silver.py)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import build_identity, silver  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.run")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("identity", help="resolve clean rows to PRJ keys")
    sub.add_parser("silver", help="identity, then typed rows, quarantine and the panel")
    args = ap.parse_args(argv)
    t0 = time.time()
    build_identity.main([])
    if args.step == "silver":
        silver.main()
    print(f"{args.step}: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
