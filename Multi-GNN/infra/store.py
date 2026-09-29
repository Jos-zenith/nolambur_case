"""Durable store for the analyst audit trail, decisions (the feedback labels), the
integration outbox and the sandbox portals' records.

The audit trail is tamper-evident: each row stores the SHA-256 of the previous row's
hash plus its own content, and database triggers reject UPDATE and DELETE on it.
verify_audit_chain() recomputes the chain and names the first row that does not match,
which catches edits made by someone who dropped the triggers first.

SQLAlchemy Core, so the same code runs on the default SQLite file and on Postgres
(set RAIL_DB_URL). Hot-path writes (audit entries, decisions) go through one writer
thread so a slow database never stalls the replay loop; outbox and sandbox writes are
synchronous because their callers need the row back.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from typing import Any, Callable

from sqlalchemy import (
    JSON, Column, Float, Integer, MetaData, String, Table, Text, create_engine, event, func, insert, inspect, select, text, update,
)
from sqlalchemy.engine import Engine

from . import settings

metadata = MetaData()

runs = Table(
    "rail_runs", metadata,
    Column("id", String(40), primary_key=True),
    Column("started_at", Float, nullable=False),
    Column("source", String(20), nullable=False),
    Column("rule_version", String(20)),
    Column("meta", JSON),
)

audit_events = Table(
    "audit_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(40), index=True),
    Column("entry_id", String(20)),
    Column("at", Float, nullable=False),
    Column("sim_t", Float),
    Column("action", String(40), nullable=False),
    Column("actor", String(80)),
    Column("note", Text),
    Column("alert_id", String(20)),
    Column("account_id", String(64), index=True),
    Column("case_id", String(20)),
    Column("payload", JSON),
    Column("role", String(20)),
    Column("prev_hash", String(64)),
    Column("hash", String(64), index=True),
)

# Columns that go into each audit row's hash, in this order.
HASHED = ("run_id", "entry_id", "at", "sim_t", "action", "actor", "role", "note", "alert_id", "account_id", "case_id", "payload")
GENESIS = "0" * 64


def audit_hash(prev_hash: str, row: dict[str, Any]) -> str:
    body = json.dumps({k: row.get(k) for k in HASHED}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()

# One row per analyst decision on an alert. clear = the analyst says false positive,
# freeze = confirmed mule, escalate = no label yet. infra/feedback.py turns these into
# edge labels for retraining.
decisions = Table(
    "alert_decisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(40), index=True),
    Column("alert_id", String(20), nullable=False),
    Column("account_id", String(64), nullable=False, index=True),
    Column("vpa", String(120)),
    Column("detector", String(40)),
    Column("decision", String(20), nullable=False),
    Column("actor", String(80)),
    Column("note", Text),
    Column("at", Float, nullable=False),
    Column("sim_t", Float),
    Column("score", Integer),
    Column("gnn_max", Float),
    Column("rows", JSON),
    Column("truth_role", String(20)),
)

agent_actions = Table(
    "agent_actions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("logged_at", String(40)),
    Column("action", String(40)),
    Column("payload", JSON),
)

outbox = Table(
    "integration_outbox", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(40), nullable=False),
    Column("target", String(400), nullable=False),
    Column("reference", String(60), index=True),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False, index=True),  # pending | delivered | failed
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_attempt_at", Float, nullable=False),
    Column("last_error", Text),
    Column("response", JSON),
    Column("created_at", Float, nullable=False),
    Column("delivered_at", Float),
)

sandbox_records = Table(
    "sandbox_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("portal", String(20), nullable=False, index=True),  # gateway | cfcfrms
    Column("reference", String(60), nullable=False, unique=True),
    Column("status", String(30), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("received_at", Float, nullable=False),
)

# Where each stream consumer has got to, written only after the engine has processed the
# payments (infra/ingest.py). Kafka keeps its own committed offsets; this table is
# Kinesis's (one row per shard) and a mirror of Kafka's for the platform page.
stream_checkpoints = Table(
    "stream_checkpoints", metadata,
    Column("source", String(20), primary_key=True),   # kafka | kinesis
    Column("stream", String(200), primary_key=True),  # topic or stream name
    Column("shard", String(80), primary_key=True),    # partition or shard id
    Column("position", String(130), nullable=False),  # next offset, or last sequence number processed
    Column("closed", Integer, nullable=False, default=0),  # 1 = a Kinesis shard read to its end (resharded)
    Column("updated_at", Float, nullable=False),
)

# Which bridge may read a stream. Kafka divides partitions through its consumer group;
# Kinesis has no such thing, so a second bridge on the same stream stands by until the
# holder stops renewing. Works across bridges that share this database (Postgres, or one
# SQLite file on one machine).
stream_leases = Table(
    "stream_leases", metadata,
    Column("source", String(20), primary_key=True),
    Column("stream", String(200), primary_key=True),
    Column("owner", String(120), nullable=False),
    Column("expires_at", Float, nullable=False),
)

# Messages a consumer could not parse or validate. Kept so nothing is silently lost and a
# fixed message can be replayed with POST /rail/ingest/payments.
dead_letters = Table(
    "ingest_dead_letters", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(20), nullable=False, index=True),
    Column("position", String(200)),  # topic/partition/offset or stream/shard/sequence
    Column("raw", Text),
    Column("error", Text, nullable=False),
    Column("at", Float, nullable=False),
)


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

        @event.listens_for(engine, "connect")
        def _pragmas(conn, _record):  # WAL lets the writer thread and readers overlap
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


def _row(r) -> dict[str, Any]:
    return dict(r._mapping)


class Store:
    def __init__(self, url: str | None = None):
        self.url = url or settings.RAIL_DB_URL
        self.engine = _make_engine(self.url)
        metadata.create_all(self.engine)
        self._migrate()
        self._writes: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._writer = threading.Thread(target=self._drain, name="rail-store-writer", daemon=True)
        self._writer.start()
        self.write_errors = 0
        self.last_write_error: str | None = None

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created, and the append-only triggers."""
        have = {c["name"] for c in inspect(self.engine).get_columns("audit_events")}
        with self.engine.begin() as conn:
            for name, sql_type in (("role", "VARCHAR(20)"), ("prev_hash", "VARCHAR(64)"), ("hash", "VARCHAR(64)")):
                if name not in have:
                    conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN {name} {sql_type}"))
            if self.backend == "sqlite":
                for op in ("UPDATE", "DELETE"):
                    conn.execute(text(
                        f"CREATE TRIGGER IF NOT EXISTS audit_events_no_{op.lower()} BEFORE {op} ON audit_events "
                        "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
                    ))
            elif self.backend == "postgresql":
                conn.execute(text(
                    "CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$ "
                    "BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql"
                ))
                conn.execute(text("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events"))
                conn.execute(text(
                    "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
                    "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
                ))

    @property
    def backend(self) -> str:
        return self.engine.dialect.name

    def describe(self) -> dict[str, Any]:
        safe = self.engine.url.render_as_string(hide_password=True)
        durable = self.backend != "sqlite" or not settings.EPHEMERAL_DISK
        return {"backend": self.backend, "url": safe, "writeErrors": self.write_errors, "lastWriteError": self.last_write_error, "writeQueue": self._writes.qsize(),
                "durable": durable,
                "warning": None if durable else "SQLite on an ephemeral disk: the audit trail is lost on every redeploy. Set RAIL_DB_URL (or DATABASE_URL) to Postgres."}

    # ------------------------------------------------------------------ writer thread

    def _drain(self) -> None:
        while True:
            job = self._writes.get()
            try:
                if job is None:
                    return
                job()
            except Exception as error:  # keep the writer alive; surface the error in /rail/platform
                self.write_errors += 1
                self.last_write_error = f"{type(error).__name__}: {error}"[:300]
            finally:
                self._writes.task_done()

    def _later(self, stmt) -> None:
        def job() -> None:
            with self.engine.begin() as conn:
                conn.execute(stmt)

        self._writes.put(job)

    def flush(self) -> None:
        """Block until every queued write has landed (tests and CLI tools)."""
        self._writes.join()

    # ------------------------------------------------------------------ audit trail

    def start_run(self, run_id: str, source: str, rule_version: str, meta: dict[str, Any]) -> None:
        self._later(insert(runs).values(id=run_id, started_at=time.time(), source=source, rule_version=rule_version, meta=meta))

    def record_audit(self, run_id: str, entry: dict[str, Any]) -> None:
        known = {"id", "at", "simT", "action", "actor", "role", "note", "alertId", "accountId", "caseId"}
        row = {
            "run_id": run_id,
            "entry_id": entry["id"],
            # floats, as the database returns them, so the hash is stable whatever the caller passed
            "at": float(entry["at"]),
            "sim_t": float(entry["simT"]) if entry.get("simT") is not None else None,
            "action": entry["action"],
            "actor": entry.get("actor"),
            "role": entry.get("role"),
            "note": entry.get("note"),
            "alert_id": entry.get("alertId"),
            "account_id": entry.get("accountId"),
            "case_id": entry.get("caseId"),
            # through JSON once so the hash is computed on exactly what the database returns
            "payload": json.loads(json.dumps({k: v for k, v in entry.items() if k not in known}, default=str)) or None,
        }

        def job() -> None:
            with self.engine.begin() as conn:
                if self.backend == "postgresql":  # one chain even with several writers
                    conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))
                last = conn.execute(select(audit_events.c.hash).where(audit_events.c.hash.is_not(None)).order_by(audit_events.c.id.desc()).limit(1)).scalar()
                prev = last or GENESIS
                conn.execute(insert(audit_events).values(**row, prev_hash=prev, hash=audit_hash(prev, row)))

        self._writes.put(job)

    def verify_audit_chain(self) -> dict[str, Any]:
        """Recompute every hash. Rows written before the chain existed (no hash) are skipped."""
        checked, prev, first_bad = 0, None, None
        with self.engine.connect() as conn:
            result = conn.execution_options(stream_results=True).execute(
                select(audit_events).where(audit_events.c.hash.is_not(None)).order_by(audit_events.c.id)
            )
            for r in result:
                row = _row(r)
                expected_prev = prev if prev is not None else row["prev_hash"]
                if row["prev_hash"] != expected_prev or audit_hash(row["prev_hash"], row) != row["hash"]:
                    first_bad = {"id": row["id"], "entryId": row["entry_id"], "action": row["action"], "runId": row["run_id"],
                                 "reason": "link to previous row broken" if row["prev_hash"] != expected_prev else "content does not match its hash"}
                    break
                prev = row["hash"]
                checked += 1
            unchained = conn.execute(select(func.count()).select_from(audit_events).where(audit_events.c.hash.is_(None))).scalar() or 0
        return {"ok": first_bad is None, "checked": checked, "firstBad": first_bad, "head": prev, "unchainedLegacyRows": int(unchained), "checkedAt": time.time()}

    def record_decision(self, run_id: str, alert: dict[str, Any], decision: str, actor: str, note: str, sim_t: float) -> None:
        self._later(
            insert(decisions).values(
                run_id=run_id,
                alert_id=alert["id"],
                account_id=alert["accountId"],
                vpa=alert.get("vpa"),
                detector=alert.get("detector"),
                decision=decision,
                actor=actor,
                note=note,
                at=time.time(),
                sim_t=sim_t,
                score=alert.get("score"),
                gnn_max=alert.get("gnnMax"),
                rows=alert.get("rows"),
                truth_role=(alert.get("truth") or {}).get("role"),
            )
        )

    def record_agent_action(self, record: dict[str, Any]) -> None:
        self._later(insert(agent_actions).values(logged_at=record.get("logged_at"), action=record.get("action"), payload=record))

    def account_history(self, account_id: str, exclude_run: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        stmt = select(decisions).where(decisions.c.account_id == account_id)
        if exclude_run:
            stmt = stmt.where(decisions.c.run_id != exclude_run)
        stmt = stmt.order_by(decisions.c.at.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(stmt)]

    def audit_trail(self, *, run_id: str | None = None, account_id: str | None = None, alert_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        stmt = select(audit_events)
        if run_id:
            stmt = stmt.where(audit_events.c.run_id == run_id)
        if account_id:
            stmt = stmt.where(audit_events.c.account_id == account_id)
        if alert_id:
            stmt = stmt.where(audit_events.c.alert_id == alert_id)
        stmt = stmt.order_by(audit_events.c.id.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(stmt)]

    def all_decisions(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(select(decisions).order_by(decisions.c.at))]

    # ------------------------------------------------------------------ outbox

    def outbox_add(self, kind: str, target: str, payload: dict[str, Any], reference: str | None = None) -> int:
        now = time.time()
        with self.engine.begin() as conn:
            result = conn.execute(
                insert(outbox).values(kind=kind, target=target, reference=reference, payload=payload, status="pending", attempts=0, next_attempt_at=now, created_at=now)
            )
            return int(result.inserted_primary_key[0])

    def outbox_due(self, limit: int = 20) -> list[dict[str, Any]]:
        stmt = select(outbox).where(outbox.c.status == "pending", outbox.c.next_attempt_at <= time.time()).order_by(outbox.c.id).limit(limit)
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(stmt)]

    def outbox_update(self, item_id: int, **values: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(outbox).where(outbox.c.id == item_id).values(**values))

    def outbox_get(self, item_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(outbox).where(outbox.c.id == item_id)).first()
            return _row(r) if r else None

    def outbox_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(select(outbox).order_by(outbox.c.id.desc()).limit(limit))]

    # ------------------------------------------------------------------ sandbox portals

    def sandbox_add(self, portal: str, reference: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
        values = dict(portal=portal, reference=reference, status=status, payload=payload, received_at=time.time())
        with self.engine.begin() as conn:
            conn.execute(insert(sandbox_records).values(**values))
        return values

    def sandbox_get(self, portal: str, reference: str) -> dict[str, Any] | None:
        stmt = select(sandbox_records).where(sandbox_records.c.portal == portal, sandbox_records.c.reference == reference)
        with self.engine.connect() as conn:
            r = conn.execute(stmt).first()
            return _row(r) if r else None

    def sandbox_list(self, portal: str, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(sandbox_records).where(sandbox_records.c.portal == portal).order_by(sandbox_records.c.id.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(stmt)]

    # ------------------------------------------------------------------ stream consumers

    def checkpoints(self, source: str, stream: str) -> dict[str, dict[str, Any]]:
        stmt = select(stream_checkpoints).where(stream_checkpoints.c.source == source, stream_checkpoints.c.stream == stream)
        with self.engine.connect() as conn:
            return {r.shard: _row(r) for r in conn.execute(stmt)}

    def save_checkpoints(self, source: str, stream: str, positions: dict[str, str], closed: set[str] = frozenset()) -> None:
        """Upsert, synchronously: the caller acknowledges the stream only after this returns."""
        if not positions and not closed:
            return
        now = time.time()
        with self.engine.begin() as conn:
            for shard in set(positions) | set(closed):
                where = (stream_checkpoints.c.source == source, stream_checkpoints.c.stream == stream, stream_checkpoints.c.shard == shard)
                values: dict[str, Any] = {"updated_at": now}
                if shard in positions:
                    values["position"] = positions[shard]
                if shard in closed:
                    values["closed"] = 1
                if conn.execute(update(stream_checkpoints).where(*where).values(**values)).rowcount == 0:
                    conn.execute(insert(stream_checkpoints).values(source=source, stream=stream, shard=shard, position=positions.get(shard, ""), closed=int(shard in closed), updated_at=now))

    def acquire_lease(self, source: str, stream: str, owner: str, ttl: float) -> tuple[bool, str | None]:
        """Take or renew the lease. Returns (held, current owner). One conditional UPDATE,
        so two bridges racing for an expired lease cannot both win."""
        now = time.time()
        where = (stream_leases.c.source == source, stream_leases.c.stream == stream)
        with self.engine.begin() as conn:
            taken = conn.execute(
                update(stream_leases).where(*where, (stream_leases.c.owner == owner) | (stream_leases.c.expires_at < now)).values(owner=owner, expires_at=now + ttl)
            ).rowcount
            if taken:
                return True, owner
            holder = conn.execute(select(stream_leases.c.owner).where(*where)).scalar()
        if holder is None:
            try:
                with self.engine.begin() as conn:
                    conn.execute(insert(stream_leases).values(source=source, stream=stream, owner=owner, expires_at=now + ttl))
                return True, owner
            except Exception:  # another bridge inserted first
                with self.engine.connect() as conn:
                    holder = conn.execute(select(stream_leases.c.owner).where(*where)).scalar()
        return False, holder

    def release_lease(self, source: str, stream: str, owner: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(stream_leases).where(stream_leases.c.source == source, stream_leases.c.stream == stream, stream_leases.c.owner == owner).values(expires_at=0.0))

    def dead_letter(self, source: str, position: str | None, raw: bytes | str | None, error: str) -> None:
        """Once per position: a redelivered poison message is not recorded twice."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        values = dict(source=source, position=position, raw=(raw or "")[:20000], error=error[:1000], at=time.time())

        def job() -> None:
            with self.engine.begin() as conn:
                seen = position and conn.execute(
                    select(dead_letters.c.id).where(dead_letters.c.source == source, dead_letters.c.position == position).limit(1)
                ).first()
                if not seen:
                    conn.execute(insert(dead_letters).values(**values))

        self._writes.put(job)

    def dead_letters_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [_row(r) for r in conn.execute(select(dead_letters).order_by(dead_letters.c.id.desc()).limit(limit))]

    # ------------------------------------------------------------------ summary

    def counts(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            def count(table, *where) -> int:
                return int(conn.execute(select(func.count()).select_from(table).where(*where)).scalar() or 0)

            by_decision = {d: n for d, n in conn.execute(select(decisions.c.decision, func.count()).group_by(decisions.c.decision))}
            by_status = {s: n for s, n in conn.execute(select(outbox.c.status, func.count()).group_by(outbox.c.status))}
            return {
                "runs": count(runs),
                "auditEvents": count(audit_events),
                "decisions": by_decision,
                "agentActions": count(agent_actions),
                "outbox": by_status,
                "sandbox": {p: count(sandbox_records, sandbox_records.c.portal == p) for p in ("gateway", "cfcfrms")},
                "deadLetters": count(dead_letters),
            }


_STORE: Store | None = None
_LOCK = threading.Lock()


def get_store() -> Store:
    """Process-wide store; the bridge and the agent tools share it."""
    global _STORE
    with _LOCK:
        if _STORE is None:
            _STORE = Store()
        return _STORE
