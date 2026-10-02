# Trustify

**A risk layer for a payment aggregator: rules, a graph model and graded holds that stop UPI mule chains. Each claim is tested, including where it fails.**

[Live demo](https://vict.onrender.com) · [Evidence report](Multi-GNN/reports/README.md) · codename *Operation Nolambur*

> Results come from synthetic data plus one real dataset (Elliptic). None come from live UPI traffic. That needs a shadow pilot.

## What it does

| | |
|---|---|
| **Detect mules (P2P)** | Four rule detectors (new-payer bursts, rapid pass-through, splitting under the UPI cap, money from a flagged account), plus leads from a GIN graph model |
| **Act in steps** | Delay settlement, hold outbound, full hold. Holds expire on their own; an appeal not decided in 24 h releases the account |
| **Merchant side (P2M)** | Hold the settlement of fake merchants; send shared settlement accounts to review |
| **Case work** | Cases, evidence packs, 1930 reports (sandboxed), role-based access, hash-chained audit trail |

## What the evidence says

| Test | Result |
|---|---|
| Held-out synthetic days (rules + model) | 58–77% of mules caught, 58–78% of alerts are mules, 17 s – 4 h of warning |
| Fake merchants (synthetic) | All flagged before their first settlement; 63–68% of their money held |
| **Real data: Elliptic Bitcoin, temporal split** | **The graph model failed all 3 pre-registered marks.** A Random Forest on each transaction's features scored F1 0.74; the GIN 0.32 |
| **Break-even, from reported Indian figures** | **The queue pays only above ~2.7% precision (6% for 90% confidence).** At the real UPI fraud rate the projected precision is 0.4% |
| Throughput (laptop) | 4,900–6,150 payments a second, scored 0.3–0.7 s after arrival |

**So the case is narrower than "a GNN catches mules".** Rules, features and the hold policy do the work, and the graph model is a secondary signal. A pilot passes only if precision within the daily review budget clears break-even.

Every test was pre-registered: its protocol was written down before the data it was judged on. Failures are published: rules r2.2 missed its marks, and so did the GIN on Elliptic.

## How it is built

```
payments (webhook | Kafka | Kinesis | replay)
  → rail engine: rules + GIN scorer (2-hop, time-respecting) → decision router → holds
  → outbox: gateway, 1930, SMS (sandbox) · store: SQLite/Postgres · graph: memory/Neo4j
  → Next.js console (thin proxy, no browser-side data)
```

Scoring runs off the payment path. An inline gate inside the path is designed but not built.

## Run it

```bash
cd Multi-GNN && RAIL_SOURCE=replay python bridge_api.py   # :8001, ready in about a minute
pnpm install && pnpm dev                                  # :3000
python -m pytest Multi-GNN/tests                          # tests
```

Settings: `RAIL_SOURCE` (webhook, replay, kafka, kinesis) · `RAIL_GRAPH` (memory, neo4j) · `RAIL_DB_URL` (SQLite or Postgres) · `RAIL_RULES` (r2.0, r2.1) · `RAIL_AUTO_HOLD` (on, off).

Stack: PyTorch Geometric, FastAPI, SQLAlchemy, Next.js, Tailwind, d3, hosted on Render.

## Next

1. A 30-day shadow pilot on one partner's anonymised flows. It passes only on precision within the review budget, recall and lead time, against marks fixed in advance.
2. The IBM AML half of the external test, which needs a GPU.
3. Drift monitoring. Elliptic showed every model collapsing when a dark market shut down.
