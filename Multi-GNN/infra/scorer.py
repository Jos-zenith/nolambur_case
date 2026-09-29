"""Incremental GNN scoring: a rolling temporal graph, and exact 2-hop subgraph inference.

The bridge used to score every live batch by splicing it onto the whole background graph
and running the model over all ~30-80k edges. That costs the same for one payment as for
thousands, and it lets a score see edges that arrive later.

GINe (models.py) with n_gnn_layers=2 and no reverse message passing classifies edge u->v
from the layer-2 embeddings of u and v plus the edge's own features. A node's layer-2
embedding depends only on its in-edges, and on the in-edges of the nodes those come from.
So an edge's score needs:

    E0 = {u, v}; the in-edges of E0; N1 = the sources of those edges; the in-edges of N1.

That is quadratic in degree: a payment to a merchant pulls in all its recent customers
and everyone who paid them. mode="cached" makes it linear. Every refresh_seconds of event
time, one pass computes every node's layer-1 embedding (x1). A payment then needs only
the 1-hop in-edges of u and v: their own x1 is computed fresh (including this batch), and
their in-neighbours' x1 comes from the cache, up to refresh_seconds stale. Nodes created
since the last refresh are computed fresh too. `python -m infra.scorer compare` measures
what the staleness costs against exact scoring.

OnlineScorer keeps the graph (inside a rolling window) with per-node in-edge lists, and
for a micro-batch of new payments it runs the model on exactly that subgraph. Eval-mode
BatchNorm and dropout are per-node or off, so this reproduces the full-graph forward pass
to float precision: `python -m infra.scorer verify` measures that. A score uses only edges
already in the graph, so replayed or live scores never see the future.

Inputs are built as the model was trained: the node feature is the z-normalised constant
(0, not 1: z_norm of a column of ones is 0), and the edge features are those listed in the
checkpoint's .norm.json, normalised with the training split's mean and std.

    python -m infra.scorer verify     --dataset v2 [--edges 2000]
    python -m infra.scorer precompute --dataset v2          # time-respecting scores for the replay
    python -m infra.scorer bench      --dataset v2          # latency per micro-batch size
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import torch.nn.functional as F
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import GINe  # noqa: E402

DATASETS = {
    "v1": {"dir": ROOT / "nolambur", "raw": ROOT / "nolambur_transactions.csv", "labels": ROOT / "nolambur_labels.csv", "checkpoint": ROOT / "models" / "local_finetuned_gin_nolambur.pt"},
    "v2": {"dir": ROOT / "nolambur_v2", "raw": ROOT / "nolambur_v2" / "transactions.csv", "labels": ROOT / "nolambur_v2" / "labels.csv", "checkpoint": ROOT / "models" / "local_finetuned_gin_nolambur_v2.pt"},
}
WINDOW_SECONDS = 72 * 3600


def load_gin(checkpoint: Path) -> tuple[torch.nn.Module, dict[str, Any]]:
    """GINe with the checkpoint's weights and its normalisation sidecar."""
    norm = json.loads(checkpoint.with_suffix(".norm.json").read_text(encoding="utf-8"))
    params = json.loads((ROOT / "model_settings.json").read_text(encoding="utf-8"))["gin"]["params"]
    model = GINe(
        num_features=1, num_gnn_layers=int(round(params["n_gnn_layers"])), n_classes=2,
        n_hidden=int(round(params["n_hidden"])), edge_updates=False, edge_dim=len(norm["edge_features"]),
        dropout=float(params["dropout"]), final_dropout=float(params["final_dropout"]),
    )
    state = torch.load(checkpoint, map_location="cpu")
    model.load_state_dict(state.get("model_state_dict", state) if isinstance(state, dict) else state)
    model.eval()
    return model, norm


def edge_features(names: list[str], seconds_of_day: np.ndarray, amount: np.ndarray, p2m: np.ndarray, timestamp: np.ndarray) -> np.ndarray:
    """Raw feature columns, by name, exactly as data_loading.add_derived_edge_features builds them.
    seconds_of_day follows prepare_datasets.py's clock (seconds since midnight + 10)."""
    cols = {
        "HourOfDay": (seconds_of_day % 86400) / 3600.0,
        "LogAmount": np.log1p(amount.astype(np.float64)),
        "Amount Received": amount.astype(np.float64),
        "Payment Format": p2m.astype(np.float64),
        "Received Currency": np.zeros(len(amount)),
        "Timestamp": timestamp.astype(np.float64),
    }
    return np.stack([cols[n] for n in names], axis=1).astype(np.float32)


@dataclass
class Batch:
    ids: np.ndarray  # edge ids that were scored
    probs: np.ndarray
    subgraph_nodes: int
    subgraph_edges: int
    ms: float


class OnlineScorer:
    """A rolling temporal graph with exact 2-hop scoring. Not thread-safe: one owner."""

    def __init__(self, model: torch.nn.Module, norm: dict[str, Any], window_seconds: float = WINDOW_SECONDS, max_fanin: int | None = None,
                 mode: str = "exact", refresh_seconds: float = 300.0) -> None:
        self.model = model
        self.mode = mode  # exact | cached
        self.refresh_seconds = refresh_seconds
        self.x1: torch.Tensor | None = None  # cached layer-1 embeddings (mode="cached")
        self.cache_nodes = 0
        self.cache_t = -math.inf
        self.refreshes = 0
        self.last_refresh_ms: float | None = None
        self.feature_names: list[str] = norm["edge_features"]
        self.mean = np.asarray(norm["edge_attr_mean"], dtype=np.float32)
        std = np.asarray(norm["edge_attr_std"], dtype=np.float32)
        self.std = np.where(std == 0, 1.0, std).astype(np.float32)
        self.window = window_seconds
        self.max_fanin = max_fanin  # cap per node (most recent); None = exact
        self.node_of: dict[str, int] = {}
        self.in_edges: list[list[int]] = []
        cap = 1024
        self.src = np.zeros(cap, np.int64)
        self.dst = np.zeros(cap, np.int64)
        self.t = np.zeros(cap, np.float64)
        self.feat = np.zeros((cap, len(self.feature_names)), np.float32)
        self.n = 0
        self.now = -math.inf
        self.capped = 0  # subgraph builds that hit max_fanin (scores approximate)
        self.pruned = 0

    # -------------------------------------------------------------- graph

    def _node(self, account: str) -> int:
        i = self.node_of.get(account)
        if i is None:
            i = self.node_of[account] = len(self.in_edges)
            self.in_edges.append([])
        return i

    def _grow(self, need: int) -> None:
        cap = len(self.src)
        if need <= cap:
            return
        new = max(need, cap * 2)
        self.src = np.resize(self.src, new)
        self.dst = np.resize(self.dst, new)
        self.t = np.resize(self.t, new)
        feat = np.zeros((new, self.feat.shape[1]), np.float32)
        feat[: self.n] = self.feat[: self.n]
        self.feat = feat

    def add(self, src: Iterable[str], dst: Iterable[str], t: np.ndarray, raw_features: np.ndarray) -> np.ndarray:
        """Append edges (account ids, epoch seconds, raw feature rows); returns their edge ids."""
        src, dst = list(src), list(dst)
        k = len(src)
        self._grow(self.n + k)
        ids = np.arange(self.n, self.n + k)
        self.src[ids] = [self._node(a) for a in src]
        self.dst[ids] = [self._node(b) for b in dst]
        self.t[ids] = t
        self.feat[ids] = (raw_features - self.mean) / self.std
        for e, v in zip(ids.tolist(), self.dst[ids].tolist()):
            self.in_edges[v].append(e)
        self.n += k
        self.now = max(self.now, float(np.max(t)) if k else self.now)
        return ids

    def _incoming(self, nodes: np.ndarray, cutoff: float) -> np.ndarray:
        lists = []
        for v in nodes.tolist():
            lst = self.in_edges[v]
            # edges arrive in time order, so expired ones sit at the front: drop them for good
            drop = 0
            while drop < len(lst) and self.t[lst[drop]] < cutoff:
                drop += 1
            if drop:
                del lst[:drop]
                self.pruned += drop
            if self.max_fanin is not None and len(lst) > self.max_fanin:
                self.capped += 1
                lists.append(lst[-self.max_fanin:])
            else:
                lists.append(lst)
        return np.fromiter((e for lst in lists for e in lst), dtype=np.int64) if lists else np.zeros(0, np.int64)

    # -------------------------------------------------------------- scoring

    @torch.no_grad()
    def score(self, ids: np.ndarray) -> Batch:
        started = time.perf_counter()
        cutoff = self.now - self.window
        e0 = np.unique(np.concatenate([self.src[ids], self.dst[ids]]))
        in0 = self._incoming(e0, cutoff)
        n1 = np.unique(self.src[in0])
        in1 = self._incoming(n1, cutoff)
        edges = np.unique(np.concatenate([in0, in1, ids]))
        nodes = np.unique(np.concatenate([self.src[edges], self.dst[edges]]))
        local = np.stack([np.searchsorted(nodes, self.src[edges]), np.searchsorted(nodes, self.dst[edges])])
        x = torch.zeros((len(nodes), 1), dtype=torch.float32)  # z_norm of the all-ones node feature
        logits = self.model(x, torch.from_numpy(local), torch.from_numpy(self.feat[edges]))
        probs = torch.softmax(logits, dim=-1)[:, 1].numpy()
        pos = np.searchsorted(edges, ids)
        return Batch(ids=ids, probs=probs[pos].astype(np.float64), subgraph_nodes=len(nodes), subgraph_edges=len(edges), ms=(time.perf_counter() - started) * 1000)

    @torch.no_grad()
    def refresh_cache(self) -> None:
        """Layer-1 embeddings for every node, over the edges in the window."""
        started = time.perf_counter()
        m = self.model
        cutoff = self.now - self.window
        alive = np.flatnonzero(self.t[: self.n] >= cutoff)
        n_nodes = len(self.in_edges)
        x0 = m.node_emb(torch.zeros((n_nodes, 1)))
        ei = torch.from_numpy(np.stack([self.src[alive], self.dst[alive]]))
        ea = m.edge_emb(torch.from_numpy(self.feat[alive]))
        self.x1 = (x0 + F.relu(m.batch_norms[0](m.convs[0](x0, ei, ea)))) / 2
        self.cache_nodes, self.cache_t = n_nodes, self.now
        self.refreshes += 1
        self.last_refresh_ms = (time.perf_counter() - started) * 1000

    @torch.no_grad()
    def score_cached(self, ids: np.ndarray) -> Batch:
        started = time.perf_counter()
        m = self.model
        cutoff = self.now - self.window
        e0 = np.unique(np.concatenate([self.src[ids], self.dst[ids]]))
        in0 = self._incoming(e0, cutoff)  # includes the batch's own edges
        sources = np.unique(self.src[in0])
        fresh = np.unique(np.concatenate([e0, sources[sources >= self.cache_nodes]]))  # endpoints, and nodes newer than the cache
        in_f = self._incoming(fresh, cutoff)
        # layer 1, fresh: x0 is the same constant for every node
        nodes1 = np.unique(np.concatenate([fresh, self.src[in_f]]))
        x0 = m.node_emb(torch.zeros((len(nodes1), 1)))
        ei1 = torch.from_numpy(np.stack([np.searchsorted(nodes1, self.src[in_f]), np.searchsorted(nodes1, self.dst[in_f])]))
        x1_local = (x0 + F.relu(m.batch_norms[0](m.convs[0](x0, ei1, m.edge_emb(torch.from_numpy(self.feat[in_f])))))) / 2
        x1_fresh = x1_local[torch.from_numpy(np.searchsorted(nodes1, fresh))]
        # layer 2 for the endpoints, over their in-edges; neighbours' x1 from the cache
        nodes2 = np.unique(np.concatenate([e0, self.src[in0]]))
        x1 = torch.zeros((len(nodes2), x1_fresh.shape[1]))
        cached = nodes2 < self.cache_nodes
        if cached.any():
            x1[torch.from_numpy(cached)] = self.x1[torch.from_numpy(nodes2[cached])]
        pos = np.searchsorted(nodes2, fresh)
        ok = (pos < len(nodes2)) & (nodes2[np.minimum(pos, len(nodes2) - 1)] == fresh)
        x1[torch.from_numpy(pos[ok])] = x1_fresh[torch.from_numpy(np.flatnonzero(ok))]
        ei2 = torch.from_numpy(np.stack([np.searchsorted(nodes2, self.src[in0]), np.searchsorted(nodes2, self.dst[in0])]))
        x2 = (x1 + F.relu(m.batch_norms[1](m.convs[1](x1, ei2, m.edge_emb(torch.from_numpy(self.feat[in0])))))) / 2
        u = torch.from_numpy(np.searchsorted(nodes2, self.src[ids]))
        v = torch.from_numpy(np.searchsorted(nodes2, self.dst[ids]))
        h = torch.cat([x2[u].relu(), x2[v].relu(), m.edge_emb(torch.from_numpy(self.feat[ids]))], 1)
        probs = torch.softmax(m.mlp(h), dim=-1)[:, 1].numpy()
        return Batch(ids=ids, probs=probs.astype(np.float64), subgraph_nodes=len(nodes1) + len(nodes2), subgraph_edges=len(in0) + len(in_f), ms=(time.perf_counter() - started) * 1000)

    def ingest(self, src: list[str], dst: list[str], t: np.ndarray, raw_features: np.ndarray) -> Batch:
        ids = self.add(src, dst, t, raw_features)
        if self.mode != "cached":
            return self.score(ids)
        if self.x1 is None or self.now - self.cache_t >= self.refresh_seconds:
            self.refresh_cache()
        return self.score_cached(ids)

    def describe(self) -> dict[str, Any]:
        cutoff = self.now - self.window
        live = int(np.count_nonzero(self.t[: self.n] >= cutoff)) if self.n else 0
        return {"edges": self.n, "edgesInWindow": live, "nodes": len(self.in_edges), "windowHours": self.window / 3600, "maxFanin": self.max_fanin,
                "cappedBuilds": self.capped, "exact": self.max_fanin is None and self.mode == "exact", "features": self.feature_names,
                "scoringMode": self.mode, "refreshSeconds": self.refresh_seconds if self.mode == "cached" else None,
                "cacheRefreshes": self.refreshes, "lastRefreshMs": round(self.last_refresh_ms, 1) if self.last_refresh_ms else None}


# ---------------------------------------------------------------------- dataset helpers


def load_dataset(name: str):
    """The raw rows in formatted order (the order the model was trained on) plus features."""
    import pandas as pd

    spec = DATASETS[name]
    formatted = pd.read_csv(spec["dir"] / "formatted_transactions.csv")
    raw = pd.read_csv(spec["raw"])
    if len(formatted) != len(raw):
        raise RuntimeError(f"{name}: formatted and raw row counts differ")
    order = np.argsort(formatted["Timestamp"].to_numpy(), kind="mergesort")  # data_loading sorts the same way
    formatted, raw = formatted.iloc[order].reset_index(drop=True), raw.iloc[order].reset_index(drop=True)
    # resolution-independent (pandas 3 parses these at 1 s resolution, older pandas at 1 ns)
    epoch = ((pd.to_datetime(raw["timestamp"]) - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)
    return raw, formatted, epoch


def raw_features_for(names: list[str], formatted) -> np.ndarray:
    return edge_features(
        names,
        seconds_of_day=formatted["Timestamp"].to_numpy(),
        amount=formatted["Amount Received"].to_numpy(),
        p2m=formatted["Payment Format"].to_numpy(),
        timestamp=formatted["Timestamp"].to_numpy() - formatted["Timestamp"].min(),
    )


def payment_features(names: list[str], payments: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Epoch seconds and raw feature rows for live Payment dicts (infra/ingest.py)."""
    ts = [datetime.fromisoformat(p["timestamp"]) if p.get("timestamp") else datetime.utcnow() for p in payments]
    epoch = np.array([(t - datetime(1970, 1, 1)).total_seconds() for t in ts])
    sod = np.array([t.hour * 3600 + t.minute * 60 + t.second + 10 for t in ts], dtype=np.float64)
    amount = np.array([float(p["amount_inr"]) for p in payments])
    p2m = np.array([1.0 if p.get("channel") == "P2M" else 0.0 for p in payments])
    return epoch, edge_features(names, sod, amount, p2m, epoch - epoch.min())


def checkpoint_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ---------------------------------------------------------------------- commands


def compare(name: str, refresh: float) -> dict[str, Any]:
    """Cached (x1 refreshed every `refresh` seconds) vs exact time-respecting scores, same batches."""
    raw, formatted, epoch = load_dataset(name)
    model, norm = load_gin(DATASETS[name]["checkpoint"])
    feats = raw_features_for(norm["edge_features"], formatted)
    src, dst = raw["sender_id"].astype(str).tolist(), raw["recv_id"].astype(str).tolist()
    exact = OnlineScorer(model, norm)
    cached = OnlineScorer(model, norm, mode="cached", refresh_seconds=refresh)
    buckets = np.floor(epoch / 5.0)
    bounds = np.flatnonzero(np.diff(buckets)) + 1
    a_all, b_all, ms_e, ms_c = np.zeros(len(raw)), np.zeros(len(raw)), [], []
    for a, b in zip(np.r_[0, bounds], np.r_[bounds, len(raw)]):
        be = exact.ingest(src[a:b], dst[a:b], epoch[a:b], feats[a:b])
        bc = cached.ingest(src[a:b], dst[a:b], epoch[a:b], feats[a:b])
        a_all[a:b], b_all[a:b] = be.probs, bc.probs
        ms_e.append(be.ms)
        ms_c.append(bc.ms)
    d = np.abs(a_all - b_all)
    y = raw["is_fraud"].to_numpy()
    th = 0.5
    return {"dataset": name, "refreshSeconds": refresh, "edges": len(raw), "maxAbsDiff": float(d.max()), "meanAbsDiff": float(d.mean()),
            "p99AbsDiff": float(np.percentile(d, 99)), "fraudMeanAbsDiff": float(d[y == 1].mean()),
            "labelFlipsAt0_5": int(((a_all >= th) != (b_all >= th)).sum()),
            "exactMsP50": round(float(np.percentile(ms_e, 50)), 2), "cachedMsP50": round(float(np.percentile(ms_c, 50)), 2),
            "exactMsP99": round(float(np.percentile(ms_e, 99)), 2), "cachedMsP99": round(float(np.percentile(ms_c, 99)), 2),
            "cacheRefreshes": cached.refreshes, "lastRefreshMs": cached.last_refresh_ms}


def verify(name: str, sample: int) -> dict[str, Any]:
    """Full-graph forward pass vs. 2-hop subgraph scoring on the same (complete) graph."""
    raw, formatted, epoch = load_dataset(name)
    model, norm = load_gin(DATASETS[name]["checkpoint"])
    feats = raw_features_for(norm["edge_features"], formatted)
    scorer = OnlineScorer(model, norm, window_seconds=math.inf)
    ids = scorer.add(raw["sender_id"].astype(str), raw["recv_id"].astype(str), epoch, feats)
    started = time.perf_counter()
    with torch.no_grad():
        full = torch.softmax(model(torch.zeros((len(scorer.in_edges), 1)), torch.from_numpy(np.stack([scorer.src[: scorer.n], scorer.dst[: scorer.n]])), torch.from_numpy(scorer.feat[: scorer.n])), -1)[:, 1].numpy()
    full_ms = (time.perf_counter() - started) * 1000
    rng = np.random.default_rng(0)
    pick = np.sort(rng.choice(ids, min(sample, len(ids)), replace=False))
    diffs, times = [], []
    for chunk in np.array_split(pick, max(1, len(pick) // 50)):
        b = scorer.score(chunk)
        diffs.append(np.abs(b.probs - full[chunk]))
        times.append(b.ms)
    d = np.concatenate(diffs)
    return {"dataset": name, "edgesChecked": int(len(pick)), "maxAbsDiff": float(d.max()), "meanAbsDiff": float(d.mean()), "fullGraphMs": round(full_ms, 1),
            "fullGraphEdges": int(scorer.n), "subgraphMsPer50": round(statistics.median(times), 2)}


def precompute(name: str, bucket_seconds: float = 5.0) -> dict[str, Any]:
    """Score every edge in time order using only edges up to its own 5-second bucket."""
    raw, formatted, epoch = load_dataset(name)
    ckpt = DATASETS[name]["checkpoint"]
    model, norm = load_gin(ckpt)
    feats = raw_features_for(norm["edge_features"], formatted)
    src, dst = raw["sender_id"].astype(str).tolist(), raw["recv_id"].astype(str).tolist()
    scorer = OnlineScorer(model, norm)
    out = np.zeros(len(raw))
    buckets = np.floor(epoch / bucket_seconds)
    bounds = np.flatnonzero(np.diff(buckets)) + 1
    starts, ends = np.r_[0, bounds], np.r_[bounds, len(raw)]
    latencies = []
    started = time.perf_counter()
    for a, b in zip(starts, ends):
        batch = scorer.ingest(src[a:b], dst[a:b], epoch[a:b], feats[a:b])
        out[a:b] = batch.probs
        latencies.append(batch.ms)
    wall = time.perf_counter() - started
    # stored in the raw CSV's row order, which the engine uses
    order = np.argsort(np.argsort(pd_order(name)))
    scores_raw_order = out[order]
    target = DATASETS[name]["dir"] / "online_scores.npy"
    np.save(target, scores_raw_order)
    meta = {"dataset": name, "checkpoint": ckpt.name, "checkpointSha": checkpoint_sha(ckpt), "bucketSeconds": bucket_seconds, "windowHours": WINDOW_SECONDS / 3600,
            "edges": int(len(raw)), "batches": int(len(starts)), "wallSeconds": round(wall, 1), "p50Ms": round(float(np.percentile(latencies, 50)), 2),
            "p99Ms": round(float(np.percentile(latencies, 99)), 2), "features": norm["edge_features"], "createdAt": datetime.now().isoformat(timespec="seconds")}
    target.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def pd_order(name: str) -> np.ndarray:
    """Row order load_dataset applies (formatted Timestamp, stable)."""
    import pandas as pd

    ts = pd.read_csv(DATASETS[name]["dir"] / "formatted_transactions.csv", usecols=["Timestamp"])["Timestamp"].to_numpy()
    return np.argsort(ts, kind="mergesort")


def bench(name: str) -> dict[str, Any]:
    """Warm graph (all but the last 2,000 edges), then score the rest in micro-batches."""
    raw, formatted, epoch = load_dataset(name)
    model, norm = load_gin(DATASETS[name]["checkpoint"])
    feats = raw_features_for(norm["edge_features"], formatted)
    src, dst = raw["sender_id"].astype(str).tolist(), raw["recv_id"].astype(str).tolist()
    warm = len(raw) - 2000
    scorer = OnlineScorer(model, norm)
    scorer.add(src[:warm], dst[:warm], epoch[:warm], feats[:warm])
    results = []
    for size in (1, 10, 100, 500, 1000):
        s = OnlineScorer(model, norm)
        s.add(src[:warm], dst[:warm], epoch[:warm], feats[:warm])
        ms, sub = [], []
        for a in range(warm, len(raw) - size + 1, size):
            b = s.ingest(src[a : a + size], dst[a : a + size], epoch[a : a + size], feats[a : a + size])
            ms.append(b.ms)
            sub.append(b.subgraph_edges)
            if len(ms) >= 200:
                break
        results.append({"batch": size, "batches": len(ms), "p50Ms": round(float(np.percentile(ms, 50)), 2), "p99Ms": round(float(np.percentile(ms, 99)), 2),
                        "edgesPerSecond": round(size / (statistics.mean(ms) / 1000)), "medianSubgraphEdges": int(statistics.median(sub))})
    return {"dataset": name, "warmEdges": warm, "torchThreads": torch.get_num_threads(), "results": results}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["verify", "precompute", "bench", "compare"])
    parser.add_argument("--refresh", type=float, default=300.0, help="compare: cache refresh interval, event-time seconds")
    parser.add_argument("--dataset", choices=list(DATASETS), default="v2")
    parser.add_argument("--edges", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.cmd == "verify":
        out = verify(args.dataset, args.edges)
    elif args.cmd == "compare":
        out = compare(args.dataset, args.refresh)
    elif args.cmd == "precompute":
        out = precompute(args.dataset)
    else:
        out = bench(args.dataset)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
