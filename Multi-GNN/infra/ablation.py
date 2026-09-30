"""Does the GNN earn its place, or is amount doing the work? And what happens at real base rates?

Every arm is scored and judged the same way as the production model (rail_engine.evaluate_temporal):
fit on days 0-5, pick the alert threshold that maximises F1 on days 6-7, report days 8-9 only.
GNN scores are online and time-respecting (infra/scorer.py precompute).

Arms:
  amount_only      logistic regression on log amount, nothing else
  tabular          gradient boosting on the GNN's own inputs (hour, log amount, channel), no graph
  gnn_full_s*      GINe on hour, log amount, channel (s42 is the production checkpoint)
  gnn_noamt_s*     GINe on hour and channel only: amount removed, retrained
  gnn_full_permuted production checkpoint, test-day amounts shuffled among test-day payments

Each arm's scores also go through the rules engine as its "model" input, so the account-level
rules + model numbers show what each arm adds to the rules, not only on its own.

The base-rate section takes the production arm's measured error rates and projects precision
at rarer fraud. It is arithmetic, not a measurement: it assumes recall and false-positive rate
stay put when fraud gets rarer.

    python -m infra.ablation scores     # online scores for models/ablation/*/ and the permuted run
    python -m infra.ablation report     # reports/ablation_v2.json
    python -m infra.ablation baserates  # recompute only the base-rate section from the report's counts

Train the ablation checkpoints first (from any other working directory, so logs/logs.log,
which the Model page reads, is left alone):
    NOLAMBUR_EDGE_FEATURES="HourOfDay,Payment Format" python finetune_local_nolambur.py \\
        --dataset v2 --finetune-epochs 12 --seed 42 --save-dir models/ablation/noamt_s42
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra import scorer as online  # noqa: E402

ABLATION_DIR = ROOT / "models" / "ablation"
REPORT = ROOT / "reports" / "ablation_v2.json"
SPLIT_DAYS = {"train": [0, 6], "val": [6, 8], "test": [8, 10]}
PERMUTE_SEED = 7
BASE_RATE_DIVISORS = (1, 10, 100, 1000)
# Reported UPI fraud, FY 2024-25 (MoS Finance, Lok Sabha): 12.64 lakh incidents in 185.8 billion
# UPI transactions. Incidents, not payments, and under-reported, so a rough anchor only.
REPORTED_UPI = {"incidents": 1_264_000, "transactions": 185.8e9, "period": "FY 2024-25",
                "source": "https://www.moneylife.in/article/upi-frauds-27-lakh-cases-worth-rs2145-crore-registered-in-30-months-govt/75709.html"}


# ---------------------------------------------------------------------- scores


def _epoch(raw: pd.DataFrame) -> np.ndarray:
    ts = pd.to_datetime(raw["timestamp"])
    return ((ts - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def _in_test(raw: pd.DataFrame) -> np.ndarray:
    epoch = _epoch(raw)
    t0, t1 = _test_window(epoch)
    return (epoch >= t0) & (epoch < t1)


def _test_window(epoch: np.ndarray) -> tuple[float, float]:
    day0 = math.floor(epoch.min() / 86400) * 86400
    a, b = SPLIT_DAYS["test"]
    return day0 + a * 86400, day0 + b * 86400


def permute_test_amounts(feats: np.ndarray, names: list[str], raw: pd.DataFrame, epoch: np.ndarray) -> np.ndarray:
    """Shuffle LogAmount among test-day payments; every other input and all history stay real."""
    col = names.index("LogAmount")
    t0, t1 = _test_window(epoch)
    idx = np.flatnonzero((epoch >= t0) & (epoch < t1))
    out = feats.copy()
    out[idx, col] = feats[np.random.default_rng(PERMUTE_SEED).permutation(idx), col]
    return out


def gnn_arms() -> dict[str, Path]:
    """Arm name -> checkpoint. s42 of the full model is the production checkpoint."""
    arms = {"gnn_full_s42": online.DATASETS["v2"]["checkpoint"]}
    for d in sorted(ABLATION_DIR.glob("*_s*")):
        ckpt = d / "local_finetuned_gin_nolambur_v2.pt"
        if ckpt.exists():
            arms[f"gnn_{d.name}"] = ckpt
    return arms


def compute_scores(only: list[str] | None = None) -> dict[str, Any]:
    out = {}
    for name, ckpt in gnn_arms().items():
        if name == "gnn_full_s42" or (only and name not in only):
            continue  # nolambur_v2/online_scores.npy already holds it (the bridge keeps it current)
        target = ckpt.parent / "online_scores.npy"
        out[name] = online.precompute("v2", checkpoint=ckpt, target=target)
    if only and "gnn_full_permuted" not in only:
        return out
    target = ABLATION_DIR / "full_permuted" / "online_scores.npy"
    target.parent.mkdir(parents=True, exist_ok=True)
    out["gnn_full_permuted"] = online.precompute("v2", target=target, transform=permute_test_amounts)
    return out


def _gnn_scores(name: str) -> np.ndarray:
    if name == "gnn_full_s42":
        return np.load(online.DATASETS["v2"]["dir"] / "online_scores.npy")
    if name == "gnn_full_permuted":
        return np.load(ABLATION_DIR / "full_permuted" / "online_scores.npy")
    return np.load(ABLATION_DIR / name.removeprefix("gnn_") / "online_scores.npy")


def tabular_scores(raw: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per-payment models with no graph, fit on the train days, in raw CSV row order."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    epoch = _epoch(raw)
    day0 = math.floor(epoch.min() / 86400) * 86400
    train = epoch < day0 + SPLIT_DAYS["train"][1] * 86400
    y = raw["is_fraud"].to_numpy()
    log_amt = np.log1p(raw["amount_inr"].to_numpy(dtype=float))
    hour = ((epoch - day0) % 86400) / 3600.0
    p2m = (raw["channel"] == "P2M").to_numpy(dtype=float)

    amount = LogisticRegression(class_weight="balanced").fit(log_amt[train, None], y[train])
    x = np.column_stack([hour, log_amt, p2m])
    gbm = HistGradientBoostingClassifier(class_weight="balanced", max_iter=200, random_state=0).fit(x[train], y[train])
    return {"amount_only": amount.predict_proba(log_amt[:, None])[:, 1], "tabular": gbm.predict_proba(x)[:, 1]}


# ---------------------------------------------------------------------- evaluation


def _summary(ev: dict[str, Any], rows: list, th: float) -> dict[str, Any]:
    """The parts of evaluate_temporal that compare arms, plus recall per chain layer."""
    t = ev["test"]
    d = ev["detectors"]
    p = ev["policy"]
    fraud = [r for r in rows if r.is_fraud]
    by_layer = {}
    for layer in sorted({r.layer for r in fraud}):
        sub = [r for r in fraud if r.layer == layer]
        by_layer[layer] = {"fraud": len(sub), "caught": sum(1 for r in sub if r.gnn >= th)}
    return {
        "edge": {"rocAuc": t["rocAuc"], "averagePrecision": t["averagePrecision"], "threshold": t["threshold"],
                 **{k: t["atThreshold"][k] for k in ("tp", "fp", "fn", "precision", "recall", "f1", "precisionCi", "recallCi")},
                 "recallByLayer": by_layer, "precisionAtK": t["precisionAtK"]},
        "accounts": {"mulesActive": d["mulesActive"], "rulesOnly": d["accountLevel"], "rulesPlusModel": d["combined"],
                     "modelOnlyAccounts": d["modelOnlyAccounts"], "modelOnlyMules": d["modelOnlyMules"],
                     "leadSecondsMedian": d["leadSeconds"]["median"], "alertsPerDay": d["alertsPerDay"]},
        "policy": {"fraudTotal": p["fraudTotal"], "fraudStopped": p["fraudStopped"], "genuineBlocked": p["genuineBlocked"],
                   "restrictedAccounts": p["restrictedAccounts"], "innocentRestricted": p["innocentRestricted"]},
    }


def evaluate_arm(raw: pd.DataFrame, labels: pd.DataFrame, scores: np.ndarray, name: str) -> dict[str, Any]:
    import rail_engine as re_

    data = re_.Dataset(raw, scores, labels, {"version": "v2", "file": "nolambur_v2/transactions.csv", "splitDays": SPLIT_DAYS,
                                             "features": name, "checkpoint": ""})
    started = time.perf_counter()
    ev = re_.evaluate_temporal(data)
    t0, t1 = data.splits["test"]
    out = _summary(ev, [r for r in data.rows if t0 <= r.t < t1], ev["test"]["threshold"])
    out["validation"] = ev["test"]["validation"]
    out["seconds"] = round(time.perf_counter() - started, 1)
    del data, ev
    gc.collect()
    return out


# ---------------------------------------------------------------------- base rates


def _clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    from scipy.stats import beta

    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def _precision(tpr: float, fpr: float, prevalence: float) -> float:
    hit = tpr * prevalence
    return hit / (hit + fpr * (1 - prevalence)) if hit + fpr else 0.0


def reported_factor(payment_prevalence: float) -> float:
    """How much rarer reported UPI fraud is than fraud in the test-day payments."""
    return payment_prevalence / (REPORTED_UPI["incidents"] / REPORTED_UPI["transactions"])


def base_rate_table(tp: int, fn: int, fp: int, negatives: int, unit: str, anchor: float | None = None) -> dict[str, Any]:
    """Precision if fraud were 10x, 100x, 1000x rarer, holding recall and false-positive rate fixed.

    Range: pessimistic = recall at its 95% lower bound and FPR at its upper; optimistic the
    reverse. Exact (Clopper-Pearson) intervals, because the false positives are a handful.
    anchor adds a row at that factor: the reported UPI rate. For payments it is measured against
    payments; for accounts it reuses the payment factor, a rough guess, since the share of mule
    accounts is not the share of fraud payments."""
    positives = tp + fn
    tpr, fpr = tp / positives, fp / negatives
    tpr_lo, tpr_hi = _clopper_pearson(tp, positives)
    fpr_lo, fpr_hi = _clopper_pearson(fp, negatives)
    prev0 = positives / (positives + negatives)
    rows = []
    for div in (*BASE_RATE_DIVISORS, *([anchor] if anchor else [])):
        prev = prev0 / div
        point = _precision(tpr, fpr, prev)
        rows.append({
            "rarer": round(div, 1), "prevalence": prev, "anchor": div not in BASE_RATE_DIVISORS,
            "precision": point, "precisionLow": _precision(tpr_lo, fpr_hi, prev), "precisionHigh": _precision(tpr_hi, fpr_lo, prev),
            "falsePerTrue": (1 - point) / point if point else None,
        })
    return {"unit": unit, "tp": tp, "fn": fn, "fp": fp, "negatives": negatives, "measuredPrevalence": prev0,
            "recall": tpr, "recallCi": [tpr_lo, tpr_hi], "falsePositiveRate": fpr, "falsePositiveRateCi": [fpr_lo, fpr_hi], "rows": rows}


def clean_accounts_active_in_test(raw: pd.DataFrame, labels: pd.DataFrame) -> int:
    test = raw[_in_test(raw)]
    active = set(test["sender_id"].astype(str)) | set(test["recv_id"].astype(str))
    mules = set(labels.loc[labels["role"].isin(["l1_mule", "l2_mule"]), "account_id"].astype(str))
    return len(active - mules)


# ---------------------------------------------------------------------- report


def report() -> dict[str, Any]:
    spec = online.DATASETS["v2"]
    raw = pd.read_csv(spec["raw"])
    labels = pd.read_csv(spec["labels"])
    arms: dict[str, np.ndarray] = tabular_scores(raw)
    for name in [*gnn_arms(), "gnn_full_permuted"]:
        arms[name] = _gnn_scores(name)
    results = {}
    for name, scores in arms.items():
        print(f"evaluating {name} ...", flush=True)
        results[name] = evaluate_arm(raw, labels, scores, name)

    def seeds(prefix: str) -> dict[str, Any]:
        runs = [v for k, v in results.items() if k.startswith(prefix) and k[len(prefix):].isdigit()]
        pick = lambda f: [f(r) for r in runs]  # noqa: E731
        return {"n": len(runs),
                "edgeRecall": pick(lambda r: r["edge"]["recall"]), "edgePrecision": pick(lambda r: r["edge"]["precision"]),
                "averagePrecision": pick(lambda r: r["edge"]["averagePrecision"]),
                "rulesPlusModelRecall": pick(lambda r: r["accounts"]["rulesPlusModel"]["recall"]),
                "rulesPlusModelPrecision": pick(lambda r: r["accounts"]["rulesPlusModel"]["precision"])}

    prod = results["gnn_full_s42"]
    e, a = prod["edge"], prod["accounts"]["rulesPlusModel"]
    edge_negatives = int((_in_test(raw) & (raw["is_fraud"].to_numpy() == 0)).sum())
    out = {
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "dataset": "nolambur_v2 (synthetic, seed 7)",
        "protocol": "fit on days 0-5, threshold = max F1 on days 6-7, report days 8-9; GNN scores online and time-respecting",
        "arms": results,
        "seeds": {"gnn_full": seeds("gnn_full_s"), "gnn_noamt": seeds("gnn_noamt_s")},
        "baseRates": base_rates(e, a, edge_negatives, clean_accounts_active_in_test(raw, labels)),
    }
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def base_rates(e: dict[str, Any], a: dict[str, Any], edge_negatives: int, account_negatives: int) -> dict[str, Any]:
    factor = reported_factor((e["tp"] + e["fn"]) / (e["tp"] + e["fn"] + edge_negatives))
    return {
        "note": "Projection, not measurement: holds the production arm's recall and false-positive rate fixed as fraud gets rarer. "
                "Range: recall at its 95% lower bound with FPR at its upper (pessimistic), and the reverse (optimistic).",
        "caveats": [
            "The reported rate counts incidents per transaction, includes fraud that is not mule-based and probably undercounts; "
            "the anchor row is an order of magnitude, not an estimate.",
            "The false-positive rate is held constant as clean traffic scales. Real clean traffic is messier than the synthetic set, "
            "so the real rate is more likely higher than lower.",
            "The account anchor reuses the payment factor: the share of mule accounts is not the share of fraud payments.",
        ],
        "reportedUpi": {**REPORTED_UPI, "rate": REPORTED_UPI["incidents"] / REPORTED_UPI["transactions"], "factor": factor},
        "edge": base_rate_table(e["tp"], e["fn"], e["fp"], edge_negatives, "payment (model alone)", anchor=factor),
        "account": base_rate_table(a["tp"], a["fn"], a["fp"], account_negatives, "account (rules + model queue)", anchor=factor),
    }


def refresh_base_rates() -> dict[str, Any]:
    """Recompute baseRates from the counts already in the report, without re-running the arms."""
    out = json.loads(REPORT.read_text(encoding="utf-8"))
    old = out["baseRates"]
    e, a = out["arms"]["gnn_full_s42"]["edge"], out["arms"]["gnn_full_s42"]["accounts"]["rulesPlusModel"]
    out["baseRates"] = base_rates(e, a, old["edge"]["negatives"], old["account"]["negatives"])
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["scores", "report", "baserates"])
    parser.add_argument("--arm", nargs="*", help="scores: only these arms (e.g. gnn_noamt_s42), to run them in parallel")
    args = parser.parse_args(argv)
    out = compute_scores(args.arm) if args.cmd == "scores" else refresh_base_rates() if args.cmd == "baserates" else report()
    print(json.dumps(out if args.cmd == "scores" else {k: out[k] for k in ("seeds", "baseRates")}, indent=2, default=str))


if __name__ == "__main__":
    main()
