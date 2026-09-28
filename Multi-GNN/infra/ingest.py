"""Payment ingest: the wire schema and the stream consumers that feed the rail engine.

Every source ends in the same place: RailService.inbox (an asyncio.Queue of Payment
dicts). The service loop drains it once per tick, scores the batch with the GNN in one
forward pass, and hands the rows to the detectors (RailEngine.ingest_live).

Delivery is at-least-once; the engine drops a txn_id it has already seen in this run,
so a redelivered Kafka message or a retried webhook does not double-count.

A payment never carries a fraud label. Precision / recall still work when the
Nolambur CSV is streamed in (infra/producer.py) because the engine looks labels up by
account id, the same way the replay does.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field, field_validator

from . import settings


class Payment(BaseModel):
    txn_id: str = Field(min_length=1, max_length=64)
    payer_vpa: str = Field(min_length=3)
    payee_vpa: str = Field(min_length=3)
    amount_inr: float = Field(gt=0)
    timestamp: str | None = Field(default=None, description="ISO 8601; defaults to arrival time (webhook) or the replay clock (replay mode)")
    payer_state: str | None = None
    payee_state: str | None = None
    payer_account_id: str | None = None
    payee_account_id: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _normalise_timestamp(cls, value: str | None) -> str | None:
        """ISO 8601 in, 'YYYY-MM-DDTHH:MM:SS' out. Naive times are kept as given (the
        dataset's convention); times with an offset are converted to UTC."""
        if value in (None, ""):
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%dT%H:%M:%S")


class PaymentBatch(BaseModel):
    payments: list[Payment] = Field(min_length=1, max_length=5000)


def payment_from_csv(r: dict[str, Any]) -> dict[str, Any]:
    """A nolambur_transactions.csv row as a gateway would send it: no labels, no layer."""
    return {
        "txn_id": str(r["txn_id"]),
        "payer_vpa": str(r["sender_vpa"]),
        "payee_vpa": str(r["recv_vpa"]),
        "amount_inr": float(r["amount_inr"]),
        "timestamp": str(r["timestamp"]),
        "payer_state": str(r["sender_state"]),
        "payee_state": str(r["recv_state"]),
        "payer_account_id": str(r["sender_id"]),
        "payee_account_id": str(r["recv_id"]),
    }


Push = Callable[[list[dict[str, Any]]], None]


class Source:
    """A background consumer. `push` must be safe to call from any thread."""

    backend = "none"

    def __init__(self) -> None:
        self.state = "idle"
        self.received = 0
        self.last_error: str | None = None
        self.last_at: float | None = None

    def describe(self) -> dict[str, Any]:
        return {"backend": self.backend, "state": self.state, "received": self.received, "lastError": self.last_error, "lastAt": self.last_at}

    def _got(self, n: int) -> None:
        self.received += n
        self.last_at = time.time()

    async def start(self, push: Push) -> None:
        self.state = "listening"


class WebhookSource(Source):
    """Payments arrive on POST /rail/ingest/payments; nothing to consume."""

    backend = "webhook"

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "endpoint": "/rail/ingest/payments", "signed": bool(settings.RAIL_WEBHOOK_SECRET)}


class KafkaSource(Source):
    backend = "kafka"

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "bootstrap": settings.KAFKA_BOOTSTRAP, "topic": settings.KAFKA_TOPIC, "group": settings.KAFKA_GROUP}

    async def start(self, push: Push) -> None:
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore
        except ImportError:
            self.state, self.last_error = "error", "aiokafka is not installed (pip install aiokafka)"
            return
        while True:
            consumer = AIOKafkaConsumer(
                settings.KAFKA_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP,
                group_id=settings.KAFKA_GROUP,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )
            try:
                self.state = "connecting"
                await consumer.start()
                self.state, self.last_error = "listening", None
                while True:
                    batches = await consumer.getmany(timeout_ms=500, max_records=2000)
                    payments = []
                    for records in batches.values():
                        for record in records:
                            try:
                                payments.append(Payment(**json.loads(record.value)).model_dump())
                            except Exception as error:  # a poison message must not stop the partition
                                self.last_error = f"skipped offset {record.offset}: {error}"[:300]
                    if payments:
                        push(payments)
                        self._got(len(payments))
                    if batches:
                        # Committed once the batch is in the inbox. A crash before the engine
                        # processes it loses at most one tick of payments; txn_id dedupe covers
                        # the opposite case (redelivery after a crash before commit).
                        await consumer.commit()
            except Exception as error:
                self.state, self.last_error = "reconnecting", f"{type(error).__name__}: {error}"[:300]
                await asyncio.sleep(5)
            finally:
                try:
                    await consumer.stop()
                except Exception:
                    pass


class KinesisSource(Source):
    backend = "kinesis"

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "stream": settings.KINESIS_STREAM, "region": settings.AWS_REGION}

    async def start(self, push: Push) -> None:
        try:
            import boto3  # type: ignore
        except ImportError:
            self.state, self.last_error = "error", "boto3 is not installed (pip install boto3)"
            return
        if not settings.KINESIS_STREAM:
            self.state, self.last_error = "error", "KINESIS_STREAM is not set"
            return
        threading.Thread(target=self._poll, args=(boto3, push), name="rail-kinesis", daemon=True).start()
        self.state = "connecting"

    def _poll(self, boto3, push: Push) -> None:
        while True:
            try:
                client = boto3.client("kinesis", region_name=settings.AWS_REGION)
                shards = client.list_shards(StreamName=settings.KINESIS_STREAM)["Shards"]
                iterators = {
                    s["ShardId"]: client.get_shard_iterator(StreamName=settings.KINESIS_STREAM, ShardId=s["ShardId"], ShardIteratorType="LATEST")["ShardIterator"]
                    for s in shards
                }
                self.state, self.last_error = "listening", None
                while iterators:
                    for shard, iterator in list(iterators.items()):
                        out = client.get_records(ShardIterator=iterator, Limit=1000)
                        payments = []
                        for record in out["Records"]:
                            try:
                                payments.append(Payment(**json.loads(record["Data"])).model_dump())
                            except Exception as error:
                                self.last_error = f"skipped {record.get('SequenceNumber')}: {error}"[:300]
                        if payments:
                            push(payments)
                            self._got(len(payments))
                        if out.get("NextShardIterator"):
                            iterators[shard] = out["NextShardIterator"]
                        else:
                            iterators.pop(shard)
                    time.sleep(1.0)  # Kinesis allows 5 GetRecords per shard per second
            except Exception as error:
                self.state, self.last_error = "reconnecting", f"{type(error).__name__}: {error}"[:300]
                time.sleep(5)


def make_source() -> Source:
    return {"kafka": KafkaSource, "kinesis": KinesisSource}.get(settings.RAIL_SOURCE, WebhookSource)()
