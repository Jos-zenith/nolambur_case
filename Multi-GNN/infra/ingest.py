"""Payment ingest: the wire schema and the stream consumers that feed the rail engine.

Every source ends in the same place: RailService.inbox (an asyncio.Queue of Payment
dicts). The service loop drains it once per tick, scores the batch with the GNN in one
forward pass, and hands the rows to the detectors (RailEngine.ingest_live).

Delivery is at-least-once, end to end. Each batch a consumer pushes carries an `ack`
callback, and the service calls it only after the engine has ingested the batch. Only
then does the consumer commit (Kafka offsets) or checkpoint (Kinesis sequence numbers,
in the stream_checkpoints table). A crash anywhere before that means the batch is read
again on restart. The engine drops a txn_id it has already seen in this run, so a
redelivered message or a retried webhook does not double-count within a run.

Backpressure: while the inbox holds more than HIGH_WATER payments, Kafka partitions are
paused (the consumer keeps polling so it stays in its group) and Kinesis stops calling
GetRecords. The webhook answers 429 instead.

A message that does not parse or validate goes to the ingest_dead_letters table with
its position and the error, and is acknowledged so it cannot block its partition.

A payment never carries a fraud label. Precision / recall still work when the
Nolambur CSV is streamed in (infra/producer.py) because the engine looks labels up by
account id, the same way the replay does.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
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


Ack = Callable[[], None]
Push = Callable[[list[dict[str, Any]], "Ack | None"], None]
Backlog = Callable[[], int]

HIGH_WATER = 20_000  # payments waiting in the inbox before consumers pause


def parse_payment(raw: bytes | str) -> dict[str, Any]:
    return Payment(**json.loads(raw)).model_dump()


def _store():
    """The durable store, or None when it is unavailable (consumers still run, without checkpoints)."""
    try:
        from .store import get_store

        return get_store()
    except Exception:
        return None


class Source:
    """A background consumer. `push` must be safe to call from any thread."""

    backend = "none"

    def __init__(self) -> None:
        self.state = "idle"
        self.received = 0
        self.acked = 0
        self.dead_lettered = 0
        self.paused_for_backlog = False
        self.lag: int | None = None
        self.last_error: str | None = None
        self.last_at: float | None = None
        self.last_commit_at: float | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend, "state": self.state, "received": self.received, "acked": self.acked,
            "deadLettered": self.dead_lettered, "pausedForBacklog": self.paused_for_backlog, "lag": self.lag,
            "lastError": self.last_error, "lastAt": self.last_at, "lastCommitAt": self.last_commit_at,
        }

    def _got(self, n: int) -> None:
        self.received += n
        self.last_at = time.time()

    def _dead(self, position: str, raw: Any, error: Exception) -> None:
        self.dead_lettered += 1
        self.last_error = f"dead-lettered {position}: {error}"[:300]
        store = _store()
        if store:
            store.dead_letter(self.backend, position, raw, f"{type(error).__name__}: {error}")

    async def start(self, push: Push, backlog: Backlog) -> None:
        self.state = "listening"


class WebhookSource(Source):
    """Payments arrive on POST /rail/ingest/payments; nothing to consume."""

    backend = "webhook"

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "endpoint": "/rail/ingest/payments", "signed": bool(settings.RAIL_WEBHOOK_SECRET)}


class KafkaSource(Source):
    """aiokafka consumer in the service's event loop. Auto-commit is off: each partition's
    offset is committed once the engine acks the batch that ends there. `lag` is messages
    behind the partitions' high-water marks."""

    backend = "kafka"

    def __init__(self) -> None:
        super().__init__()
        self.assigned: list[str] = []
        self._acked: dict[Any, int] = {}  # TopicPartition -> next offset to commit
        self._committed: dict[Any, int] = {}

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "bootstrap": settings.KAFKA_BOOTSTRAP, "topic": settings.KAFKA_TOPIC, "group": settings.KAFKA_GROUP, "partitions": self.assigned}

    async def _commit(self, consumer) -> None:
        owned = consumer.assignment()
        due = {tp: off for tp, off in self._acked.items() if tp in owned and self._committed.get(tp) != off}
        if not due:
            return
        await consumer.commit(due)
        self._committed.update(due)
        self.last_commit_at = time.time()
        store = _store()
        if store:  # mirror for the platform page; Kafka's own committed offset is what resumes
            await asyncio.to_thread(store.save_checkpoints, "kafka", settings.KAFKA_TOPIC, {str(tp.partition): str(off) for tp, off in due.items()})

    async def start(self, push: Push, backlog: Backlog) -> None:
        try:
            from aiokafka import AIOKafkaConsumer, ConsumerRebalanceListener  # type: ignore
        except ImportError:
            self.state, self.last_error = "error", "aiokafka is not installed (pip install aiokafka)"
            return
        source = self

        class Rebalance(ConsumerRebalanceListener):
            def __init__(self, consumer) -> None:
                self.consumer = consumer

            async def on_partitions_revoked(self, revoked) -> None:
                try:  # hand over what has been processed, so the next owner starts after it
                    await source._commit(self.consumer)
                except Exception as error:
                    source.last_error = f"commit on revoke: {error}"[:300]
                for tp in revoked:
                    source._acked.pop(tp, None)
                    source._committed.pop(tp, None)

            async def on_partitions_assigned(self, assigned) -> None:
                source.assigned = sorted(f"{tp.topic}/{tp.partition}" for tp in self.consumer.assignment())
                if source.paused_for_backlog:
                    self.consumer.pause(*assigned)

        while True:
            consumer = AIOKafkaConsumer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP,
                group_id=settings.KAFKA_GROUP,
                enable_auto_commit=False,
                auto_offset_reset=settings.KAFKA_OFFSET_RESET,
            )
            consumer.subscribe([settings.KAFKA_TOPIC], listener=Rebalance(consumer))
            try:
                self.state = "connecting"
                await consumer.start()
                self.state, self.last_error = "listening", None
                while True:
                    owned = consumer.assignment()
                    if backlog() > HIGH_WATER:
                        if not self.paused_for_backlog:
                            consumer.pause(*owned)
                            self.paused_for_backlog, self.state = True, "paused (inbox full)"
                    elif self.paused_for_backlog:
                        consumer.resume(*owned)
                        self.paused_for_backlog, self.state = False, "listening"
                    batches = await consumer.getmany(timeout_ms=500, max_records=2000)
                    for tp, records in batches.items():
                        payments = []
                        for record in records:
                            try:
                                payments.append(parse_payment(record.value))
                            except Exception as error:  # a poison message must not stop the partition
                                self._dead(f"{tp.topic}/{tp.partition}@{record.offset}", record.value, error)

                        def ack(tp=tp, next_offset=records[-1].offset + 1, n=len(payments)) -> None:
                            self._acked[tp] = max(self._acked.get(tp, 0), next_offset)
                            self.acked += n

                        if payments:
                            push(payments, ack)
                            self._got(len(payments))
                        else:
                            ack()  # all dead-lettered: nothing for the engine, move past them
                    await self._commit(consumer)
                    lags = []
                    for tp in owned:
                        high = consumer.highwater(tp)
                        if high is not None:
                            lags.append(high - await consumer.position(tp))
                    self.lag = sum(lags) if lags else None
            except Exception as error:
                self.state, self.last_error = "reconnecting", f"{type(error).__name__}: {error}"[:300]
                await asyncio.sleep(5)
            finally:
                try:
                    await self._commit(consumer)
                except Exception:
                    pass
                try:
                    await consumer.stop()
                except Exception:
                    pass
                self._acked.clear()
                self._committed.clear()
                self.paused_for_backlog = False


class KinesisSource(Source):
    """Polls every shard with GetRecords from one thread and checkpoints, per shard, the
    last sequence number the engine acked (stream_checkpoints table). `lag` is the largest
    MillisBehindLatest across shards, in milliseconds.

    Resharding: shards are re-listed every SHARD_REFRESH seconds and whenever one closes. A
    child shard (from a split or merge) is read only after all its parents have been read
    to their end and acked, so each key's records stay in order. A shard with a checkpoint
    resumes AFTER_SEQUENCE_NUMBER; a child starts at TRIM_HORIZON; any other new shard
    starts at KINESIS_START (TRIM_HORIZON by default, so a first start misses nothing still
    in retention).

    One consumer per stream. Several bridges on one stream would each read every shard;
    dividing shards between them needs leases (what the KCL does), which this does not do.
    """

    backend = "kinesis"
    SHARD_REFRESH = 30.0

    def __init__(self) -> None:
        super().__init__()
        self.shards: dict[str, dict[str, Any]] = {}  # shard id -> state shown on /platform
        self._lock = threading.Lock()
        self._acked: dict[str, str] = {}  # shard -> last sequence number the engine processed
        self._saved: dict[str, str] = {}
        self._pending: dict[str, int] = defaultdict(int)  # batches pushed, not yet acked
        self._closed: set[str] = set()  # read to the end; marked finished once fully acked
        self._memory_checkpoints: dict[str, dict[str, Any]] = {}  # used when the store is down
        self._relist = False  # a parent finished: its children can open now

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "stream": settings.KINESIS_STREAM, "region": settings.AWS_REGION, "endpoint": settings.KINESIS_ENDPOINT or None, "shards": list(self.shards.values())}

    async def start(self, push: Push, backlog: Backlog) -> None:
        try:
            import boto3  # type: ignore
        except ImportError:
            self.state, self.last_error = "error", "boto3 is not installed (pip install boto3)"
            return
        if not settings.KINESIS_STREAM:
            self.state, self.last_error = "error", "KINESIS_STREAM is not set"
            return
        threading.Thread(target=self._run, args=(boto3, push, backlog), name="rail-kinesis", daemon=True).start()
        self.state = "connecting"

    # -------------------------------------------------------------- checkpoints

    def _load_checkpoints(self) -> dict[str, dict[str, Any]]:
        store = _store()
        return store.checkpoints("kinesis", settings.KINESIS_STREAM) if store else {k: dict(v) for k, v in self._memory_checkpoints.items()}

    def _save_checkpoints(self) -> None:
        with self._lock:
            due = {s: q for s, q in self._acked.items() if self._saved.get(s) != q}
            finished = {s for s in self._closed if self._pending[s] == 0}
        if not due and not finished:
            return
        store = _store()
        if store:
            store.save_checkpoints("kinesis", settings.KINESIS_STREAM, due, finished)
        else:
            for s in set(due) | finished:
                row = self._memory_checkpoints.setdefault(s, {"position": "", "closed": 0})
                row["position"] = due.get(s, row["position"])
                row["closed"] = int(s in finished or row["closed"])
        with self._lock:
            self._saved.update(due)
            self._closed -= finished
        for s in finished:
            self.shards[s] = {"id": s, "state": "finished"}
        if finished:
            self._relist = True
        self.last_commit_at = time.time()

    # -------------------------------------------------------------- polling

    def _run(self, boto3, push: Push, backlog: Backlog) -> None:
        while True:
            try:
                client = boto3.client("kinesis", region_name=settings.AWS_REGION, endpoint_url=settings.KINESIS_ENDPOINT or None)
                self._poll(client, push, backlog)
            except Exception as error:
                self.state, self.last_error = "reconnecting", f"{type(error).__name__}: {error}"[:300]
                time.sleep(5)

    def _list_shards(self, client) -> list[dict[str, Any]]:
        shards, token = [], None
        while True:
            out = client.list_shards(NextToken=token) if token else client.list_shards(StreamName=settings.KINESIS_STREAM)
            shards += out["Shards"]
            token = out.get("NextToken")
            if not token:
                return shards

    def _iterator(self, client, shard: dict[str, Any], checkpoint: dict[str, Any] | None) -> str:
        args: dict[str, Any] = {"StreamName": settings.KINESIS_STREAM, "ShardId": shard["ShardId"]}
        if checkpoint and checkpoint.get("position"):
            args.update(ShardIteratorType="AFTER_SEQUENCE_NUMBER", StartingSequenceNumber=checkpoint["position"])
        elif shard.get("ParentShardId"):
            args["ShardIteratorType"] = "TRIM_HORIZON"
        else:
            args["ShardIteratorType"] = settings.KINESIS_START
        return client.get_shard_iterator(**args)["ShardIterator"]

    def _open_ready_shards(self, client, iterators: dict[str, str]) -> None:
        self._save_checkpoints()
        checkpoints = self._load_checkpoints()
        shards = self._list_shards(client)
        present = {s["ShardId"] for s in shards}
        for shard in shards:
            sid = shard["ShardId"]
            ck = checkpoints.get(sid)
            ending = shard.get("SequenceNumberRange", {}).get("EndingSequenceNumber")
            if ck and not ck.get("closed") and ending and ck.get("position") and int(ck["position"]) >= int(ending) and sid not in iterators:
                # closed shard already processed to its last record (e.g. before a restart)
                store = _store()
                if store:
                    store.save_checkpoints("kinesis", settings.KINESIS_STREAM, {}, {sid})
                else:
                    self._memory_checkpoints.setdefault(sid, {"position": ck["position"]})["closed"] = 1
                ck = {**ck, "closed": 1}
                checkpoints[sid] = ck
            if ck and ck.get("closed"):
                self.shards[sid] = {"id": sid, "state": "finished"}
                continue
            if sid in iterators or sid in self._closed:
                continue
            # a parent that has aged out of retention is gone from the listing: nothing to wait for
            parents = [p for p in (shard.get("ParentShardId"), shard.get("AdjacentParentShardId")) if p and p in present]
            if any(not (checkpoints.get(p) or {}).get("closed") for p in parents):
                self.shards[sid] = {"id": sid, "state": "waiting for parent", "parents": parents}
                continue
            iterators[sid] = self._iterator(client, shard, ck)
            self.shards[sid] = {"id": sid, "state": "reading", "resumedFrom": (ck or {}).get("position") or None, "millisBehind": None}

    def _poll(self, client, push: Push, backlog: Backlog) -> None:
        iterators: dict[str, str] = {}
        last_read: dict[str, str] = {}  # last sequence fetched, to reopen an expired iterator without re-reading
        listed_at = 0.0
        self.state, self.last_error = "listening", None
        while True:
            if time.monotonic() - listed_at > self.SHARD_REFRESH or not iterators or self._relist:
                self._relist = False
                self._open_ready_shards(client, iterators)
                listed_at = time.monotonic()
                if not iterators:
                    self.state = "idle (no readable shard)" if not self._closed else "draining"
                    time.sleep(1.0)
                    continue

            if backlog() > HIGH_WATER:
                self.paused_for_backlog, self.state = True, "paused (inbox full)"
                self._save_checkpoints()
                time.sleep(0.5)
                continue
            self.paused_for_backlog, self.state = False, "listening"

            got_any = False
            for sid, iterator in list(iterators.items()):
                try:
                    out = client.get_records(ShardIterator=iterator, Limit=1000)
                except client.exceptions.ProvisionedThroughputExceededException:
                    self.last_error = f"throttled on {sid}; backing off"
                    time.sleep(1.0)
                    continue
                except client.exceptions.ExpiredIteratorException:
                    seq = last_read.get(sid) or self._acked.get(sid)
                    args = {"ShardIteratorType": "AFTER_SEQUENCE_NUMBER", "StartingSequenceNumber": seq} if seq else {"ShardIteratorType": "TRIM_HORIZON"}
                    iterators[sid] = client.get_shard_iterator(StreamName=settings.KINESIS_STREAM, ShardId=sid, **args)["ShardIterator"]
                    continue
                records = out.get("Records", [])
                if records:
                    got_any = True
                    payments = []
                    for record in records:
                        try:
                            payments.append(parse_payment(record["Data"]))
                        except Exception as error:
                            self._dead(f"{settings.KINESIS_STREAM}/{sid}@{record.get('SequenceNumber')}", record.get("Data"), error)
                    seq = records[-1]["SequenceNumber"]
                    last_read[sid] = seq

                    def ack(sid=sid, seq=seq, n=len(payments)) -> None:
                        with self._lock:
                            self._acked[sid] = seq  # one shard's batches are acked in inbox (FIFO) order
                            self._pending[sid] -= 1
                        self.acked += n

                    with self._lock:
                        self._pending[sid] += 1
                    if payments:
                        push(payments, ack)
                        self._got(len(payments))
                    else:
                        ack()
                if sid in self.shards:
                    self.shards[sid]["millisBehind"] = out.get("MillisBehindLatest")
                if out.get("NextShardIterator"):
                    iterators[sid] = out["NextShardIterator"]
                else:  # closed by a reshard; its children open once everything read from it is acked
                    iterators.pop(sid)
                    with self._lock:
                        self._closed.add(sid)
                    self.shards[sid] = {"id": sid, "state": "closed, draining"}
                    listed_at = 0.0
            behind = [s["millisBehind"] for s in self.shards.values() if s.get("state") == "reading" and s.get("millisBehind") is not None]
            self.lag = max(behind) if behind else None
            self._save_checkpoints()
            time.sleep(0.2 if got_any else 1.0)  # GetRecords allows 5 calls per shard per second


def make_source() -> Source:
    return {"kafka": KafkaSource, "kinesis": KinesisSource}.get(settings.RAIL_SOURCE, WebhookSource)()
