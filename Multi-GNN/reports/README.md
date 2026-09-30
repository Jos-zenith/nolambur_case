# Evidence report: what the rail engine achieves, measured honestly

Every number here comes from a JSON file in this folder, written by the code that measured it. The bridge serves the same files, and the console's Model page shows them.

| File | Written by |
|---|---|
| `evaluation_v2.json` | `rail_engine.evaluate` (the bridge's `/rail/evaluation`) |
| `scorer_compare.json` | `python -m infra.scorer compare` |
| `loadtest.json`, `loadtest_cached.json` | `python -m infra.loadtest engine [--scoring cached]` |
| `loadtest_http.json` | `python -m infra.loadtest http` |
| `ablation_v2.json` | `python -m infra.ablation report` |

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

## 3. Robustness: amount, real fraud rates, and a changing adversary

Measured by `python -m infra.ablation report` (`ablation_v2.json`). The protocol is the same as in section 2: fit on days 0–5, pick the threshold on days 6–7, report days 8–9. GNN scores are online and time-respecting.

### 3.1 Removing amount

Five ways to score a payment, on the 16,301 test-day payments (57 fraud):

| Arm | ROC AUC | Avg. precision | Fraud caught (of 57) | False alarms | Precision | Recall |
|---|---|---|---|---|---|---|
| Amount only (logistic regression on log amount) | 0.990 | 0.49 | 23 | 17 | 57% | 40% |
| Tabular, no graph (gradient boosting on hour, amount, channel) | 0.955 | 0.38 | 28 | 38 | 42% | 49% |
| **GNN, all inputs** (3 seeds) | 0.999–1.000 | 0.93–0.94 | 45–50 | 2–6 | 89–96% | 79–88% |
| GNN retrained **without amount** (3 seeds) | 0.87–0.89 | 0.02–0.05 | 0–7 | 10–38 | 0–16% | 0–12% |
| Production GNN, test-day amounts shuffled | 0.65 | 0.01 | 0 | 9 | 0% | 0% |

Fraud caught, by hop in the chain:

| Arm | Victim → first mule (14) | First → second mule (32) | Second → second mule (11) |
|---|---|---|---|
| Amount only | 10 | 11 | 2 |
| Tabular, no graph | 10 | 13 | 5 |
| GNN, all inputs (3 seeds) | 10–12 | 29–31 | 5–7 |
| GNN without amount (3 seeds) | 0 | 0–5 | 0–2 |

Mule accounts found by the rules plus each arm (26 mules active; the rules alone find 15, with 7 false accounts):

| Rules plus | Mules found | False accounts | Recall | Precision |
|---|---|---|---|---|
| Amount only | 19 | 18 | 73% | 51% |
| Tabular, no graph | 20 | 41 | 77% | 33% |
| GNN, all inputs | 20–21 | 9–12 | 77–81% | 64–69% |
| GNN without amount | 15–16 | 15–30 | 58–62% | 35–50% |

**What this shows.**
- **The model is not structure-only.** Without amount it collapses on every seed. It still ranks fraud above clean payments on average (AUC 0.87–0.89), but not near the top, so at a 0.35% base rate it is useless. It adds no mules to the rules, only false alerts.
- **It is not an amount check either.** Amount alone, with or without hour and channel, catches about the same share of victim payments as the GNN (10 of 14) but only a third of the forwarding hops. The GNN catches 29–31 of 32 forwards, with 2–6 false alarms against 17–38.
- **So the GNN learns amount in context: large sums arriving at an account and leaving again.** Neither the graph nor the amount does this alone. The three seeds agree, so this is not seed noise.
- **The consequence is a weakness.** A fraud ring that keeps every hop small defeats both the amount signal and the GNN's use of it. The drift test (payments under ₹10,000) now matters more than planned.

For the pitch, the honest claim is: rules find the core mules, and the GNN adds about 5 more with fewer false alerts than a non-graph model. The GNN supports the rules; it is not the product.

### 3.2 Precision at real fraud rates

The test days have fraud at 0.35% of payments. Real UPI fraud is far rarer: 12.64 lakh reported incidents in 185.8 billion transactions in FY 2024–25, about 0.0007%. That counts incidents, not payments, and under-reports, so treat it as a rough anchor, about 500× rarer than here ([source](https://www.moneylife.in/article/upi-frauds-27-lakh-cases-worth-rs2145-crore-registered-in-30-months-govt/75709.html)).

The table below holds recall and false-positive rate fixed and lets fraud get rarer. **This is arithmetic, not a measurement.** The false-positive rate rests on 2 false positives, so each figure is a range. Pessimistic uses recall at its 95% lower bound and FPR at its upper; optimistic is the reverse. Both use exact (Clopper-Pearson) intervals.

**Model alone, per payment.** Recall 79% (66–89%). False positives 2 of 16,244 clean payments, a rate of 0.012% (0.0015–0.044%).

| Fraud rarer than here | Fraud share | Precision | Range | False alerts per real one |
|---|---|---|---|---|
| 1× (as measured) | 0.35% | 96% | 84–99% | 0.04 |
| 10× | 0.035% | 69% | 34–95% | 0.4 |
| 100× | 0.0035% | 18% | 5–68% | 4.5 |
| ~500× (reported UPI rate) | 0.0007% | 4% | 1–29% | 23 |
| 1000× | 0.00035% | 2% | 0.5–17% | 45 |

**Rules and model together, per account.** Recall 77% (56–91%). 9 false accounts among 5,245 clean accounts active on the test days, a rate of 0.17% (0.08–0.33%).

| Mules rarer than here | Precision | Range | False accounts per mule |
|---|---|---|---|
| 1× (as measured) | 69% | 46–85% | 0.5 |
| 10× | 18% | 8–36% | 4.5 |
| 100× | 2% | 0.8–5% | 45 |
| ~500× (same factor as payments; see caveat 3) | 0.4% | 0.2–1.1% | 230 |

At a realistic base rate most alerts would be false. The queue (0.17% of accounts) is the weaker of the two.

**Caveats on this table:**
1. **The ~500× anchor is only an order of magnitude.** The reported rate counts incidents per transaction. It includes fraud that doesn't involve mules, and it probably undercounts.
2. **The false-positive rate is held constant as clean traffic grows.** Real clean traffic is messier than the synthetic set, so the real rate is more likely to be higher than lower. That would make these precisions optimistic.
3. **The account row at ~500× reuses the payment factor.** The share of accounts that are mules is not the share of payments that are fraud. No reported figure for mule-account prevalence was used here.

**What to do about it:**
- **Restrict only on corroborated alerts.** Rules and the model have to agree, as the router already requires for automatic holds, or an outside signal has to confirm, such as an I4C Suspect Registry hit or an onboarding link. A model-only score queues for review and never restricts on its own.
- **Use friction, not blocks, for weak signals.** A cooling-off period or a step-up confirmation costs an innocent payer seconds. A hold costs them a day.
- **Size the queue to analyst capacity.** Review the top k accounts a day, not everything above a threshold tuned at 0.35%. Pick the threshold again in shadow mode at the real base rate.
- **Report precision per 1,000 alerts in shadow mode, not recall.** At these rates, precision decides whether analysts trust the queue.

## 4. Throughput and latency

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

## 5. What this does not show

- **Synthetic data.** Clean payments are mostly small (median about ₹600) while scam transfers run ₹10,000 to ₹1 lakh, so amount still carries much of the signal: without it the model collapses (section 3.1). The rules were written by someone who knew how the generator works.
- **The test set is small.** Two campaigns, 26 mules. The intervals above are wide for that reason.
- **The base rate is high.** Fraud is 0.35% of test-day payments, about 500× the reported UPI rate. Precision would fall steeply (section 3.2).
- **The graph is incomplete.** A payment aggregator sees only its own merchants' flows, while mule chains cross banks and PSPs. This engine sees one slice of the graph.

**Shadow mode is the test that is missing.** Run the engine silently on one partner's anonymised flows for a few weeks. Log every alert and every would-be restriction. Then compare against the fraud reports and chargebacks that arrive later. That measures precision, recall and lead time on real traffic. Nothing here does.

## 6. Where this fits

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
