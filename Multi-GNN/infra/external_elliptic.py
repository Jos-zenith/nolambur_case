"""Elliptic: the approach on real data this project did not generate (reports/EXTERNAL_PROTOCOL.md).

    python -m infra.external_elliptic        -> reports/external_elliptic.json

Split as Weber et al. 2019: steps 1-29 fit, 30-34 pick the threshold (max illicit F1), 35-49 test.
Edges never cross time steps, so the full graph can be built once: a test step's neighbourhood holds
only that step's transactions. Unknown-label nodes stay in the graph and are never scored.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve
from torch_geometric.nn import GINConv
from torch_geometric.utils import to_undirected

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "elliptic"
OUT = ROOT / "reports" / "external_elliptic.json"
PARTIAL = ROOT / "data" / "elliptic" / "per_seed.json"  # finished seeds, so a stopped run resumes without redoing them
PROTOCOL = ROOT / "reports" / "EXTERNAL_PROTOCOL.md"
SEEDS = (1, 2, 3)
FIT, VAL, TEST = range(1, 30), range(30, 35), range(35, 50)
DARK_MARKET_STEP = 43  # Weber et al.: models fail after a dark market shut down here


def load():
    feats = pd.read_csv(DATA / "elliptic_txs_features.csv", header=None)
    classes = pd.read_csv(DATA / "elliptic_txs_classes.csv")
    edges = pd.read_csv(DATA / "elliptic_txs_edgelist.csv")
    ids = feats[0].to_numpy()
    index = pd.Series(np.arange(len(ids)), index=ids)
    step = feats[1].to_numpy()
    x_all = feats.iloc[:, 1:].to_numpy(np.float32)  # 166 features; the first is the time step (as in the paper)
    x_local = x_all[:, :94]
    lab = classes.set_index("txId").loc[ids, "class"].astype(str).to_numpy()
    y = np.where(lab == "1", 1, np.where(lab == "2", 0, -1))
    src = index.loc[edges["txId1"]].to_numpy()
    dst = index.loc[edges["txId2"]].to_numpy()
    return {"step": step, "x_all": x_all, "x_local": x_local, "y": y, "src": src, "dst": dst}


def mask(d, steps) -> np.ndarray:
    return np.isin(d["step"], list(steps)) & (d["y"] >= 0)


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(c - h, 4), round(c + h, 4)]


def scores_at(y: np.ndarray, flag: np.ndarray) -> dict:
    tp = int((flag & (y == 1)).sum())
    fp = int((flag & (y == 0)).sum())
    fn = int((~flag & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "precisionCI": wilson(tp, tp + fp), "recallCI": wilson(tp, tp + fn)}


def best_threshold(y: np.ndarray, s: np.ndarray) -> float:
    p, r, t = precision_recall_curve(y, s)
    f = np.where(p + r > 0, 2 * p * r / np.maximum(p + r, 1e-12), 0)[:-1]
    return float(t[int(np.argmax(f))])


def evaluate(d, s: np.ndarray, th: float, flag: np.ndarray | None = None) -> dict:
    te = mask(d, TEST)
    flag = (s >= th) if flag is None else flag
    out = scores_at(d["y"][te], flag[te])
    out["ap"] = round(float(average_precision_score(d["y"][te], s[te])), 4)
    out["threshold"] = round(th, 4)
    by_step = {}
    for t in TEST:
        m = (d["step"] == t) & (d["y"] >= 0)
        if (d["y"][m] == 1).any():
            by_step[t] = round(float(f1_score(d["y"][m], flag[m], zero_division=0)), 4)
    out["f1ByStep"] = by_step
    for name, steps in (("beforeDarkMarket", range(35, DARK_MARKET_STEP)), ("fromDarkMarket", range(DARK_MARKET_STEP, 50))):
        m = mask(d, steps)
        out[name] = scores_at(d["y"][m], flag[m])
    return out


def rf(x_fit, y_fit, seed: int) -> RandomForestClassifier:
    # as the paper: 50 trees, max_features 50
    return RandomForestClassifier(n_estimators=50, max_features=50, random_state=seed, n_jobs=-1).fit(x_fit, y_fit)


class GIN(torch.nn.Module):
    def __init__(self, n_in: int, hidden: int = 64, dropout: float = 0.1):
        super().__init__()
        mlp = lambda a, b: torch.nn.Sequential(torch.nn.Linear(a, b), torch.nn.ReLU(), torch.nn.Linear(b, b))
        self.c1, self.c2 = GINConv(mlp(n_in, hidden)), GINConv(mlp(hidden, hidden))
        self.n1, self.n2 = torch.nn.BatchNorm1d(hidden), torch.nn.BatchNorm1d(hidden)
        self.out = torch.nn.Linear(hidden, 2)
        self.dropout = dropout

    def embed(self, x, ei):
        h = F.relu(self.n1(self.c1(x, ei)))
        h = F.dropout(h, self.dropout, self.training)
        return F.relu(self.n2(self.c2(h, ei)))

    def forward(self, x, ei):
        return self.out(F.dropout(self.embed(x, ei), self.dropout, self.training))


def train_gin(d, seed: int, illicit_weight: float, epochs: int = 300, patience: int = 40):
    torch.manual_seed(seed)
    np.random.seed(seed)
    x = d["x_local"]
    mu, sd = x[mask(d, FIT)].mean(0), x[mask(d, FIT)].std(0) + 1e-6  # normalise with the fitting steps only
    xt = torch.from_numpy((x - mu) / sd)
    ei = to_undirected(torch.from_numpy(np.stack([d["src"], d["dst"]])).long())
    y = torch.from_numpy(d["y"]).long()
    fit, val = torch.from_numpy(mask(d, FIT)), torch.from_numpy(mask(d, VAL))
    model = GIN(xt.shape[1])
    opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    w = torch.tensor([1.0, illicit_weight])
    best, best_state, since = -1.0, None, 0
    for _ in range(epochs):
        model.train()
        opt.zero_grad()
        loss = F.cross_entropy(model(xt, ei)[fit], y[fit], weight=w)
        loss.backward()
        opt.step()
        model.eval()
        with torch.no_grad():
            s = torch.softmax(model(xt, ei), 1)[:, 1].numpy()
        vy, vs = d["y"][mask(d, VAL)], s[mask(d, VAL)]
        f = f1_score(vy, vs >= best_threshold(vy, vs))  # model selection on the validation steps only
        if f > best:
            best, best_state, since = f, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            since += 1
            if since >= patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        s = torch.softmax(model(xt, ei), 1)[:, 1].numpy()
        emb = model.embed(xt, ei).numpy()
    return s, emb, best


def hop_flags(d, s: np.ndarray, th: float) -> np.ndarray:
    """hop_from_flagged: a transaction paid by a transaction the model flagged. One hop, direction kept."""
    hit = np.zeros(len(s), dtype=bool)
    flagged_src = s[d["src"]] >= th
    hit[d["dst"][flagged_src]] = True
    return hit


def run() -> dict:
    t0 = time.time()
    d = load()
    fit, val = mask(d, FIT), mask(d, VAL)
    counts = {"nodes": int(len(d["y"])), "edges": int(len(d["src"])), "illicit": int((d["y"] == 1).sum()), "licit": int((d["y"] == 0).sum()),
              "unknown": int((d["y"] == -1).sum()), "testIllicit": int(((d["y"] == 1) & mask(d, TEST)).sum()), "testLabelled": int(mask(d, TEST).sum())}

    # replication of the paper's own setup: RF fit on steps 1-34, threshold 0.5 (Weber: LF 0.694, AF 0.788)
    paper = mask(d, range(1, 35))
    replication = {}
    for name, x in (("RF-LF", d["x_local"]), ("RF-AF", d["x_all"])):
        s = rf(x[paper], d["y"][paper], 1).predict_proba(x)[:, 1]
        replication[name] = {k: v for k, v in evaluate(d, s, 0.5).items() if k in ("precision", "recall", "f1")}

    per_seed = json.loads(PARTIAL.read_text()) if PARTIAL.exists() else []
    for seed in SEEDS:
        if any(r["seed"] == seed for r in per_seed):
            continue
        row = {"seed": seed}
        for name, x in (("RF-LF", d["x_local"]), ("RF-AF", d["x_all"])):
            s = rf(x[fit], d["y"][fit], seed).predict_proba(x)[:, 1]
            row[name] = evaluate(d, s, best_threshold(d["y"][val], s[val]))
        # illicit class weight picked on the validation steps
        tried = {}
        for wgt in (1.0, 3.0, 10.0):
            s, emb, vf1 = train_gin(d, seed, wgt)
            tried[wgt] = (vf1, s, emb)
        wgt = max(tried, key=lambda k: tried[k][0])
        _, s_gin, emb = tried[wgt]
        th = best_threshold(d["y"][val], s_gin[val])
        row["GIN"] = evaluate(d, s_gin, th) | {"illicitWeight": wgt}
        hop = hop_flags(d, s_gin, th)
        row["GIN+hop"] = evaluate(d, s_gin, th, flag=(s_gin >= th) | hop)
        row["hopOnly"] = scores_at(d["y"][mask(d, TEST)], (hop & ~(s_gin >= th))[mask(d, TEST)])
        xe = np.hstack([d["x_local"], emb])
        s = rf(xe[fit], d["y"][fit], seed).predict_proba(xe)[:, 1]
        row["RF-LF+GIN"] = evaluate(d, s, best_threshold(d["y"][val], s[val]))
        per_seed.append(row)
        PARTIAL.write_text(json.dumps(per_seed, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        print(f"seed {seed}: " + ", ".join(f"{k} F1 {row[k]['f1']}" for k in ("RF-LF", "RF-AF", "GIN", "GIN+hop", "RF-LF+GIN")), flush=True)

    mean = lambda m, k: round(float(np.mean([r[m][k] for r in per_seed])), 4)
    gin_f1, rf_f1, rfg_f1 = mean("GIN", "f1"), mean("RF-LF", "f1"), mean("RF-LF+GIN", "f1")
    marks = {
        "E1": {"claim": "GIN F1 >= 0.628 (Weber GCN)", "value": gin_f1, "pass": gin_f1 >= 0.628},
        "E2": {"claim": "RF-LF+GIN F1 >= RF-LF F1 + 0.02, higher in all 3 seeds", "value": round(rfg_f1 - rf_f1, 4),
               "pass": rfg_f1 >= rf_f1 + 0.02 and all(r["RF-LF+GIN"]["f1"] > r["RF-LF"]["f1"] for r in per_seed)},
        "E3": {"claim": "GIN+hop recall >= GIN recall + 0.05 with precision >= 0.50",
               "value": {"recallGain": round(mean("GIN+hop", "recall") - mean("GIN", "recall"), 4), "precision": mean("GIN+hop", "precision")},
               "pass": mean("GIN+hop", "recall") >= mean("GIN", "recall") + 0.05 and mean("GIN+hop", "precision") >= 0.50},
    }
    import hashlib
    return {
        "protocol": {"file": "reports/EXTERNAL_PROTOCOL.md", "sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()},
        "dataset": counts,
        "split": {"fit": [1, 29], "threshold": [30, 34], "test": [35, 49]},
        "replicationOfPaper": {"setup": "RF fit on steps 1-34, threshold 0.5", "ours": replication, "weber": {"RF-LF": 0.694, "RF-AF": 0.788}},
        "meanF1": {m: mean(m, "f1") for m in ("RF-LF", "RF-AF", "GIN", "GIN+hop", "RF-LF+GIN")},
        "marks": marks,
        "perSeed": per_seed,
        "seconds": round(time.time() - t0, 1),
    }


if __name__ == "__main__":
    result = run()
    OUT.write_text(json.dumps(result, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    print(json.dumps({"meanF1": result["meanF1"], "marks": result["marks"], "replication": result["replicationOfPaper"]}, indent=1))
