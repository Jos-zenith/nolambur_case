"""Stress tests: fast mules, structuring, and low-value rings, against the frozen production model.

Each variant rewrites only the test-day campaigns (days 8-9) of nolambur_v2 (nolambur_v2_gen.py
--variant ... --scope test). Days 0-7 are byte-identical to the base data, so the frozen model's
training days and its validation threshold are untouched: this measures what happens when the
adversary changes behaviour after the model was built. `redraw` is the control: base behaviour
on the same new random stream the variants use.

The metrics were fixed before any variant was run (METRICS below; reports/README.md 3.3).
Rules stay r2.0. A variant where the frozen model collapses (model recall on fraud payments
below COLLAPSE_RECALL) is also retrained on data where every campaign has the new behaviour
(--scope all), to ask a different question: is the pattern still learnable?

    python -m infra.stress gen                    # data/variants/<name>/nolambur_v2/ (gitignored)
    python -m infra.stress score --variant fast   # frozen-model online scores, ~26 min each
    python -m infra.stress report                 # reports/stress_v2.json
"""

from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra import scorer as online  # noqa: E402

VARIANT_ROOT = ROOT / "data" / "variants"
REPORT = ROOT / "reports" / "stress_v2.json"
SPLIT_DAYS = {"train": [0, 6], "val": [6, 8], "test": [8, 10]}

# name -> generator arguments
VARIANTS: dict[str, list[str]] = {
    "redraw": ["--variant", "redraw"],
    "fast": ["--variant", "fast"],
    "struct": ["--variant", "struct"],
    "low_0.5": ["--variant", "low", "--scale", "0.5"],
    "low_0.2": ["--variant", "low", "--scale", "0.2"],
    "low_0.1": ["--variant", "low", "--scale", "0.1"],
    "low_0.05": ["--variant", "low", "--scale", "0.05"],
}

# Fixed before the first variant was scored. Test days only; frozen model, threshold from days 6-7.
METRICS = {
    "recall": "mules found by rules + model / mules active on the test days",
    "precision": "mules / accounts alerted by rules + model",
    "leadMedianSeconds": "median over alerted mules of (first time fraud money left the mule - first alert); negative = too late",
    "alertedBeforeMoneyLeft": "mules alerted before any fraud money left them / mules that forwarded fraud money",
    "moneyStoppedShare": "fraud money stopped by graded holds, router acting alone / all test-day fraud money",
}
SECONDARY = ("rulesOnlyRecall", "rulesOnlyPrecision", "modelEdgeRecall", "modelEdgePrecision")
COLLAPSE_RECALL = 0.40  # half the production model's 0.79 on the base test days


def variant_dir(name: str, scope: str = "test") -> Path:
    return VARIANT_ROOT / (name if scope == "test" else f"{name}_all") / "nolambur_v2"


def generate(names: list[str], scope: str = "test") -> None:
    import prepare_datasets

    for name in names:
        out = variant_dir(name, scope)
        subprocess.run([sys.executable, str(ROOT / "nolambur_v2_gen.py"), *VARIANTS[name], "--scope", scope, "--out", str(out)],
                       check=True, stdout=subprocess.DEVNULL)
        prepare_datasets.convert_nolambur(out.parent, dataset="v2")


def _register(name: str, scope: str = "test", checkpoint: Path | None = None) -> str:
    """Make a variant loadable by infra.scorer (which looks datasets up by key)."""
    d = variant_dir(name, scope)
    key = f"stress_{name}_{scope}"
    online.DATASETS[key] = {"dir": d, "raw": d / "transactions.csv", "labels": d / "labels.csv",
                            "checkpoint": checkpoint or online.DATASETS["v2"]["checkpoint"]}
    return key


def scores_path(name: str, model: str = "frozen", scope: str = "test") -> Path:
    return variant_dir(name, scope) / f"online_scores_{model}.npy"


def score(name: str, model: str = "frozen", scope: str = "test", checkpoint: Path | None = None) -> dict[str, Any]:
    key = _register(name, scope, checkpoint)
    return online.precompute(key, target=scores_path(name, model, scope))


def measure(raw: pd.DataFrame, labels: pd.DataFrame, scores: np.ndarray) -> dict[str, Any]:
    import rail_engine as re_

    data = re_.Dataset(raw, scores, labels, {"version": "v2", "file": "variant", "splitDays": SPLIT_DAYS, "features": None, "checkpoint": ""})
    ev = re_.evaluate_temporal(data)
    d, p, m = ev["detectors"], ev["policy"], ev["test"]["atThreshold"]
    lead = d["leadSeconds"]
    out = {
        "recall": d["combined"]["recall"],
        "precision": d["combined"]["precision"],
        "leadMedianSeconds": lead["median"],
        "alertedBeforeMoneyLeft": lead["alertedBeforeMoneyLeft"] / lead["mulesThatForwarded"] if lead["mulesThatForwarded"] else None,
        "moneyStoppedShare": p["fraudStopped"] / p["fraudTotal"] if p["fraudTotal"] else None,
        "rulesOnlyRecall": d["accountLevel"]["recall"],
        "rulesOnlyPrecision": d["accountLevel"]["precision"],
        "modelEdgeRecall": m["recall"],
        "modelEdgePrecision": m["precision"],
        "counts": {
            "mulesActive": d["mulesActive"], "mulesFound": d["combined"]["tp"], "falseAccounts": d["combined"]["fp"],
            "rulesOnlyFound": d["accountLevel"]["tp"], "rulesOnlyFalse": d["accountLevel"]["fp"],
            "mulesThatForwarded": lead["mulesThatForwarded"], "alertedBeforeMoneyLeft": lead["alertedBeforeMoneyLeft"],
            "fraudPayments": ev["test"]["positives"], "modelCaught": m["tp"], "modelFalse": m["fp"],
            "fraudTotal": p["fraudTotal"], "fraudStopped": p["fraudStopped"], "genuineBlocked": p["genuineBlocked"],
            "innocentRestricted": p["innocentRestricted"],
        },
        "threshold": ev["test"]["threshold"],
        "byDetector": d["byDetector"],
        "precisionCi": d["combined"]["precisionCi"], "recallCi": d["combined"]["recallCi"],
    }
    del data, ev
    gc.collect()
    return out


def fraud_profile(raw: pd.DataFrame) -> dict[str, Any]:
    ts = raw["timestamp"]
    f = raw[(raw["is_fraud"] == 1) & (ts >= "2024-03-19")]
    return {"payments": int(len(f)), "medianAmount": float(f["amount_inr"].median()), "maxAmount": float(f["amount_inr"].max()),
            "victimTotal": float(f.loc[f["layer"] == "L0→L1", "amount_inr"].sum()), "allLayersTotal": float(f["amount_inr"].sum())}


def report() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    base = online.DATASETS["v2"]
    targets = [("base", base["raw"], base["labels"], base["dir"] / "online_scores.npy", "frozen", "test")]
    for name in VARIANTS:
        for model, scope in (("frozen", "test"), ("retrained", "all")):
            path = scores_path(name, model, scope)
            if path.exists():
                d = variant_dir(name, scope)
                targets.append((name, d / "transactions.csv", d / "labels.csv", path, model, scope))
    for name, raw_path, labels_path, path, model, scope in targets:
        print(f"measuring {name} ({model}) ...", flush=True)
        raw, labels = pd.read_csv(raw_path), pd.read_csv(labels_path)
        rows[f"{name}/{model}"] = {"variant": name, "model": model, "scope": scope, "fraud": fraud_profile(raw), **measure(raw, labels, np.load(path))}
    out = {
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "protocol": "test days 8-9 only; frozen = production checkpoint and its validation threshold, variant applied to the test campaigns only; "
                    "retrained = same recipe (seed 42, 12 epochs) on data where every campaign has the variant; rules r2.0 unchanged",
        "metrics": METRICS,
        "collapseRecall": COLLAPSE_RECALL,
        "rows": rows,
    }
    REPORT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["gen", "score", "report"])
    parser.add_argument("--variant", nargs="*", default=list(VARIANTS))
    parser.add_argument("--scope", choices=["test", "all"], default="test")
    parser.add_argument("--model", default="frozen", help="score: label for the scores file (frozen | retrained)")
    parser.add_argument("--checkpoint", type=Path, help="score: a retrained checkpoint instead of production")
    args = parser.parse_args(argv)
    if args.cmd == "gen":
        generate(args.variant, args.scope)
    elif args.cmd == "score":
        for name in args.variant:
            print(json.dumps(score(name, args.model, args.scope, args.checkpoint), indent=2))
    else:
        out = report()
        for k, r in out["rows"].items():
            print(k, {m: r[m] for m in (*METRICS, *SECONDARY)})


if __name__ == "__main__":
    main()
