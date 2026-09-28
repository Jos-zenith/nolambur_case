"""Analyst decisions -> edge labels -> a retrained checkpoint.

    python -m infra.feedback report            what the decisions say, and how they compare to the dataset labels
    python -m infra.feedback build             write data/feedback/formatted_transactions.csv with the overrides
    python -m infra.feedback retrain [--epochs 10]
                                               build, then finetune into models/feedback/ (never over the live checkpoint)

Labelling rule: freeze = the analyst confirmed a mule, so every transfer in that
alert's evidence becomes fraud (1); clear = false positive, so they become clean (0);
escalate gives no label. When several decisions touch one transfer, the latest wins.

On Nolambur every transfer already has a ground-truth label, so feedback can only
agree with it or overwrite it; the report shows which. With real traffic, where most
transfers never get a label, these decisions would be the main source of new labels.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from typing import Any

import pandas as pd

from . import settings
from .store import get_store

LABEL = {"freeze": 1, "clear": 0}
FORMATTED = settings.MULTI_GNN_DIR / "nolambur" / "formatted_transactions.csv"
RAW = settings.MULTI_GNN_DIR / "nolambur_transactions.csv"
OUT_DIR = settings.DATA_DIR / "feedback"
OUT_CSV = OUT_DIR / "formatted_transactions.csv"


def edge_labels(decisions: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    labels: dict[int, dict[str, Any]] = {}
    for d in sorted(decisions, key=lambda d: d["at"]):
        if d["decision"] not in LABEL:
            continue
        # Live (ingested) payments have row ids from 1,000,000 up and no dataset row to relabel.
        for row in d.get("rows") or []:
            if row < 1_000_000:
                labels[int(row)] = {"label": LABEL[d["decision"]], "decision": d["decision"], "alertId": d["alert_id"], "runId": d["run_id"], "actor": d["actor"]}
    return labels


def report(decisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    decisions = get_store().all_decisions() if decisions is None else decisions
    labels = edge_labels(decisions)
    truth = pd.read_csv(RAW, usecols=["is_fraud"])["is_fraud"].tolist()
    agree = sum(1 for row, l in labels.items() if row < len(truth) and truth[row] == l["label"])
    flips = [row for row, l in labels.items() if row < len(truth) and truth[row] != l["label"]]
    accounts = Counter(d["decision"] for d in decisions)
    confirmed = [d for d in decisions if d["decision"] == "freeze"]
    cleared = [d for d in decisions if d["decision"] == "clear"]
    mule = ("l1_mule", "l2_mule")
    return {
        "decisions": dict(accounts),
        "runs": len({d["run_id"] for d in decisions}),
        "labelledEdges": len(labels),
        "fraudLabels": sum(1 for l in labels.values() if l["label"] == 1),
        "cleanLabels": sum(1 for l in labels.values() if l["label"] == 0),
        "agreeWithDataset": agree,
        "wouldFlip": len(flips),
        "freezesOnTrueMules": sum(1 for d in confirmed if d["truth_role"] in mule),
        "freezes": len(confirmed),
        "clearsOnTrueMules": sum(1 for d in cleared if d["truth_role"] in mule),
        "clears": len(cleared),
        "byDetector": {
            det: {"freeze": sum(1 for d in decisions if d["detector"] == det and d["decision"] == "freeze"),
                  "clear": sum(1 for d in decisions if d["detector"] == det and d["decision"] == "clear")}
            for det in sorted({d["detector"] for d in decisions if d["detector"]})
        },
        "lastRetrain": _last_retrain(),
    }


def build() -> dict[str, Any]:
    labels = edge_labels(get_store().all_decisions())
    df = pd.read_csv(FORMATTED)
    raw_amounts = pd.read_csv(RAW, usecols=["amount_inr"])["amount_inr"]
    # formatted EdgeID i is raw CSV row i (prepare_datasets.convert_nolambur keeps file order)
    if len(df) != len(raw_amounts) or not (df["Amount Received"].round() == raw_amounts.round()).all():
        raise RuntimeError("nolambur/formatted_transactions.csv is out of step with nolambur_transactions.csv; rerun prepare_datasets")
    before = df["Is Laundering"].copy()
    for row, l in labels.items():
        if row < len(df):
            df.at[row, "Is Laundering"] = l["label"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    changed = int((before != df["Is Laundering"]).sum())
    return {"path": str(OUT_CSV), "edges": len(df), "overrides": len(labels), "changed": changed, "fraudEdges": int(df["Is Laundering"].sum())}


def _last_retrain() -> dict[str, Any] | None:
    meta = settings.MULTI_GNN_DIR / "models" / "feedback" / "retrain.json"
    return json.loads(meta.read_text()) if meta.exists() else None


def retrain(epochs: int) -> dict[str, Any]:
    built = build()
    save_dir = settings.MULTI_GNN_DIR / "models" / "feedback"
    save_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "finetune_local_nolambur.py", "--finetune-epochs", str(epochs), "--save-dir", str(save_dir)],
        cwd=settings.MULTI_GNN_DIR,
        env={**os.environ, "NOLAMBUR_TRAIN_CSV": str(OUT_CSV)},
    )
    meta = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - started, 1),
        "exitCode": proc.returncode,
        "epochs": epochs,
        "checkpoint": str(save_dir / "local_finetuned_gin_nolambur.pt"),
        "trainingData": built,
        "promoted": False,
        "note": "Not promoted. Compare against the live checkpoint, then copy it over models/local_finetuned_gin_nolambur.pt by hand.",
    }
    (save_dir / "retrain.json").write_text(json.dumps(meta, indent=2))
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["report", "build", "retrain"])
    parser.add_argument("--epochs", type=int, default=10)
    args = parser.parse_args()
    out = {"report": report, "build": build, "retrain": lambda: retrain(args.epochs)}[args.command]()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
