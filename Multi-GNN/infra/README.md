# infra: platform adapters for the rail engine

Each piece runs locally with no extra services, and switches to a production backend by env var on the bridge (full list in `settings.py`).

| Piece | Default | Production switch | Module |
|---|---|---|---|
| Payment ingest | CSV replay, plus `POST /rail/ingest/payments` | `RAIL_SOURCE=webhook \| kafka \| kinesis` | `ingest.py` |
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
# stream mode: no replay; the clock is event time from incoming payments
RAIL_SOURCE=webhook python bridge_api.py
python -m infra.producer webhook --speed 0 --from 2024-03-15T10:00 --limit 3000

# feedback labels from analyst decisions, then retrain into models/feedback/
python -m infra.feedback report
python -m infra.feedback retrain --epochs 10
```

## Design notes

- **Ingest.** Every source feeds one inbox. Each 0.5 s tick drains up to 2,000 payments and scores them with the GNN in one `/predict` splice onto the background graph. Delivery is at least once; the engine drops a `txn_id` it has already seen. Payments carry no labels. Truth is looked up by account id, so precision and recall still work when the CSV is streamed in. Webhook HMAC is enforced when `RAIL_WEBHOOK_SECRET` is set.
- **Graph.** Detectors keep using in-memory indexes, since a database round trip on every payment would cap throughput. The graph store serves the fan-out queries: onboarding 2-hop checks and `GET /rail/graph/downstream/{account}?hops=N`. Those return time-respecting paths that skip blocked transfers. Neo4j writes are batched per tick. A replay reset wipes the namespace; a live graph keeps its history across restarts.
- **Store.** Hot-path writes go through one writer thread. Decisions (`clear` = false positive, `freeze` = confirmed) are the feedback labels. `GET /rail/audit?run=all` spans restarts. Each alert shows earlier decisions on its account.
- **Outbox.** Every outbound call is written first and delivered by a worker with exponential backoff (up to 6 attempts) and an `Idempotency-Key`. Pending rows survive a crash and resume on the next start.
- **Feedback.** On Nolambur every edge already has a ground-truth label, so feedback can only agree with it or overwrite it; `report` shows which. Retraining never replaces the live checkpoint.

- **Auto-hold.** A critical alert that the model scores at 0.9 or above holds the account. Its transfers are blocked like a freeze, but no bank instruction is sent. A supervisor confirms (freeze) or releases (clear). On the full replay the policy holds 34 accounts, all of them labelled mules, and blocks ₹1.68 Cr of the ₹7.93 Cr of fraud with no genuine payments blocked. The median time from first evidence to hold is 80 s. Most fraud money is victims' first transfers, which arrive before any alert can exist.
- **Roles.** `X-Rail-Actor` is checked by the bridge on every action. Analysts clear, escalate and investigate. Supervisors also freeze, file 1930 reports, notify, and override the model (release a hold, or clear a score ≥ 0.9). Admins can also restart. There is no login: in production an auth proxy would set the header.
- **Audit integrity.** `audit_events` is append-only through database triggers, and each row carries a hash of the row before it (a hash chain). `GET /rail/audit/verify` recomputes the chain. On Postgres an advisory lock keeps concurrent writers on one chain; on SQLite, run one bridge per database file.

## Verified here vs. not

These were run end to end on this machine: the webhook, the SQLite store, the in-memory graph, the outbox against the sandbox, and the feedback build. The Kafka, Kinesis, Neo4j/Memgraph and Postgres adapters are written against the documented driver APIs, but have not been run against live servers.
