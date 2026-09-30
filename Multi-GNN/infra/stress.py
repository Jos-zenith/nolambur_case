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

Rules r2.1 (reports/README.md 3.4): fresh draws of every variant (--stream 2), then r2.0 vs r2.1
vs r2.1 with friction on the base data, the original draws and the fresh ones:
    python -m infra.stress gen --stream 2 && python -m infra.stress score --stream 2
    python -m infra.stress rules                  # reports/rules_r21.json
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
RULES_REPORT = ROOT / "reports" / "rules_r21.json"
RULE_ARMS = (("r2.0", False), ("r2.1", False), ("r2.1", True))  # (RAIL_RULES, model friction)
REPORTED_FACTOR = 514.0  # reported UPI fraud is ~514x rarer than the test-day payments (ablation_v2.json)
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


def variant_dir(name: str, scope: str = "test", stream: int = 1) -> Path:
    folder = name if scope == "test" else f"{name}_all"
    return VARIANT_ROOT / (folder if stream == 1 else f"{folder}_s{stream}") / "nolambur_v2"


def generate(names: list[str], scope: str = "test", stream: int = 1) -> None:
    import prepare_datasets

    for name in names:
        out = variant_dir(name, scope, stream)
        subprocess.run([sys.executable, str(ROOT / "nolambur_v2_gen.py"), *VARIANTS[name], "--scope", scope, "--stream", str(stream), "--out", str(out)],
                       check=True, stdout=subprocess.DEVNULL)
        prepare_datasets.convert_nolambur(out.parent, dataset="v2")


def _register(name: str, scope: str = "test", checkpoint: Path | None = None, stream: int = 1) -> str:
    """Make a variant loadable by infra.scorer (which looks datasets up by key)."""
    d = variant_dir(name, scope, stream)
    key = f"stress_{name}_{scope}_{stream}"
    online.DATASETS[key] = {"dir": d, "raw": d / "transactions.csv", "labels": d / "labels.csv",
                            "checkpoint": checkpoint or online.DATASETS["v2"]["checkpoint"]}
    return key


def scores_path(name: str, model: str = "frozen", scope: str = "test", stream: int = 1) -> Path:
    return variant_dir(name, scope, stream) / f"online_scores_{model}.npy"


def score(name: str, model: str = "frozen", scope: str = "test", checkpoint: Path | None = None, stream: int = 1) -> dict[str, Any]:
    key = _register(name, scope, checkpoint, stream)
    return online.precompute(key, target=scores_path(name, model, scope, stream))


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
            "innocentRestricted": p["innocentRestricted"], "innocentRestrictionHours": p["innocentRestrictionHours"],
            "fraudDelayed": p.get("fraudDelayed"), "genuineDelayedThenReleased": p["genuineDelayedThenReleased"],
            "restrictions": p["restrictions"], "alertsPerDay": d["alertsPerDay"], "alertsPerAnalystPerDay": d["alertsPerAnalystPerDay"],
        },
        "rules": d.get("ruleVersion"), "modelFriction": d.get("modelFriction"),
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


def _with_rules(rules: str, friction: bool):
    """RailEngine reads these at construction; set them for one arm."""
    import os

    os.environ["RAIL_RULES"] = rules
    os.environ["RAIL_MODEL_FRICTION"] = "1" if friction else "0"


def clean_cost(rules: str) -> dict[str, Any]:
    """False accounts a day over days 1-9 of the base data: alerted accounts that are not mules.
    Alert-only replay; day 0 is skipped because every payer is new on the first day."""
    import rail_engine as re_

    _with_rules(rules, False)
    spec = online.DATASETS["v2"]
    raw, labels = pd.read_csv(spec["raw"]), pd.read_csv(spec["labels"])
    data = re_.Dataset(raw, np.load(spec["dir"] / "online_scores.npy"), labels,
                       {"version": "v2", "file": "base", "splitDays": SPLIT_DAYS, "features": None, "checkpoint": ""})
    th = re_.choose_threshold(data)["threshold"]
    eng = re_.RailEngine(data, record_actions=False, auto_hold=False, model_threshold=th)
    eng.run_to_end()
    day0 = data.splits["train"][0]
    first: dict[str, tuple[float, str]] = {}
    for a in eng.alerts.values():
        if a.account_id not in first or a.created_t < first[a.account_id][0]:
            first[a.account_id] = (a.created_t, a.detector)
    false = [(t, det, data.kind.get(acct, "?")) for acct, (t, det) in first.items()
             if data.role.get(acct) not in ("l1_mule", "l2_mule") and t >= day0 + 86400]
    days = 9
    by_det: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for _, det, kind in false:
        by_det[det] = by_det.get(det, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
    rule_false = [x for x in false if x[1] != "model_only"]
    del data, eng
    gc.collect()
    return {"rules": rules, "days": days, "falseAccounts": len(false), "falsePerDay": len(false) / days,
            "falsePerAnalystPerDay": len(false) / days / 2, "ruleFalsePerDay": len(rule_false) / days,
            "byFirstDetector": by_det, "byKind": by_kind}


def rules_report() -> dict[str, Any]:
    """r2.0 vs r2.1 vs r2.1 + friction, on the base data, the original draws (3.3's development set)
    and the fresh draws (stream 2), all with the frozen model's scores."""
    base = online.DATASETS["v2"]
    datasets = [("base", "base", base["raw"], base["labels"], base["dir"] / "online_scores.npy")]
    for stream, label in ((1, "original"), (2, "fresh")):
        for name in VARIANTS:
            path = scores_path(name, "frozen", "test", stream)
            if path.exists():
                d = variant_dir(name, "test", stream)
                datasets.append((name, label, d / "transactions.csv", d / "labels.csv", path))
    rows: dict[str, Any] = {}
    for name, draw, raw_path, labels_path, path in datasets:
        raw, labels = pd.read_csv(raw_path), pd.read_csv(labels_path)
        scores = np.load(path)
        for rules, friction in RULE_ARMS:
            arm = rules + (" + friction" if friction else "")
            print(f"measuring {name} ({draw}) with {arm} ...", flush=True)
            _with_rules(rules, friction)
            m = measure(raw, labels, scores)
            c = m["counts"]
            # a false account per real mule, if mules were ~514x rarer among the same accounts
            m["falsePerMuleAt514x"] = (c["falseAccounts"] / c["mulesFound"] * REPORTED_FACTOR) if c["mulesFound"] else None
            rows[f"{name}/{draw}/{arm}"] = {"variant": name, "draw": draw, "arm": arm, "fraud": fraud_profile(raw), **m}
    cost = [clean_cost(r) for r in ("r2.0", "r2.1")]
    _with_rules("r2.0", False)
    out = {
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "protocol": "reports/README.md 3.4: r2.1 designed from the train days only; judged on fresh draws (stream 2) nobody had seen; "
                    "frozen production model and threshold throughout",
        "arms": [r + (" + friction" if f else "") for r, f in RULE_ARMS],
        "reportedFactor": REPORTED_FACTOR,
        "cleanCost": cost,
        "rows": rows,
    }
    RULES_REPORT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["gen", "score", "report", "rules"])
    parser.add_argument("--stream", type=int, default=1, help="gen/score: 1 = the original draws, 2+ = fresh ones")
    parser.add_argument("--variant", nargs="*", default=list(VARIANTS))
    parser.add_argument("--scope", choices=["test", "all"], default="test")
    parser.add_argument("--model", default="frozen", help="score: label for the scores file (frozen | retrained)")
    parser.add_argument("--checkpoint", type=Path, help="score: a retrained checkpoint instead of production")
    args = parser.parse_args(argv)
    if args.cmd == "gen":
        generate(args.variant, args.scope, args.stream)
    elif args.cmd == "score":
        for name in args.variant:
            print(json.dumps(score(name, args.model, args.scope, args.checkpoint, args.stream), indent=2))
    elif args.cmd == "rules":
        out = rules_report()
        print(json.dumps(out["cleanCost"], indent=2))
    else:
        out = report()
        for k, r in out["rows"].items():
            print(k, {m: r[m] for m in (*METRICS, *SECONDARY)})


if __name__ == "__main__":
    main()
