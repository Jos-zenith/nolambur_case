# infra: platform adapters for the rail engine

Each piece runs locally with no extra services, and switches to a production backend by env var on the bridge (full list in `settings.py`).

| Piece | Default | Production switch | Module |
|---|---|---|---|
| Payment ingest | live webhook, `POST /rail/ingest/payments` | `RAIL_SOURCE=kafka \| kinesis`; `RAIL_SOURCE=replay` for the CSV demo | `ingest.py` |
| Company / director registry | empty; load MCA files | `MCA_PROVIDER=http`, `MCA_API_URL`, `MCA_API_KEY` | `registry.py` |
| Graph for multi-hop queries | engine's in-memory adjacency | `RAIL_GRAPH=neo4j` (Neo4j or Memgraph over Bolt) | `graph.py` |
| Audit trail, decisions | SQLite at `Multi-GNN/data/rail.db` | `RAIL_DB_URL=postgresql+psycopg://…` | `store.py` |
| Freeze → bank gateway | bridge's `/sandbox/gateway` | `GATEWAY_WEBHOOK_URL`, `GATEWAY_WEBHOOK_SECRET` | `integrations.py`, `sandbox.py` |
| 1930 complaint | bridge's `/sandbox/cfcfrms` (mock, not I4C's schema) | `CFCFRMS_URL` | same |
| NPCI suspect registry | bridge's `/sandbox/npci` (answer derived from the label) | `NPCI_REGISTRY_URL` | `sandbox.py` |
| Automatic hold | on | `RAIL_AUTO_HOLD=off` | `rail_engine.py` |
| Roles | 4 demo users | `RAIL_USERS='{"name":"role"}'` | `rbac.py` |
| SMS | Twilio dry run | `TWILIO_*` (unchanged, `agents/notifications.py`) | |
| Feedback → retrain | CLI | | `feedback.py` |

Optional drivers (only for the backend you pick): `pip install aiokafka kafka-python boto3 neo4j "psycopg[binary]"`. SQLAlchemy is required.

## Try it

```bash
cd Multi-GNN
# live (the default): the clock is event time from incoming payments
python bridge_api.py
python -m infra.producer webhook --speed 0 --from 2024-03-15T10:00 --limit 3000

# the recorded demo: replay nolambur_transactions.csv with full-graph scores
RAIL_SOURCE=replay python bridge_api.py

# Kafka: consumer group nolambur-rail on topic upi.payments
RAIL_SOURCE=kafka KAFKA_BOOTSTRAP=localhost:9092 python bridge_api.py
python -m infra.producer kafka --speed 0 --limit 3000

# MCA registry: load files, then give onboarding a CIN
python -m infra.registry load companies     Company_Master_Maharashtra.csv   # data.gov.in download
python -m infra.registry load directorships signatories.csv                  # CIN, DIN, name, designation, dates
python -m infra.registry load disqualified  disqualified_directors.csv       # s.164(2) lists
python -m infra.registry load accounts      merchant_settlement_vpas.csv     # CIN -> settlement VPA
python -m infra.registry report U72900MH2021PTC123456
python -m pytest tests -q

# feedback labels from analyst decisions, then retrain into models/feedback/
python -m infra.feedback report
python -m infra.feedback retrain --epochs 10
```

## Design notes

- **Ingest.** Every source feeds one inbox. Each 0.5 s tick drains up to 2,000 payments and scores them with the GNN in one `/predict` splice onto the background graph. Payments carry no labels. Truth is looked up by account id, so precision and recall still work when the CSV is streamed in. Webhook HMAC is enforced when `RAIL_WEBHOOK_SECRET` is set.
- **Delivery guarantees.** At least once, end to end. A consumer's batch carries an ack that the service calls only after the engine has ingested it. Only then does Kafka commit the partition offset, or Kinesis write the shard's sequence number to `stream_checkpoints`. A crash before that re-reads the batch on restart. Within a run the engine drops a `txn_id` it has already seen. Above 20,000 queued payments, Kafka partitions are paused (the consumer stays in its group) and Kinesis stops polling. The webhook answers 429. A message that fails to parse or validate goes to `ingest_dead_letters` with its position, and is acked so it cannot block a partition.
- **Kinesis resharding.** Shards are re-listed every 30 s and when one closes. A child shard is read only after its parents have been read to the end and acked, so records for one key stay in order. One bridge per stream: there are no KCL-style leases for sharing shards between consumers.
- **Registry.** MCA tables live in the same database as the audit store. The checks are: disqualified or over-limit directors (s.164, s.165); struck-off, dormant, very young or non-filing companies; groups of companies sharing two or more directors, incorporated close together; registered-address farms (exact match after normalisation, so another office number in the same building does not match); and any company linked by a director or an address whose settlement VPA is under alert, held or frozen here. A high finding means hold, a medium one means review. Onboarding can record the applicant's VPAs against its CIN, which is what lets the next linked applicant be caught.
- **Graph.** Detectors keep using in-memory indexes, since a database round trip on every payment would cap throughput. The graph store serves the fan-out queries: onboarding 2-hop checks and `GET /rail/graph/downstream/{account}?hops=N`. Those return time-respecting paths that skip blocked transfers. Neo4j writes are batched per tick. A replay reset wipes the namespace; a live graph keeps its history across restarts.
- **Store.** Hot-path writes go through one writer thread. Decisions (`clear` = false positive, `freeze` = confirmed) are the feedback labels. `GET /rail/audit?run=all` spans restarts. Each alert shows earlier decisions on its account.
- **Outbox.** Every outbound call is written first and delivered by a worker with exponential backoff (up to 6 attempts) and an `Idempotency-Key`. Pending rows survive a crash and resume on the next start.
- **Feedback.** On Nolambur every edge already has a ground-truth label, so feedback can only agree with it or overwrite it; `report` shows which. Retraining never replaces the live checkpoint.

- **Auto-hold.** A critical alert that the model scores at 0.9 or above holds the account. Its transfers are blocked like a freeze, but no bank instruction is sent. A supervisor confirms (freeze) or releases (clear). On the full replay the policy holds 34 accounts, all of them labelled mules, and blocks ₹1.68 Cr of the ₹7.93 Cr of fraud with no genuine payments blocked. The median time from first evidence to hold is 80 s. Most fraud money is victims' first transfers, which arrive before any alert can exist.
- **Roles.** `X-Rail-Actor` is checked by the bridge on every action. Analysts clear, escalate and investigate. Supervisors also freeze, file 1930 reports, notify, and override the model (release a hold, or clear a score ≥ 0.9). Admins can also restart. There is no login: in production an auth proxy would set the header.
- **Audit integrity.** `audit_events` is append-only through database triggers, and each row carries a hash of the row before it (a hash chain). `GET /rail/audit/verify` recomputes the chain. On Postgres an advisory lock keeps concurrent writers on one chain; on SQLite, run one bridge per database file.

## Verified here vs. not

These were run end to end on this machine: the webhook, the SQLite store, the in-memory graph, the outbox against the sandbox, and the feedback build.

Kafka was run against a real Apache Kafka 4.1.2 broker (single node, KRaft) with a 3-partition topic:
- Consumer crash, rebalance and restart: no payment lost. Redelivery happened only for batches that were processed but not acked. The final restart re-read nothing.
- Poison messages were dead-lettered.
- Bridge end to end: 3,000 CSV payments produced, consumed, scored and alerted on.
- Bridge killed mid-stream and restarted: all 9,000 offsets committed, lag 0.

Kinesis was run against moto's Kinesis server, an emulator, not AWS:
- Crash and restart: the same no-loss and redelivery results as Kafka.
- Checkpoints resumed and poison messages were dead-lettered.
- moto does not close a shard after a split, so the parent-then-child handoff has not been exercised.

The registry was tested with invented fixtures laid out like the real headers (`tests/test_registry.py`), and through the bridge's HTTP endpoints. The vendor API client (`MCA_PROVIDER=http`) was tested only against a stub. Neo4j/Memgraph and Postgres have still not been run against live servers.
