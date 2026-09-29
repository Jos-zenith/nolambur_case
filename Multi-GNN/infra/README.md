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
| GNN scoring | incremental 2-hop subgraph, exact | cached layer-1 embeddings (`OnlineScorer(mode="cached")`) | `scorer.py` |
| Dataset | v2 (10 days, temporal split) | `NOLAMBUR_DATASET=v1` for the original file | `../nolambur_v2_gen.py` |
| Graded actions | on (decision router) | `RAIL_AUTO_HOLD=off` = alert only | `rail_engine.py` |
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

# the recorded demo: replay nolambur_v2/transactions.csv with time-respecting online scores
RAIL_SOURCE=replay python bridge_api.py

# v2 from scratch: generate, format, train on days 0-5, verify and precompute the online scores
python nolambur_v2_gen.py
python prepare_datasets.py --nolambur-only --dataset v2
NOLAMBUR_EDGE_FEATURES="HourOfDay,LogAmount,Payment Format" python finetune_local_nolambur.py --dataset v2 --finetune-epochs 12
python -m infra.scorer verify --dataset v2         # subgraph scores == full-graph scores
python -m infra.scorer precompute --dataset v2     # nolambur_v2/online_scores.npy
python -m infra.scorer compare --dataset v2 --refresh 300   # cached vs exact

# load test (reports/loadtest*.json; the model page shows them)
python -m infra.loadtest engine --tps 1000 2000 5000 --seconds 20 [--scoring cached]

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

- **Ingest.** Every source feeds one inbox. Each 0.5 s tick drains up to 2,000 payments and scores them in one micro-batch with the incremental scorer (`scorer.py`). Payments carry no labels. Truth is looked up by account id, so precision and recall still work when the CSV is streamed in. Webhook HMAC is enforced when `RAIL_WEBHOOK_SECRET` is set.
- **Delivery guarantees.** At least once, end to end. A consumer's batch carries an ack that the service calls only after the engine has ingested it. Only then does Kafka commit the partition offset, or Kinesis write the shard's sequence number to `stream_checkpoints`. A crash before that re-reads the batch on restart. Within a run the engine drops a `txn_id` it has already seen. Above 20,000 queued payments, Kafka partitions are paused (the consumer stays in its group) and Kinesis stops polling. The webhook answers 429. A message that fails to parse or validate goes to `ingest_dead_letters` with its position, and is acked so it cannot block a partition.
- **Kinesis resharding.** Shards are re-listed every 30 s and when one closes. A child shard is read only after its parents have been read to the end and acked, so records for one key stay in order.
- **Several bridges on one Kinesis stream.** Bridges that share a database take a lease on the stream (`stream_leases`), and only the holder reads. The others show `standby` on the platform page. When the holder stops renewing, another takes over within 30 s and resumes from the checkpoints. Batches the old holder had in flight may be read twice, but none are lost. Shards are not divided between bridges the way the KCL does, so one bridge's throughput is the ceiling. With separate SQLite files there is nothing shared to lease on, so use Postgres for more than one bridge. Kafka needs none of this: its consumer group divides the partitions.
- **Registry.** MCA tables live in the same database as the audit store. The checks are: disqualified or over-limit directors (s.164, s.165); struck-off, dormant, very young or non-filing companies; groups of companies sharing two or more directors, incorporated close together; registered-address farms (exact match after normalisation, so another office number in the same building does not match); and any company linked by a director or an address whose settlement VPA is under alert, held or frozen here. A high finding means hold, a medium one means review. Onboarding can record the applicant's VPAs against its CIN, which is what lets the next linked applicant be caught.
- **Graph.** Detectors keep using in-memory indexes, since a database round trip on every payment would cap throughput. The graph store serves the fan-out queries: onboarding 2-hop checks and `GET /rail/graph/downstream/{account}?hops=N`. Those return time-respecting paths that skip blocked transfers. Neo4j writes are batched per tick. A replay reset wipes the namespace; a live graph keeps its history across restarts.
- **Store.** Hot-path writes go through one writer thread. Decisions (`clear` = false positive, `freeze` = confirmed) are the feedback labels. `GET /rail/audit?run=all` spans restarts. Each alert shows earlier decisions on its account.
- **Outbox.** Every outbound call is written first and delivered by a worker with exponential backoff (up to 6 attempts) and an `Idempotency-Key`. Pending rows survive a crash and resume on the next start.
- **Feedback.** On Nolambur every edge already has a ground-truth label, so feedback can only agree with it or overwrite it; `report` shows which. Retraining never replaces the live checkpoint.
- **Scoring.** GINe with two layers and no reverse message passing scores edge u→v from the layer-2 embeddings of u and v. Those depend only on the in-edges of u and v and the in-edges of their in-neighbours. `OnlineScorer` keeps a 72-hour rolling graph with per-node in-edge lists and runs the model on exactly that subgraph for each micro-batch. It matches a full-graph pass to 1e-20 (`verify`). A score only ever sees earlier payments. The cost grows with the square of an account's degree, because a payment to a merchant pulls in its customers and their payers. `mode="cached"` refreshes every node's layer-1 embedding periodically and computes only the 1-hop part fresh; `compare` measures what that costs in accuracy. A 72-hour window at 1,000 TPS is about 260 million edges, which one process cannot hold: at that volume the scorer has to be sharded by account.
- **Model inputs.** Time of day, log amount and channel (P2P or P2M), z-normalised with the training split's statistics (saved in the checkpoint's `.norm.json`). The node feature is the z-normalised constant, which is 0. The old bridge fed 1, so v1's served scores came from inputs the model was never trained on.
- **Rules r2.0.** UPI caps a P2P transfer at ₹1 lakh, so large sums arrive as several transfers. The rules therefore sum over windows instead of testing single transfers:
  - inflow from first-time payers over 24 h and 72 h, above ₹1.5 lakh or 3× the account's busiest day in the last 7 (the baseline counts only once the account has been active 5 of those 7 days, so a mule cannot raise its own bar by drip-feeding itself);
  - structuring: 3+ transfers near the cap or at just-under amounts, from 2+ payers;
  - pass-through over 1 h, 6 h and 24 h, where an established forwarder alerts only at 3× its usual scale;
  - a hop from a flagged account;
  - model-only leads above the threshold picked on the validation days.

  `tests/test_rules_and_ladder.py` plays an adversary against these, and states what still gets through: ₹1.45 lakh once from two payers, half of it forwarded, fires nothing.
- **Decision router and graded actions.** The router works per account: its strongest open rule alert, whether the model agrees, and how many detectors agree.

  | Level | Action | Triggered by | Lifts after |
  |---|---|---|---|
  | 0 | Alert only | medium severity, or a model-only lead | — |
  | 1 | Delay settlement: outgoing transfers are queued, then cancelled if it escalates | high severity | 1 h |
  | 2 | Hold outbound: out blocked, in allowed | high + model, or critical | 24 h |
  | 3 | Full hold, pending a supervisor | critical + model + two detectors | 72 h |

  An account an analyst has cleared before steps down one level. A restriction lifts itself at its time limit unless a supervisor freezes the account; the alert then goes back to the queue. An appeal (recorded by an analyst, decided by a supervisor) must be decided within 24 h, or the restriction lifts. Restricted accounts keep collecting alerts, which is how a hold escalates.
- **Evaluation.** v2 is split by day: train on 0–5, threshold on 6–7, report 8–9. Model: ROC AUC, average precision, and precision/recall at the chosen threshold with 95% Wilson intervals. Rules: account-level metrics, precision@k of the queue, alerts per analyst per day (`RAIL_ANALYSTS`), and the lead-time distribution. Policy: money blocked, recovered from delays, and lost; genuine money blocked or delayed; and innocent accounts restricted, in account-hours.
- **Roles.** `X-Rail-Actor` is checked by the bridge on every action. Analysts clear, escalate, investigate and record appeals. Supervisors also freeze, file 1930 reports, notify, decide appeals and override (lift a restriction, or clear a model-flagged alert). Admins can also restart and load registry files. There is no login: in production an auth proxy would set the header.
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
- moto does not close a shard after a split, so resharding is covered by `tests/test_kinesis.py` instead. Its fake client follows AWS's documented split behaviour. The tests cover: parent read to the end before any child; children wait while parent records are unacked; a restart mid-handoff resumes after the last acked parent record; and lease standby and takeover. Two deliberate code mutations were each caught by these tests. None of this has run against real AWS Kinesis.

The registry was tested with invented fixtures laid out like the real headers (`tests/test_registry.py`), and through the bridge's HTTP endpoints. The vendor API client (`MCA_PROVIDER=http`) was tested only against a stub.

Postgres was run against a real PostgreSQL 16.2 server (the `pgserver` package's bundled binaries):
- The audit chain verified across 150 rows written concurrently by two stores (the advisory lock).
- The append-only triggers blocked UPDATE and DELETE.
- Checkpoints, leases, dead-letter de-duplication, decisions, the outbox, and the registry's ON CONFLICT upserts all worked.

This found one bug: the audit hash depended on whether a caller passed `0` or `0.0`, which Postgres returns differently. That is fixed. Neo4j/Memgraph has still not been run against a live server.
