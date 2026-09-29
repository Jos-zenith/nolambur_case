# Evidence report: what the rail engine achieves, measured honestly

Every number here comes from a JSON file in this folder, written by the code that measured it. The bridge serves the same files, and the console's Model page shows them.

| File | Written by |
|---|---|
| `evaluation_v2.json` | `rail_engine.evaluate` (the bridge's `/rail/evaluation`) |
| `scorer_compare.json` | `python -m infra.scorer compare` |
| `loadtest.json`, `loadtest_cached.json` | `python -m infra.loadtest engine [--scoring cached]` |
| `loadtest_http.json` | `python -m infra.loadtest http` |

**The data is synthetic.** Nothing here is evidence about real payment traffic. The only such evidence would come from shadow mode on a partner's anonymised flows (see the end of this report).

## 1. How it was measured

**The dataset.** `nolambur_v2_gen.py` (seed 7) generates 10 days of UPI traffic: 83,067 payments, of which 419 are fraud (0.50%).
- There are ten scam campaigns.
- Victims pay in transfers of at most ₹1 lakh, the NPCI per-transaction limit for person-to-person payments, and at most ₹1 lakh a day. They often pay just under the cap.
- Mules also make ordinary payments, and some are reused across campaigns.
- Clean look-alikes are included: shops that forward most of their takings to suppliers, landlords, and employers.

The first dataset, v1, could not support a temporal test, because all 353 of its fraud edges fall in one 4.5-minute window.

**The split.** Train on days 0–5, pick the model's alert threshold on days 6–7 (maximum F1, which gave 0.86), and report days 8–9 only. The test days contain two campaigns the model never saw.

**The scoring.** Each payment is scored on its own 2-hop subgraph, using only payments up to its 5-second bucket (`infra/scorer.py`).
- The model's inputs are hour of day, log amount and channel. There are no absolute timestamps, no states and no labels.
- The subgraph scores equal a full-graph forward pass to within 5e-21 (`scorer verify`).

**Uncertainty.** The test days hold only 57 fraud payments and 26 active mule accounts, so proportions are given with 95% Wilson intervals.

## 2. Results on the test days (days 8–9)

**Model, edge level.** 16,301 payments, 57 of them fraud.

| Measure | Value |
|---|---|
| ROC AUC | 0.999 |
| Average precision | 0.93 |
| At the chosen threshold (0.86) | 45 true positives, 2 false positives, 12 missed |
| Precision | 0.96 (95% CI 0.86–0.99) |
| Recall | 0.79 (95% CI 0.67–0.88) |
| Fraud share of the top 25 / 50 / 100 payments by score | 100% / 94% / 55% |

**Rules r2.0 and the analyst queue, account level.** 26 mules were active on the test days.

| | Precision | Recall |
|---|---|---|
| Rules only | 15 / 22 = 68% (47–84%) | 15 / 26 = 58% (39–74%) |
| Rules + model leads | 20 / 29 = 69% (51–83%) | 20 / 26 = 77% (58–89%) |

- **Queue quality.** Precision@5 is 100%, @10 is 100%, @20 is 75%.
- **Workload.** 14.5 accounts a day, or 7.2 per analyst for a team of two.
- **Lead time**, from first alert to the first time fraud money left that mule:
  - median 3.2 h; p10 −25 min (alerted after the money started moving)
  - 10 of 13 mules alerted before any money left
  - p90 is 8 days: mules reused from an earlier campaign were already flagged then
- **Time to alert**, from a mule's first fraud inflow: median 0 s, p90 46 min.
- **By detector:** pass-through 5 accounts (all mules), hop-from-flagged 17 (10 mules), model-only leads 14 (12 mules), inflow-from-new-payers 1. Structuring fired on none on the test days.

**Graded actions, with the router acting alone and nobody deciding.**
- 4 accounts were put on hold-outbound, all of them mules. No innocent account was restricted.
- ₹2.76 lakh of ₹16.6 lakh fraud was stopped (17%).
- ₹6,640 of genuine money was blocked: purchases from the held mules' own accounts.
- All 4 holds lifted at their 24-hour limit, because nobody confirmed them.

Most fraud money is lost because the victims' first transfers arrive before any alert can exist. The value of holds is in stopping onward movement, and that value depends on analysts confirming them.

## 3. Throughput and latency

**Hardware.** 12th Gen Intel Core i7-1255U, a 15 W laptop chip with 10 cores and 12 threads, 15.7 GB RAM, torch on CPU. A laptop, not a server: read these as a floor.

**Method.** Payments are resampled from the v2 accounts and spread over one copy of the account space per 100 TPS. Each copy is seeded with its last 72 hours of history, so every 2-hop neighbourhood is realistic. Processing runs in 0.5-second micro-batches, as the bridge does.

**Exact 2-hop scoring vs cached scoring.** Cached scoring refreshes layer-1 embeddings every 300 s and computes the 1-hop part fresh.

| Target TPS | Accounts | Sustained, exact | Payment latency p50 / p99, exact | Sustained, cached | Payment latency p50 / p99, cached |
|---|---|---|---|---|---|
| 1,000 | 55,558 | 1,545 | 541 / 757 ms | 6,151 | 322 / 425 ms |
| 2,000 | 111,046 | 2,289 | 642 / 947 ms | 4,933 | 428 / 481 ms |
| 5,000 | 277,651 | 1,830 (falls behind) | 1,594 / 2,428 ms | 5,395 (on average; p99 batch 698 ms, over the 500 ms tick) | 674 / 948 ms |

Payment latency is half a tick of batching (250 ms) plus the batch's processing time. One cache refresh takes 1.0 s at 1.2 M edges, once every 5 minutes.

**What caching costs in accuracy.** Measured over all 83,067 payments against exact scoring:

| Refresh interval | Largest score difference | Mean difference | Payments changing side of 0.5 |
|---|---|---|---|
| 60 s | 0.0067 | 4e-7 | 0 |
| 300 s | 0.020 | 2e-6 | 0 |

**Over HTTP.** Webhook traffic went into a live bridge with cached scoring and no seeded history. The load client ran on the same laptop.

| Target TPS | Ingested TPS | HTTP p50 / p99 | Sent → ingested p50 / p99 |
|---|---|---|---|
| 1,000 | 976 | 6 / 128 ms | 351 / 517 ms |
| 2,000 | 1,964 | 5 / 132 ms | 357 / 674 ms |
| 5,000 | 2,561 (falls behind: no loss, growing lag) | 5 / 339 ms | 7.2 / 18.9 s |

**Limits.**
- **One process holds the whole 72-hour window.** At 1,000 TPS that window is about 260 million edges. At that volume the scorer has to be sharded by account (payer and payee), and the rules' per-account state sharded with it.
- **The rules run in-process.** A Flink or Redis-windowed version would put the same windows on a key-partitioned stream.

## 4. What this does not show

- **Synthetic data.** Clean payments are mostly small (median about ₹600) while scam transfers run ₹10,000 to ₹1 lakh, so amount still carries much of the signal. The rules were written by someone who knew how the generator works.
- **The test set is small.** Two campaigns, 26 mules. The intervals above are wide for that reason.
- **The graph is incomplete.** A payment aggregator sees only its own merchants' flows, while mule chains cross banks and PSPs. This engine sees one slice of the graph.

**Shadow mode is the test that is missing.** Run the engine silently on one partner's anonymised flows for a few weeks. Log every alert and every would-be restriction. Then compare against the fraud reports and chargebacks that arrive later. That measures precision, recall and lead time on real traffic. Nothing here does.

## 5. Where this fits

The engine is meant as a payment aggregator's own risk layer, one that feeds the wider effort rather than competing with it:

- **RBI Innovation Hub's MuleHunter.AI** classifies mule accounts inside banks. By 2025 it was reported to be in use at 15 to 20 or more banks. An aggregator sees merchant-side flows that a bank does not: settlement VPAs, merchant onboarding, and payment-link traffic. Alerts from this engine are candidates to share with partner banks. They are not a replacement for bank-side models.
- **I4C's Suspect Registry**, launched September 2024 and shared with banks and payment intermediaries, lists identifiers linked to cyber fraud. This engine consumes such a registry (the `NPCI_REGISTRY_URL` adapter; a mock here), and its confirmed freezes and 1930 reports are what feed it.
- **The Financial Fraud Risk Indicator (FRI).** Reported sources disagree on who runs it: one attributes it to RBI; it was rolled out in May 2025 and is described as scoring risk before money moves. Treat it as another input signal at onboarding and at payment time, not something to rebuild.

Sources:
- [MuleHunter.AI adoption (Business Standard)](https://www.business-standard.com/amp/industry/banking/15-more-banks-to-adopt-rbi-s-mulehunter-fraud-detection-tool-by-october-125080101845_1.html)
- [MuleHunter.AI explained (Business Standard)](https://www.business-standard.com/finance/news/what-is-mulehunter-ai-rbi-s-latest-tool-against-financial-fraud-explained-124120600865_1.html)
- [RTI on banks using MuleHunter.AI (MediaNama)](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/)
- [I4C Suspect Registry (The420.in)](https://the420.in/i4c-suspect-registry-blocks-8031-crore-cyber-fraud-mule-accounts/)
- [I4C and RBIH on mule accounts (The420.in)](https://the420.in/i4c-rbih-ai-mule-accounts-cyber-fraud-crackdown/)
- [UPI limits, Sept 2025 (Outlook Money)](https://www.outlookmoney.com/banking/npci-changes-upi-transaction-limits-for-key-categories-from-september-15-2025-know-the-details)
