"""Calibrate rule r2.1's peer baselines from the train days (0-5) of the base data only.

No labels and no variant data: every account of a kind counts, mules included (they are a
fraction of a percent). The output is pasted into rail_engine.py's R21_* constants.

    python -m infra.calibrate_r21
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TRAIN_DAYS = 6
WARMUP_DAYS = 3  # "new payer" needs history: count fan-in only from day 3


def main() -> None:
    raw = pd.read_csv(ROOT / "nolambur_v2" / "transactions.csv")
    kinds = pd.read_csv(ROOT / "nolambur_v2" / "labels.csv").set_index("account_id")["kind"]
    ts = pd.to_datetime(raw["timestamp"])
    raw["day"] = (ts - ts.min().normalize()).dt.days
    raw = raw[(raw["day"] < TRAIN_DAYS) & (raw["channel"] == "P2P")].copy()
    raw["kind"] = raw["recv_id"].map(kinds)

    # peer baseline: each account's busiest day of P2P inflow, p95 across accounts of that kind
    daily = raw.groupby(["recv_id", "day"])["amount_inr"].sum().groupby(level=0).max()
    busiest = pd.DataFrame({"busiest": daily, "kind": daily.index.map(kinds)})
    peer = {k: float(np.percentile(g["busiest"], 95)) for k, g in busiest.groupby("kind")}

    # fan-in: distinct payers new to the account (never paid it before) per individual per day
    raw = raw.sort_values("timestamp")
    raw["new"] = ~raw.duplicated(["sender_id", "recv_id"])
    ind = raw[(raw["kind"] == "individual") & (raw["day"] >= WARMUP_DAYS) & raw["new"]]
    fanin = ind.groupby(["recv_id", "day"])["sender_id"].nunique()
    n_days = raw.loc[raw["kind"] == "individual"].groupby("recv_id")["day"].nunique().sum()
    counts = fanin.value_counts().sort_index().to_dict()
    out = {
        "peerP95BusiestDay": peer,
        "fanInNewPayersPerIndividualDay": {"histogram": {int(k): int(v) for k, v in counts.items()},
                                          "accountDaysWithP2PInflow": int(n_days),
                                          "p999": float(np.percentile(np.r_[fanin.to_numpy(), np.zeros(max(0, n_days - len(fanin)))], 99.9)),
                                          "max": int(fanin.max())},
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
