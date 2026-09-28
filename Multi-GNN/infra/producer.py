"""Push nolambur_transactions.csv into the rail as a live payment stream.

    python -m infra.producer webhook [--url http://127.0.0.1:8001] [--speed 60] [--limit N] [--from 2024-03-15T10:00]
    python -m infra.producer kafka   [--speed 60]      (KAFKA_BOOTSTRAP / KAFKA_TOPIC; pip install kafka-python)
    python -m infra.producer kinesis [--speed 60]      (KINESIS_STREAM; pip install boto3)

Rows go out in timestamp order with their original timestamps, spaced by the real gaps
divided by --speed (--speed 0 sends as fast as possible). Labels and the `layer`
column are stripped: the consumer sees only what a payment gateway would send.
"""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd
import requests

from . import settings
from .ingest import payment_from_csv
from .integrations import canonical, sign

BATCH = 200


def _rows(start: str | None, limit: int | None):
    df = pd.read_csv(settings.MULTI_GNN_DIR / "nolambur_transactions.csv")
    df["_t"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("_t", kind="stable")
    if start:
        df = df[df["_t"] >= pd.Timestamp(start)]
    if limit:
        df = df.head(limit)
    return df


def _paced(df, speed: float):
    """Yield batches, sleeping so the stream keeps the data's own rhythm / speed."""
    batch, first_t, wall0 = [], None, time.monotonic()
    for r in df.to_dict("records"):
        t = r["_t"].timestamp()
        first_t = t if first_t is None else first_t
        if speed > 0:
            due = wall0 + (t - first_t) / speed
            if due > time.monotonic() and batch:
                yield batch
                batch = []
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, 5.0))
        batch.append(payment_from_csv(r))
        if len(batch) >= BATCH:
            yield batch
            batch = []
    if batch:
        yield batch


def to_webhook(df, speed: float, url: str) -> int:
    endpoint = f"{url.rstrip('/')}/rail/ingest/payments"
    sent = 0
    for batch in _paced(df, speed):
        body = canonical({"payments": batch})
        headers = {"Content-Type": "application/json"}
        if settings.RAIL_WEBHOOK_SECRET:
            headers["X-Nolambur-Signature"] = sign(body, settings.RAIL_WEBHOOK_SECRET)
        response = requests.post(endpoint, data=body, headers=headers, timeout=30)
        response.raise_for_status()
        sent += len(batch)
        print(f"sent {sent:>6}  last {batch[-1]['timestamp']}  -> {response.json().get('queued')} queued", flush=True)
    return sent


def to_kafka(df, speed: float) -> int:
    from kafka import KafkaProducer  # type: ignore

    producer = KafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP, acks="all")
    sent = 0
    for batch in _paced(df, speed):
        for p in batch:
            # keyed by payer so one account's payments stay ordered within a partition
            producer.send(settings.KAFKA_TOPIC, key=p["payer_vpa"].encode(), value=json.dumps(p).encode())
        producer.flush()
        sent += len(batch)
        print(f"produced {sent:>6}  last {batch[-1]['timestamp']}", flush=True)
    return sent


def to_kinesis(df, speed: float) -> int:
    import boto3  # type: ignore

    client = boto3.client("kinesis", region_name=settings.AWS_REGION)
    sent = 0
    for batch in _paced(df, speed):
        for i in range(0, len(batch), 500):  # PutRecords limit
            chunk = batch[i : i + 500]
            client.put_records(StreamName=settings.KINESIS_STREAM, Records=[{"Data": json.dumps(p).encode(), "PartitionKey": p["payer_vpa"]} for p in chunk])
        sent += len(batch)
        print(f"put {sent:>6}  last {batch[-1]['timestamp']}", flush=True)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sink", choices=["webhook", "kafka", "kinesis"])
    parser.add_argument("--url", default=settings.BRIDGE_PUBLIC_URL)
    parser.add_argument("--speed", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--from", dest="start", default=None)
    args = parser.parse_args()
    df = _rows(args.start, args.limit)
    print(f"{len(df)} payments -> {args.sink} at {args.speed}x")
    if args.sink == "webhook":
        to_webhook(df, args.speed, args.url)
    elif args.sink == "kafka":
        to_kafka(df, args.speed)
    else:
        to_kinesis(df, args.speed)


if __name__ == "__main__":
    main()
