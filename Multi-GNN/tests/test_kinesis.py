"""KinesisSource against an in-memory fake of the Kinesis API.

moto (used for the broker-level runs in infra/README.md) keeps writing to a shard after
it is split and never closes it, so resharding cannot be tested there. This fake follows
AWS's documented behaviour for a split instead: the parent gets an EndingSequenceNumber,
new records go to the children, and GetRecords on a drained closed shard returns no
NextShardIterator.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from infra import ingest, settings
from infra.store import Store

STREAM = "test-stream"


class Stop(Exception):
    """Raised by a fake client to end its consumer's poll loop (a crash or shutdown)."""


class Data:
    """The stream itself, shared by every client (bridge) that reads it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seq = 0
        self.shards: dict[str, dict] = {}

    def add_shard(self, sid: str, parent: str | None = None) -> None:
        self.shards[sid] = {"records": [], "parent": parent, "closed": False, "start": str(self.seq + 1)}

    def put(self, sid: str, txn: str) -> None:
        with self.lock:
            assert not self.shards[sid]["closed"], "writes go to open shards only"
            self.seq += 1
            p = {"txn_id": txn, "payer_vpa": f"{txn.lower()}@ybl", "payee_vpa": "shop@okaxis", "amount_inr": 10.0}
            self.shards[sid]["records"].append((str(self.seq), json.dumps(p).encode()))

    def split(self, parent: str, children: list[str]) -> None:
        with self.lock:
            self.seq += 1
            self.shards[parent]["closed"] = True
            self.shards[parent]["ending"] = str(self.seq)  # the range end, past the last record
        for c in children:
            self.add_shard(c, parent)


class FakeKinesis:
    class exceptions:
        class ProvisionedThroughputExceededException(Exception):
            pass

        class ExpiredIteratorException(Exception):
            pass

    def __init__(self, data: Data) -> None:
        self.data = data
        self.stopped = False

    def _alive(self) -> None:
        if self.stopped:
            raise Stop()

    def list_shards(self, StreamName=None, NextToken=None):
        self._alive()
        out = []
        for sid, s in self.data.shards.items():
            rng = {"StartingSequenceNumber": s["start"]}
            if s["closed"]:
                rng["EndingSequenceNumber"] = s["ending"]
            out.append({"ShardId": sid, "SequenceNumberRange": rng, **({"ParentShardId": s["parent"]} if s["parent"] else {})})
        return {"Shards": out}

    def get_shard_iterator(self, StreamName, ShardId, ShardIteratorType, StartingSequenceNumber=None):
        self._alive()
        records = self.data.shards[ShardId]["records"]
        if ShardIteratorType == "TRIM_HORIZON":
            idx = 0
        elif ShardIteratorType == "LATEST":
            idx = len(records)
        else:  # AFTER_SEQUENCE_NUMBER
            idx = next(i + 1 for i, (seq, _) in enumerate(records) if seq == StartingSequenceNumber)
        return {"ShardIterator": f"{ShardId}|{idx}"}

    def get_records(self, ShardIterator, Limit):
        self._alive()
        sid, idx = ShardIterator.split("|")
        with self.data.lock:
            shard = self.data.shards[sid]
            records = shard["records"][int(idx) : int(idx) + Limit]
            end = int(idx) + len(records)
            drained = shard["closed"] and end >= len(shard["records"])
        return {
            "Records": [{"SequenceNumber": seq, "Data": data} for seq, data in records],
            "NextShardIterator": None if drained else f"{sid}|{end}",
            "MillisBehindLatest": 0,
        }


class Bridge:
    """One KinesisSource plus a stand-in for the engine that acks each batch it takes."""

    def __init__(self, data: Data, withhold=lambda payments: False) -> None:
        self.client = FakeKinesis(data)
        self.source = ingest.KinesisSource()
        self.source.SHARD_REFRESH = 0.2
        self.delivered: list[str] = []  # txn ids in the order the engine processed them
        self.withheld = False
        self._withhold = withhold
        self._inbox: list = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._consume, daemon=True).start()
        threading.Thread(target=self._engine, daemon=True).start()

    def _consume(self) -> None:
        try:
            self.source._poll(self.client, self._push, lambda: 0)
        except Stop:
            pass

    def _push(self, payments, ack) -> None:
        with self._lock:
            self._inbox.append((payments, ack))

    def _engine(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                batch, self._inbox = self._inbox, []
            for payments, ack in batch:
                self.delivered += [p["txn_id"] for p in payments]
                if self.withheld or self._withhold(payments):
                    self.withheld = True  # a crash: this batch and everything after it is never acked
                elif ack:
                    ack()
            time.sleep(0.01)

    def stop(self) -> None:
        self.client.stopped = True
        self._stop.set()
        time.sleep(0.1)


def wait_for(cond, timeout=10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = Store(f"sqlite:///{(tmp_path / 'k.db').as_posix()}")
    monkeypatch.setattr(ingest, "_store", lambda: s)
    monkeypatch.setattr(settings, "KINESIS_STREAM", STREAM)
    monkeypatch.setattr(settings, "KINESIS_START", "TRIM_HORIZON")
    real_sleep = time.sleep
    monkeypatch.setattr(ingest.time, "sleep", lambda s: real_sleep(min(s, 0.02)))
    return s


def test_split_reads_parent_to_the_end_before_children(store):
    data = Data()
    data.add_shard("shard-0")
    for i in range(30):
        data.put("shard-0", f"P{i:03d}")
    data.split("shard-0", ["shard-1", "shard-2"])
    for i in range(20):
        data.put(f"shard-{1 + i % 2}", f"C{i:03d}")

    b = Bridge(data)
    wait_for(lambda: len(b.delivered) == 50)
    b.stop()

    first_child = min(i for i, t in enumerate(b.delivered) if t.startswith("C"))
    assert all(t.startswith("P") for t in b.delivered[:first_child]) and first_child == 30
    assert sorted(b.delivered) == sorted({*b.delivered})  # each exactly once
    ck = store.checkpoints("kinesis", STREAM)
    assert ck["shard-0"]["closed"] == 1
    assert {"shard-1", "shard-2"} <= set(ck)


def test_children_wait_while_the_parent_has_unacked_records(store):
    data = Data()
    data.add_shard("shard-0")
    for i in range(10):
        data.put("shard-0", f"P{i:03d}")
    data.split("shard-0", ["shard-1"])
    for i in range(5):
        data.put("shard-1", f"C{i:03d}")

    b = Bridge(data, withhold=lambda payments: payments[0]["txn_id"].startswith("P"))
    wait_for(lambda: len(b.delivered) == 10)
    time.sleep(0.5)  # plenty of relists
    assert not any(t.startswith("C") for t in b.delivered)
    assert b.source.shards["shard-1"]["state"] == "waiting for parent"
    assert not store.checkpoints("kinesis", STREAM).get("shard-0", {}).get("closed")
    b.stop()


def test_restart_during_handoff_rereads_only_what_was_not_acked(store):
    data = Data()
    data.add_shard("shard-0")
    for i in range(15):
        data.put("shard-0", f"P{i:03d}")

    # run 1 acks the first parent batch, then "crashes" on the second
    b1 = Bridge(data, withhold=lambda payments: payments[0]["txn_id"] >= "P015")
    wait_for(lambda: len(b1.delivered) == 15)
    time.sleep(0.2)  # the first batch's checkpoint is written
    for i in range(15, 30):
        data.put("shard-0", f"P{i:03d}")
    data.split("shard-0", ["shard-1", "shard-2"])
    for i in range(10):
        data.put(f"shard-{1 + i % 2}", f"C{i:03d}")
    wait_for(lambda: len(b1.delivered) == 30)
    time.sleep(0.3)
    assert not any(t.startswith("C") for t in b1.delivered)  # parent not finished: children never opened
    b1.stop()
    assert store.checkpoints("kinesis", STREAM)["shard-0"]["position"] == data.shards["shard-0"]["records"][14][0]

    # run 2 resumes after P014, finishes the parent, then reads the children
    store.release_lease("kinesis", STREAM, b1.source.owner)
    b2 = Bridge(data)
    wait_for(lambda: len(b2.delivered) == 25)
    b2.stop()
    assert b2.delivered[:15] == [f"P{i:03d}" for i in range(15, 30)]
    assert sorted(b2.delivered[15:]) == [f"C{i:03d}" for i in range(10)]
    assert set(b1.delivered) | set(b2.delivered) == {f"P{i:03d}" for i in range(30)} | {f"C{i:03d}" for i in range(10)}


def test_second_bridge_stands_by_then_takes_over(store, monkeypatch):
    monkeypatch.setattr(ingest.KinesisSource, "LEASE_TTL", 0.5)
    monkeypatch.setattr(ingest.KinesisSource, "LEASE_RENEW", 0.05)
    data = Data()
    data.add_shard("shard-0")
    data.add_shard("shard-1")
    for i in range(40):
        data.put(f"shard-{i % 2}", f"A{i:03d}")

    a = Bridge(data)
    wait_for(lambda: len(a.delivered) == 40)
    b = Bridge(data)
    time.sleep(0.4)
    assert b.delivered == []
    assert b.source.state.startswith("standby") and b.source.lease["holder"] == a.source.owner

    for i in range(20):
        data.put(f"shard-{i % 2}", f"B{i:03d}")
    wait_for(lambda: len(a.delivered) == 60)
    time.sleep(0.2)
    a.stop()  # a dies without releasing: b waits out the TTL
    for i in range(20):
        data.put(f"shard-{i % 2}", f"D{i:03d}")
    wait_for(lambda: len(b.delivered) == 20, timeout=15)
    b.stop()
    assert sorted(b.delivered) == [f"D{i:03d}" for i in range(20)]  # resumed from a's checkpoints, nothing re-read
    assert b.source.lease["held"] and b.source.lease["holder"] == b.source.owner
