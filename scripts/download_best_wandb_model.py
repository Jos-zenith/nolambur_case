#!/usr/bin/env python3
"""
Download the best model file from a Weights & Biases sweep.

Usage:
  python scripts/download_best_wandb_model.py <sweep_path> [--metric METRIC] [--file FILE] [--out OUT]

Example:
  python scripts/download_best_wandb_model.py zenithjoshua/fraud-detection-2stage/abcdef123456 --metric val_acc --file model.h5 --out model-best.h5

`sweep_path` should be in the format `entity/project/sweep_id`.

The script requires `WANDB_API_KEY` in the environment or a logged-in wandb session.
"""

import argparse
import os
import sys
import shutil
import logging
from typing import Optional

try:
    import wandb
except Exception as e:
    print("Please install wandb (pip install wandb) and try again.")
    raise

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def find_model_file(run: wandb.apis.public.Run, prefer_name: Optional[str]) -> Optional[str]:
    # Try exact filename first
    if prefer_name:
        try:
            f = run.file(prefer_name)
            # Accessing .name will raise if missing
            _ = f.name
            return prefer_name
        except Exception:
            pass
    # Fallback: find a file with model-like name
    for candidate in ("model.h5", "model.pt", "model.pth", "weights.h5", "checkpoint.pt"):
        try:
            f = run.file(candidate)
            _ = f.name
            return candidate
        except Exception:
            continue
    # Last resort: pick the first file whose name contains 'model' or 'weight'
    try:
        files = list(run.files())
    except Exception:
        return None
    for f in files:
        if "model" in f.name.lower() or "weight" in f.name.lower():
            return f.name
    # Give up
    return None


def main():
    parser = argparse.ArgumentParser(description="Download best model from W&B sweep")
    parser.add_argument("sweep_path", help="Sweep path: entity/project/sweep_id")
    parser.add_argument("--metric", default="val_acc", help="Metric in run.summary to sort by (default: val_acc)")
    parser.add_argument("--file", default=None, help="Preferred filename to download (e.g. model.h5). If omitted, tries common names.")
    parser.add_argument("--out", default="model-best.h5", help="Destination filename (default: model-best.h5)")
    parser.add_argument("--top", type=int, default=1, help="Which top run to pick (1 = best, 2 = second-best)")
    args = parser.parse_args()

    if os.getenv("WANDB_API_KEY") is None:
        logger.info("WANDB_API_KEY not found in environment. Ensure you're logged in or set WANDB_API_KEY.")

    api = wandb.Api()

    try:
        sweep = api.sweep(args.sweep_path)
    except Exception as e:
        logger.error(f"Failed to fetch sweep '{args.sweep_path}': {e}")
        sys.exit(2)

    runs = list(sweep.runs)
    if not runs:
        logger.error("No runs found in sweep.")
        sys.exit(3)

    # Sort runs by metric (descending)
    def metric_key(run):
        try:
            v = run.summary.get(args.metric)
            # If metric is a dict or nested, try to extract numeric
            if isinstance(v, dict):
                # flatten choices
                for val in v.values():
                    if isinstance(val, (int, float)):
                        return float(val)
                return 0.0
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    runs_sorted = sorted(runs, key=metric_key, reverse=True)

    idx = max(0, args.top - 1)
    if idx >= len(runs_sorted):
        logger.error("Requested top run index is out of range")
        sys.exit(4)

    best = runs_sorted[idx]
    best_metric = metric_key(best)
    logger.info(f"Best run: {best.name} (id={best.id}) with {args.metric}={best_metric}")

    model_fname = find_model_file(best, args.file)
    if model_fname is None:
        logger.error("Could not find a model file in the best run's artifacts.")
        logger.info("Available files:")
        try:
            for f in best.files():
                logger.info(f" - {f.name}")
        except Exception:
            pass
        sys.exit(5)

    logger.info(f"Downloading '{model_fname}' from run {best.id}...")

    try:
        fobj = best.file(model_fname)
        downloaded_path = fobj.download(replace=True)
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        sys.exit(6)

    # downloaded_path may be a path to a directory or file, handle accordingly
    if os.path.isdir(downloaded_path):
        # find a file inside
        contents = os.listdir(downloaded_path)
        if not contents:
            logger.error(f"Download directory is empty: {downloaded_path}")
            sys.exit(7)
        # pick the first file
        src = os.path.join(downloaded_path, contents[0])
    else:
        src = downloaded_path

    out = args.out
    try:
        shutil.copy(src, out)
    except Exception as e:
        logger.error(f"Failed to copy downloaded file to '{out}': {e}")
        sys.exit(8)

    logger.info(f"Saved best model to {out}")


if __name__ == "__main__":
    main()
