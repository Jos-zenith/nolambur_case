"""Load test: how many payments per second the rail can score and run rules on, and how long each waits.

Two modes, both on the v2 accounts (payments are resampled from nolambur_v2/transactions.csv
with fresh txn_ids, so the graph has real hubs, repeat payers and mule structure):

  engine  In process: micro-batches go through the same path as RailService._tick
          (OnlineScorer.ingest, then RailEngine.ingest_live with the r2.0 rules and the router).
          Measures processing capacity with no network or queue.

  http    Against a running bridge (RAIL_SOURCE=webhook): an aiohttp client POSTs batches to
          /rail/ingest/payments at the target rate while /rail/platform is polled. Measures the
          HTTP response time and end-to-end lag (sent -> ingested by the engine).

    python -m infra.loadtest engine --tps 1000 2000 5000 --seconds 20
    python -m infra.loadtest http   --tps 1000 2000 --seconds 30 --url http://127.0.0.1:8011

Results go to stdout and to reports/loadtest.json (engine) / reports/loadtest_http.json; the bridge serves them at /rail/loadtest.
A laptop is not production hardware: the report names the CPU it ran on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TICK = 0.5  # RailService's tick


def hardware() -> dict[str, Any]:
    info: dict[str, Any] = {"python": platform.python_version(), "os": platform.platform(), "logicalCpus": os.cpu_count()}
    try:
        import subprocess

        name = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"], capture_output=True, text=True, timeout=10).stdout.strip()
        info["cpu"] = name or platform.processor()
    except Exception:
        info["cpu"] = platform.processor()
    try:
        import psutil

        info["ramGb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    try:
        import torch

        info["torchThreads"] = torch.get_num_threads()
    except Exception:
        pass
    return info


class PaymentFactory:
    """Resamples real v2 edges (payer, payee, amount, channel) with new ids and a moving clock."""

    def __init__(self, seed: int = 0, shards: int = 1) -> None:
        import pandas as pd

        self.shards = shards
        raw = pd.read_csv(ROOT / "nolambur_v2" / "transactions.csv")
        self.rows = raw[["sender_vpa", "sender_id", "recv_vpa", "recv_id", "amount_inr", "channel", "sender_state", "recv_state"]].to_dict("records")
        self.rng = np.random.default_rng(seed)
        self.clock = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    def batch(self, n: int, seconds: float) -> list[dict[str, Any]]:
        picks = self.rng.integers(0, len(self.rows), n)
        out = []
        shard = self.rng.integers(0, self.shards, n)
        for k, i in enumerate(picks):
            r = self.rows[int(i)]
            ts = self.clock + timedelta(seconds=seconds * k / max(n, 1))
            tag = f"#{shard[k]}" if self.shards > 1 else ""  # a copy of the v2 account space
            out.append({
                "txn_id": uuid.uuid4().hex[:20], "payer_vpa": r["sender_vpa"] + tag, "payee_vpa": r["recv_vpa"] + tag,
                "payer_account_id": r["sender_id"] + tag, "payee_account_id": r["recv_id"] + tag, "amount_inr": float(r["amount_inr"]),
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "payer_state": r["sender_state"], "payee_state": r["recv_state"], "channel": r["channel"],
            })
        self.clock += timedelta(seconds=seconds)
        return out


# ---------------------------------------------------------------------- engine mode


def seed_history(scorer, shards: int) -> int:
    """The last 72 h of v2, once per account-space copy, ending just before now: real
    neighbourhoods for the payments under test to land in."""
    import pandas as pd

    from infra import scorer as online

    raw = pd.read_csv(ROOT / "nolambur_v2" / "transactions.csv")
    t = ((pd.to_datetime(raw["timestamp"]) - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)
    keep = t >= t.max() - online.WINDOW_SECONDS
    raw, t = raw[keep], t[keep]
    now = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds()
    t = t - t.max() + now - 1
    feats = online.edge_features(scorer.feature_names, (t % 86400) + 10, raw["amount_inr"].to_numpy(), (raw["channel"] == "P2M").to_numpy(), t - t.min())
    for k in range(shards):
        tag = f"#{k}" if shards > 1 else ""
        scorer.add((raw["sender_id"] + tag).tolist(), (raw["recv_id"] + tag).tolist(), t, feats)
    return int(keep.sum()) * shards


def engine_run(tps: int, seconds: float, warm_seconds: float = 10.0, shards: int = 1, scoring: str = "exact", refresh: float = 300.0) -> dict[str, Any]:
    import pandas as pd

    import rail_engine
    from infra import scorer as online

    spec = online.DATASETS["v2"]
    raw = pd.read_csv(spec["raw"]).head(2)  # the engine needs a Dataset; live mode never replays it
    labels = pd.read_csv(spec["labels"])
    data = rail_engine.Dataset(raw, np.zeros(len(raw)), labels, {"version": "loadtest"})
    engine = rail_engine.RailEngine(data, record_actions=False, source="webhook", auto_hold=True, model_threshold=0.9)
    model, norm = online.load_gin(spec["checkpoint"])
    scorer = online.OnlineScorer(model, norm, mode=scoring, refresh_seconds=refresh)
    seeded = seed_history(scorer, shards) if shards > 1 else 0
    if scoring == "cached":
        scorer.refresh_cache()
    factory = PaymentFactory(shards=shards)

    def tick(payments: list[dict[str, Any]]) -> tuple[float, float, int]:
        t0 = time.perf_counter()
        epoch, feats = online.payment_features(scorer.feature_names, payments)
        b = scorer.ingest([p["payer_account_id"] for p in payments], [p["payee_account_id"] for p in payments], epoch, feats)
        t1 = time.perf_counter()
        engine.ingest_live(payments, [float(x) for x in b.probs], "loadtest")
        engine.drain_events()
        return (t1 - t0) * 1000, (time.perf_counter() - t1) * 1000, b.subgraph_edges

    per_tick = max(1, int(tps * TICK))
    for _ in range(int(warm_seconds / TICK)):  # fill the graph and the rules' windows first
        tick(factory.batch(per_tick, TICK))
    score_ms, rules_ms, sub = [], [], []
    started = time.perf_counter()
    for _ in range(int(seconds / TICK)):
        a, b, c = tick(factory.batch(per_tick, TICK))
        score_ms.append(a)
        rules_ms.append(b)
        sub.append(c)
    wall = time.perf_counter() - started
    total = [a + b for a, b in zip(score_ms, rules_ms)]
    processed = per_tick * len(total)
    # a payment waits on average half a tick for the batch, then the batch's processing time
    latency = [TICK * 500 + t for t in total]
    return {
        "targetTps": tps, "scoring": scoring, "refreshSeconds": refresh if scoring == "cached" else None,
        "cacheRefreshes": scorer.refreshes, "lastRefreshMs": round(scorer.last_refresh_ms, 1) if scorer.last_refresh_ms else None, "shards": shards, "accounts": len(scorer.node_of), "seededEdges": seeded, "batchPerTick": per_tick, "ticks": len(total), "graphEdges": scorer.n,
        "sustainedTps": round(processed / wall), "keepsUp": statistics.mean(total) < TICK * 1000,
        "p99WithinTick": float(np.percentile(total, 99)) < TICK * 1000,
        "tickMs": {"p50": round(float(np.percentile(total, 50)), 1), "p99": round(float(np.percentile(total, 99)), 1), "max": round(max(total), 1)},
        "scoreMs": {"p50": round(float(np.percentile(score_ms, 50)), 1), "p99": round(float(np.percentile(score_ms, 99)), 1)},
        "rulesMs": {"p50": round(float(np.percentile(rules_ms, 50)), 1), "p99": round(float(np.percentile(rules_ms, 99)), 1)},
        "paymentLatencyMs": {"p50": round(float(np.percentile(latency, 50)), 1), "p99": round(float(np.percentile(latency, 99)), 1),
                              "note": "half a tick of batching (250 ms) plus the batch's processing time"},
        "medianSubgraphEdges": int(statistics.median(sub)),
        "alerts": len(engine.alerts),
    }


# ---------------------------------------------------------------------- http mode


async def http_run(url: str, tps: int, seconds: float, batch: int = 100, shards: int = 1) -> dict[str, Any]:
    import aiohttp

    factory = PaymentFactory(seed=tps, shards=shards)
    sent_at: list[tuple[float, int]] = []  # (time, cumulative sent)
    http_ms: list[float] = []
    errors = 0
    rejected = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async def platform_count() -> int:
            async with session.get(f"{url}/rail/platform") as r:
                return (await r.json())["ingest"]["ingestedThisRun"]

        base = await platform_count()
        interval = batch / tps
        start = time.perf_counter()
        sent = 0
        pending: set[asyncio.Task] = set()
        progress: list[tuple[float, int]] = []

        async def post(payments: list[dict[str, Any]]) -> None:
            nonlocal errors, rejected
            t0 = time.perf_counter()
            try:
                async with session.post(f"{url}/rail/ingest/payments", json={"payments": payments}) as r:
                    await r.read()
                    if r.status == 429:
                        rejected += len(payments)
                    elif r.status >= 300:
                        errors += 1
            except Exception:
                errors += 1
            http_ms.append((time.perf_counter() - t0) * 1000)

        async def poll() -> None:
            while True:
                progress.append((time.perf_counter() - start, await platform_count() - base))
                await asyncio.sleep(0.25)

        poller = asyncio.create_task(poll())
        k = 0
        while time.perf_counter() - start < seconds:
            due = start + k * interval
            now = time.perf_counter()
            if due > now:
                await asyncio.sleep(due - now)
            task = asyncio.create_task(post(factory.batch(batch, interval)))
            pending.add(task)
            task.add_done_callback(pending.discard)
            sent += batch
            sent_at.append((time.perf_counter() - start, sent))
            k += 1
        await asyncio.gather(*pending)
        drain_start = time.perf_counter()
        while progress[-1][1] < sent - rejected and time.perf_counter() - drain_start < 60:
            await asyncio.sleep(0.25)
        poller.cancel()

    # end-to-end lag: for each ingested count, when was that many sent vs when was it ingested
    lags = []
    for t_ing, n in progress:
        t_sent = next((t for t, c in sent_at if c >= n), None)
        if n and t_sent is not None:
            lags.append((t_ing - t_sent) * 1000)
    duration = sent_at[-1][0] if sent_at else seconds
    final = progress[-1][1] if progress else 0
    return {
        "targetTps": tps, "shards": shards, "sent": sent, "ingested": final, "rejected429": rejected, "httpErrors": errors,
        "offeredTps": round(sent / duration), "ingestedTps": round(final / max(progress[-1][0], 1e-9)) if progress else 0,
        "httpMs": {"p50": round(float(np.percentile(http_ms, 50)), 1), "p99": round(float(np.percentile(http_ms, 99)), 1)},
        "endToEndMs": {"p50": round(float(np.percentile(lags, 50)), 1) if lags else None, "p99": round(float(np.percentile(lags, 99)), 1) if lags else None,
                       "note": "sent -> counted in ingestedThisRun, sampled every 250 ms (so +-250 ms)"},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["engine", "http"])
    parser.add_argument("--tps", type=int, nargs="+", default=[1000, 2000, 5000])
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--url", default="http://127.0.0.1:8011")
    parser.add_argument("--scoring", choices=["exact", "cached"], default="exact")
    parser.add_argument("--refresh", type=float, default=300.0, help="cached scoring: event-time seconds between x1 refreshes")
    parser.add_argument("--shards", type=int, default=0,
                        help="copies of the v2 account space, seeded with its last 72 h (0 = one copy per 100 TPS; 1 = all payments on v2's 5,680 accounts)")
    args = parser.parse_args(argv)
    report: dict[str, Any] = {"mode": args.mode, "at": datetime.now().isoformat(timespec="seconds"), "hardware": hardware(), "seconds": args.seconds, "runs": []}
    for tps in args.tps:
        shards = args.shards or max(1, tps // 100)
        run = engine_run(tps, args.seconds, shards=shards, scoring=args.scoring, refresh=args.refresh) if args.mode == "engine" else asyncio.run(http_run(args.url, tps, args.seconds, shards=shards))
        report["runs"].append(run)
        print(json.dumps(run), flush=True)
    target = ROOT / "reports" / ("loadtest_http.json" if args.mode == "http" else "loadtest.json" if args.scoring == "exact" else "loadtest_cached.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
