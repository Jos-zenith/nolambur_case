# Trustify

**A payment aggregator's own risk layer for UPI.** It scores every payment as it arrives with rules and a graph neural network. It places graded holds on mule accounts, holds fake merchants' settlement payouts, and leaves a tamper-evident trail for every decision. It stops a scam campaign's later instalments and onward hops, because the first transfer is usually gone before anything can act.

[Live console](https://vict.onrender.com) · [Evidence report](Multi-GNN/reports/README.md) · codename *Operation Nolambur*

---

## The problem, in India's own numbers

| Figure | Value | Source |
|---|---|---|
| UPI fraud, FY 2023–24 | 13.42 lakh incidents, ₹1,087 crore | [Lok Sabha, 15 Dec 2025](https://madhyamamonline.com/india/upi-linked-frauds-amount-to-rs-805-crore-far-fy26-govt-1477281) |
| UPI fraud, FY 2024–25 | 12.64 lakh incidents, ₹981 crore (about ₹7,761 each) | same |
| UPI fraud, FY 2025–26 to November | 10.64 lakh incidents, ₹805 crore | same |
| UPI volume, FY 2024–25 | 185.9 billion transactions, ₹260.6 lakh crore, 84% of retail payments | [RBI Annual Report, via MediaNama](https://www.medianama.com/2025/05/223-upi-84-india-fy25-retail-payment-volume-rbi/) |
| UPI fraud rate | about 0.0007% of payments (1 in 147,000) | derived from the two rows above |
| All cyber-fraud losses, 2024 | ₹22,845.73 crore, up about 206% on 2023 (₹7,465 crore); 36.37 lakh incidents | [Lok Sabha, 22 Jul 2025](https://www.indiatvnews.com/technology/news/indians-lost-over-rs-22-845-crore-to-cyber-fraud-in-2024-incidents-skyrocket-by-206-government-2025-07-22-1000037) |
| Money saved through CFCFRMS (the 1930 helpline system) | over ₹5,489 crore, from 17.82 lakh complaints | same |
| I4C Suspect Registry (launched 10 Sep 2024) | 18.43 lakh suspect identifiers and 24.67 lakh Layer-1 mule accounts shared; 13 lakh+ transactions blocked; ₹8,031.56 crore saved | [The420.in, Dec 2025](https://the420.in/cybercrime-suspect-registry-8031-crore-saved-mha-i4c-fraud-block/) |
| RBI MuleHunter.AI | bank-side mule classifier, reported at 15–20+ banks by 2025 | [Business Standard](https://www.business-standard.com/amp/industry/banking/15-more-banks-to-adopt-rbi-s-mulehunter-fraud-detection-tool-by-october-125080101845_1.html), [MediaNama RTI](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/) |
| RBI compensation for a failed UPI payment not reversed in time | ₹100 a day (circular of 20 Sep 2019) | [MediaNama](https://www.medianama.com/2019/09/223-rbi-penalties-failed-transaction/) |
| Fraud analyst pay, India | ₹5.03 lakh a year on average | [Indeed India](https://in.indeed.com/career/fraud-analyst/salaries) |

**How a digital-arrest scam moves money.** A victim is kept on a video call by someone posing as an officer and pays in instalments of up to ₹1 lakh, NPCI's per-transfer cap for person-to-person payments. The money lands in a first-layer mule, which forwards it within minutes to a second layer that cashes out. Banks run MuleHunter.AI on their own accounts, and I4C shares mule identifiers. An aggregator sees something neither of them does: its own merchants' settlement accounts, onboarding records and payment-link traffic. Trustify is built for that view.

---

## Architecture

```
 payments ── webhook | Kafka | Kinesis | CSV replay
    │        ack only after the engine commits · back-pressure at 20,000 queued · dead-letter table
    ▼
 RAIL ENGINE  (Multi-GNN/rail_engine.py, FastAPI bridge, 0.5 s micro-batches)
    ├─ online GIN scorer ── each payment's 2-hop neighbourhood, 72 h window, no future edges
    ├─ rule detectors ───── P2P mule rules (r2.0 default; r2.1, r2.2 opt-in)
    ├─ decision router ──── alert only → delay settlement → hold outbound → full hold
    ├─ P2M service ──────── merchant detectors D1–D4 → settlement holds
    ├─ cases ────────────── linked accounts grouped, evidence packs
    └─ outbox ───────────── retried until confirmed: gateway webhook, 1930 report, SMS, registry
    ▼
 STORE  SQLite | Postgres: decisions, hash-chained audit, checkpoints, leases, dead letters
 GRAPH  in-memory | Neo4j
    ▼
 NEXT.JS CONSOLE  thin proxy at /api/rail/*; no number is computed in the browser
```

| Layer | Detail |
|---|---|
| **Ingest** (`infra/ingest.py`) | Kafka offsets and Kinesis checkpoints are committed only after the engine has processed the batch, so a crash replays rather than loses. Consumers pause at 20,000 queued payments. Malformed messages go to `ingest_dead_letters`. Kinesis has shard leases (`stream_leases`) and handles a reshard split by handing off to the child shards. Tested against a real Kafka 4.1.2 broker and a moto Kinesis mock. |
| **Scorer** (`infra/scorer.py`) | Exact mode recomputes each payment's 2-hop subgraph. Cached mode reuses layer-1 embeddings refreshed every 300 s: over 83,067 payments it moved no score across 0.5, with a largest difference of 0.020. The model's inputs are hour of day, log amount and channel only: no absolute timestamps, no states, no labels. |
| **Store** (`infra/store.py`) | Every decision is written to an append-only audit row whose SHA-256 hash covers the previous row's hash. `/rail/audit/verify` recomputes the chain and names the first altered row. Postgres keeps a single chain even with several writers. |
| **Access** (`infra/rbac.py`) | Roles: analyst (clear, escalate, investigate), supervisor (adds freeze, 1930 report, notify, override, decide appeals), admin (adds restart, registry import). The `X-Rail-Actor` header identifies the user. |
| **Integrations** (`infra/integrations.py`, `infra/sandbox.py`) | Sandboxed payment-gateway webhook, a mock CFCFRMS 1930 portal, a mock NPCI suspect registry, and SMS to an on-call officer. All go through the outbox. |
| **Company registry** (`infra/registry.py`) | MCA tables and loaders for data.gov.in exports: director (DIN) overlap, shared registered addresses, linked companies' settlement accounts. Ships empty; no synthetic company data. |
| **Feedback** (`infra/feedback.py`) | Analyst verdicts become labels for retraining into `models/feedback/`. |
| **Hosting** | Render: a Node web service for the console and a Python web service for the bridge, with Postgres for the audit trail. Measured peak memory is about 419 MB, against the 512 MB free tier. While the bridge sleeps, the console shows a captured snapshot of real bridge output. |

---

## Detection: person-to-person mule accounts

Rules sum over time windows, because a ₹5 lakh scam arrives as several transfers under the ₹1 lakh cap. A per-transfer threshold would either never fire or be trivially evaded.

| Detector | Fires when (rules r2.0) |
|---|---|
| **Inflow burst from new payers** | Over ₹1.5 lakh from first-time payers in 24 h, and at least 3× the account's busiest day in the last 7. That baseline counts only if the account was active on 5 of those 7 days, so a new mule can't raise its own bar. |
| **Rapid pass-through** | At least ₹1 lakh in, and 60% or more of it out again within 1, 6 or 24 h. Accounts that always forward half their inflow (shops paying suppliers) alert only at 3× their usual scale. |
| **Split under the UPI cap** | Three or more P2P transfers into one account in 24 h, each either ₹90,000–1,00,000 or a just-under amount like ₹49,999, from two or more payers with at least one new. Five or more makes it critical. |
| **Funds from a flagged account** | Money received from an account a primary rule flagged in the last 24 h, or from a restricted one. One hop only. |
| **Model lead** | The GIN scores a payment at or above 0.86, a threshold picked on validation days, and no rule has fired. A lead, not a finding. |

**Rules r2.1** (opt-in) followed the stress tests. It uses relative floors: ₹25,000 absolute, 3× the account's own busiest day, or the 95th percentile of its peers (₹28,000 for individuals, ₹94,000 for suppliers). It adds a fan-in detector: 5 or more new P2P payers in 24 h. **Rules r2.2** narrowed the hop rule to individuals, at least ₹6,100 flagged inflow, and at least 50% of inflow. It was judged once on a reserved data stream and failed by small margins, so it is not adopted.

**The decision router** turns alerts into action levels:

| Level | Action | Triggered by | Lifts after |
|---|---|---|---|
| 0 | Alert only | Model lead, or medium severity | — |
| 1 | Delay settlement | High severity, model below threshold | 1 h |
| 2 | Hold outbound transfers | High severity and model agrees, or critical | 24 h |
| 3 | Full hold pending a supervisor | Critical, model agrees, two or more detectors | 72 h |

Restrictions only escalate automatically. Lifting one is a person's decision, an expiry, or an appeal not decided within 24 h. An account an analyst has already cleared steps down a level next time.

---

## Detection: the merchant side (P2M)

An aggregator's real lever is the settlement payout. Parameters come from training days and clean merchants only.

| Detector | Fires when | Action |
|---|---|---|
| **D1 Big tickets** | 3 or more first-time payers at or above the category's 99th-percentile ticket in 24 h (₹1,207 for subscriptions to ₹49,298 for electronics) | Hold settlement 24 h |
| **D2 Payer spread** | First-time payers from 6 or more other states into a local-category merchant in 24 h | Hold settlement 24 h |
| **D3 Collect pattern** | 14 or more collect requests to non-customers in 24 h, with 69% or more declined or expired | Hold settlement 24 h |
| **D4 Shared settlement** | One settlement account behind merchants with different declared legal entities | Review only: legitimate family businesses look identical |

---

## The model and the data

- **Model:** GINe, a Graph Isomorphism Network with edge updates (PyTorch Geometric), trained only on the Nolambur data. It scores each payment on its 2-hop neighbourhood using only payments up to its own 5-second bucket. Subgraph scores match a full-graph pass to within 5e-21.
- **Dataset v2** (`nolambur_v2_gen.py`, seed 7): 10 days, 83,067 payments, 5,680 accounts, 419 fraud payments, ten scam campaigns. Victims pay at most ₹1 lakh per transfer and per day. Mules also shop, some are reused across campaigns, and the clean data includes look-alikes: shops forwarding to suppliers, landlords and employers.
- **Split:** fit on days 0–5, pick the threshold on days 6–7, report days 8–9 only. The test days hold two campaigns the model never saw.
- **Merchant dataset** (`p2m_gen.py`): fake merchants, collect scammers, settlement rings, and legitimate family businesses that share bank accounts.

---

## What the evidence says

Every test below had its protocol written down before the data it was judged on. Failures are published alongside passes. Full detail: [evidence report](Multi-GNN/reports/README.md).

**On held-out synthetic days:**

| Measure | Result |
|---|---|
| Model per payment | ROC AUC 0.999, average precision 0.93; precision 96% (86–99%), recall 79% (67–88%) |
| Mules caught, rules + model | **58–77%** across fresh draws |
| Alerted accounts that are mules | **58–78%** (r2.0) |
| Warning before money leaves a mule | 17 s to 4 h; fast mules give 37 s |
| Fraud money stopped by holds alone | 11–19%: later instalments and onward hops, not the first transfer |
| Innocent accounts restricted (full replay) | 0 of 27 held accounts. The ₹33.5k of "genuine" money stopped was 44 everyday payments by held mules |
| Fake merchants flagged before their first settlement | all, in every draw; 63–68% of their money held; hold detectors 100% precise |

**Stress tests that found the limits:**
- **Without amount, the model collapses** (average precision 0.02–0.05). It learns amount in context: on forwarding hops it beats amount-only and tabular models, with average precision 0.93 against 0.49 and 0.38.
- **Structuring into ₹2,000–5,000 payments evades r2.0.** r2.1 raised recall from 33% to 94%, at three times the false alerts (6.2 to 18 a day).
- **Rings paying a median below about ₹2,500 evade everything**, even a retrained model.

**On real data this project did not generate** (Elliptic: 203,769 real Bitcoin transactions, temporal split, pass marks fixed from [Weber et al. 2019](https://arxiv.org/abs/1908.02591) before the data was opened):

| Model | Illicit F1 |
|---|---|
| Random Forest on each transaction's own features | **0.742** |
| Random Forest + GIN embeddings | 0.556 |
| GIN | 0.323 (needed 0.628) |
| GIN + hop rule | 0.280 |

The graph model failed all three marks. After a dark market shut down mid-test, every model's F1 fell below 0.06.

**Break-even, priced with the figures at the top.** Per alert, value = precision × money saved − review cost − wrong-hold cost. A confirmed mule is worth about ₹17,400 saved (₹1.16 lakh through an average mule × 15% stopped), and a review costs about ₹123. With a review budget of 50 accounts a day, break-even precision is **about 2.7%** (1.3–6.0% across 200,000 Monte Carlo draws). At the real UPI fraud rate, about 500× rarer than in the synthetic data, the projected precision of the account queue is 0.4%. That is not worth running as designed. At 6% precision the queue pays in 9 cases out of 10.

**So the defensible claim is narrower than "a GNN catches mules":** rules, features and the hold policy do the work, and the graph model is a secondary signal. Throughput is not the constraint: 4,900–6,150 payments a second on a 15 W laptop, scored 0.3–0.7 s after arrival.

---

## The console

| Page | What it shows |
|---|---|
| **Overview** | Live replay labelled as a full-dataset replay, money trails case by case, a test scam you can send through the real ingest path, results with ranges and limits |
| **Alert queue** | Ranked alerts, the plain-words reason each fired, money trail, evidence rows; clear, escalate or freeze, each with a written reason |
| **Onboarding** | A new merchant's settlement VPAs checked for direct or second-hop links to flagged accounts; company checks by CIN and DIN |
| **Merchants** | The P2M replay: merchant alerts and settlement holds |
| **Cases** | Evidence packs, 1930 reports, officer notifications |
| **Model** | Training, held-out evaluation, precision@k, workload per analyst, the cost of holds |
| **Platform** | Health of ingest, graph, store, integrations and registry; audit-chain verification |

**Stack:** PyTorch Geometric · FastAPI · SQLAlchemy (SQLite, Postgres) · Kafka · Kinesis · Neo4j · Next.js · Tailwind · Zustand · d3 · Render.
