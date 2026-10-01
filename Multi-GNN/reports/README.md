# Evidence report: what the rail engine achieves, measured honestly

Every number here comes from a JSON file in this folder, written by the code that measured it. The bridge serves the same files, and the console's Model page shows them.

| File | Written by |
|---|---|
| `evaluation_v2.json` | `rail_engine.evaluate` (the bridge's `/rail/evaluation`) |
| `scorer_compare.json` | `python -m infra.scorer compare` |
| `loadtest.json`, `loadtest_cached.json` | `python -m infra.loadtest engine [--scoring cached]` |
| `loadtest_http.json` | `python -m infra.loadtest http` |
| `ablation_v2.json` | `python -m infra.ablation report` |
| `stress_v2.json` | `python -m infra.stress report` |
| `rules_r21.json` | `python -m infra.stress rules` |
| `rules_r21_nohop.json` | `python -m infra.stress nohop` |
| `rules_r22.json` | `python -m infra.stress r22` |
| `p2m_params_p1.0.json`, `p2m/*.json` | `python -m infra.p2m calibrate` / `evaluate` |

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

**Quote recall as a range, roughly 58–77%.** Redrawing the two test campaigns with unchanged behaviour gives 58% on one draw and 67% on another (sections 3.3 and 3.4). Two campaigns are too few to pin a single number.

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

### 3.3 Stress tests: fast mules, structuring, low-value rings

**Protocol, fixed on 2026-10-01 before any variant was scored.** Code: `infra/stress.py`. Results: `stress_v2.json`.

**How the variants work.** Each variant rewrites only the two test-day campaigns (`nolambur_v2_gen.py --variant ... --scope test`). Days 0–7 are byte-identical to the base data. So the frozen production model, its training days and its validation threshold (0.86) are untouched. This measures what happens when the adversary changes behaviour after the model was built.

The variants' campaigns draw from a new random stream, so `redraw` is the control: base behaviour on that same stream.

| Variant | What changes in the test campaigns |
|---|---|
| `redraw` | Nothing (control) |
| `fast` | Mules forward automatically: median 25 s after money arrives, about 85% within a minute, payments 2–20 s apart. Second-layer mules forward straight after their first receipt. |
| `struct` | Structuring: 3× the victims, each paying a third as much a day, and every hop in ₹2,000–5,000 payments. Total money about the same. |
| `low_0.5`, `low_0.2`, `low_0.1`, `low_0.05` | Low-value ring: every fraud amount, and the forwarding floors, multiplied by 0.5 / 0.2 / 0.1 / 0.05. The same draws, scaled. |

**Metrics (test days only; all five are reported for every variant, whatever they show):**
1. Recall: mules found by rules + model, out of mules active.
2. Precision: mules out of accounts alerted by rules + model.
3. Median lead time: first time fraud money left a mule, minus its first alert. Negative means too late.
4. Share of mules alerted before any money left them, out of mules that forwarded fraud money.
5. Fraud money stopped by graded holds, with the router acting alone.

Secondary: rules-only recall and precision, and the model's recall and precision on fraud payments.

**Retraining.** If the frozen model collapses on a variant (model recall on fraud payments below 40%, half its base 79%), that variant is also retrained. Retraining uses the same recipe (seed 42, 12 epochs) on data where every campaign has the new behaviour, then goes through the same measurement. Frozen answers "what happens when the adversary changes?"; retrained answers "is the pattern still learnable?". Both are reported.

**Rules stay r2.0.** If a variant breaks them and a patch follows, it ships as a new rule version, reported with before and after numbers on every variant, including the extra false alerts on the base data.

**Results (run 2026-10-01).** Every variant, with the five fixed metrics. Compare each variant with `redraw`, not with the base. The control alone moves recall from 77% to 58%, so two test campaigns are a small, noisy sample.

| Variant | Model | Median fraud payment | Recall | Precision | Median lead | Alerted before money left | Money stopped |
|---|---|---|---|---|---|---|---|
| base | frozen | ₹22,559 | 77% (20/26) | 69% | 3.2 h | 10/13 | 17% |
| **redraw (control)** | frozen | ₹24,680 | **58% (14/24)** | **58%** | **3.1 h** | **11/16** | **11%** |
| fast | frozen | ₹25,544 | 61% (14/23) | 70% | **37 s** | 7/10 | 19% |
| struct | frozen | ₹3,064 | 33% (11/33) | 55% | 7.0 h | 6/21 | 0% |
| struct | retrained | ₹3,064 | 45% (20/44) | 71% | 14.3 h | 14/26 | 10% |
| low ×0.5 | frozen | ₹12,340 | 38% (9/24) | 90% | 3.8 h | 8/16 | 0% |
| low ×0.5 | retrained | ₹12,340 | 48% (14/29) | 64% | 3.1 h | 11/17 | 0% |
| low ×0.2 | frozen | ₹4,936 | **0% (0/24)** | 0% (0/1) | n/a* | 4/16* | 0% |
| low ×0.2 | retrained | ₹4,936 | 7% (2/29) | 14% | n/a* | 4/17* | 0% |
| low ×0.1 | frozen | ₹2,468 | 0% (0/24) | 0% (0/1) | n/a* | 4/16* | 0% |
| low ×0.1 | retrained | ₹2,468 | 3% (1/29) | 4% | n/a* | 3/17* | 0% |
| low ×0.05 | frozen | ₹1,234 | 0% (0/24) | 0% (0/1) | n/a* | 4/16* | 0% |
| low ×0.05 | retrained | ₹1,234 | 10% (3/29) | 1% (3 of 294) | n/a* | 5/17* | 0% |

\* **Only reused mules count here.** The only mules "alerted before money left" in the low ×0.2 and smaller rows are mule accounts reused from an earlier campaign, flagged days earlier (median lead 5–8 days). The pre-registered lead metric counts alerts from any time, so they count, but nothing detected the test-day ring itself.

**Why the retrained rows' counts differ.** Retrained rows use data where every campaign has the variant. Campaign 8's victims are still paying on day 8, so its variant-shaped payments spill into the test days (61 fraud payments rather than 57, and 29 active mules rather than 24).

**How the model fared on fraud payments.** This is the collapse test; the threshold is picked on days 6–7.

| Variant | Frozen | Retrained |
|---|---|---|
| fast | 33 of 46, 1 false | not needed |
| struct | 0 of 608, 1 false | 340 of 621, 3 false |
| low ×0.5 | 18 of 57, 1 false | 49 of 61, 8 false |
| low ×0.2 | 0 of 57 | 7 of 61, 13 false |
| low ×0.1 | 0 of 57 | 1 of 61, 28 false |
| low ×0.05 | 0 of 57 | 15 of 61, **627 false** |

**Fast mules.**
- **Alerts still arrive in time, just.** The median alert comes 37 s before the mule moves the money, and 7 of 10 mules are flagged before any money leaves. That is too fast for an analyst.
- **Holds still stopped money, but only from later instalments.** The router restricts only on corroborated evidence, and that comes after the first forward. What it stopped came from victims' second-day instalments, which hit an account already on hold, and from the mule's later forwards.
- **19% vs 11% for the control is one ₹99,000 payment.** Read it as "about the same", not "better".
- **So against automated mules, alerts can arrive in time but holds cannot stop the first transfer.** Only a hold at the moment of the alert could, and that would trade precision for speed.

**Structuring (₹2,000–5,000 payments, same money).**
- **The frozen model sees nothing:** 0 of 608 payments.
- **The rules partly hold up.** Pass-through sums over windows, so it still flags 3 mules (all real). Hop-from-flagged adds 8 more.
- **The rule meant for this finds nothing.** The detector named `structuring` looks for transfers just under the ₹1 lakh cap, so it has no answer to many small payments.
- Recall falls from 58% (control) to 33%, and holds stop nothing.
- **Once trained on it, the model learns it easily** (340 of 621 payments, 3 false). The retrained data has 5% fraud payments, 10× the others, which makes it easier to learn than it would be in reality.
- **So the expectation that window sums would still catch structuring holds only in part:** they work, but the near-cap rule is blind.

**Low-value rings: where detection breaks down.**
- **The rules break first.** At ×0.5 (median fraud payment ₹12,340, largest ₹50,000) they find no mules at all. Pass-through needs ₹1 lakh through an account in a window, and new-payer inflow needs ₹1.5 lakh.
- **At ×0.5 the GNN is the only thing that works.** Frozen, it finds 9 mules at 90% precision; retrained, 14.
- **Holds still stop ₹0.** The router never restricts on a model-only alert, which is the policy recommended in 3.2, so this is the cost of that policy.
- **At ×0.2 (median ₹4,936, largest ₹20,000) nothing detects the ring.** The frozen model finds nothing. Retraining doesn't rescue it: 7 of 61 payments with 13 false at ×0.2, and 15 of 61 with 627 false at ×0.05.
- **At those sizes the fraud payments look like ordinary transfers.** Clean person-to-person payments here have a median of ₹1,283, and 14% are ₹5,000 or more.
- **So a ring whose payments stay around ₹5,000 (none above ₹20,000) is invisible to everything in this system.** That is the plain failure.

**What this changes.**
1. **Pass-through floors are the rules' weak point.** The fix is floors relative to the account's own history ("5× its usual daily inflow"), not absolute rupee amounts. That would be rule r2.1, measured before and after on every variant, including the extra false alerts it causes on the base data. It has not been done.
2. **The near-cap structuring rule should count many small payments too:** the number of distinct payers per window, not only amounts near ₹1 lakh.
3. **Below about ₹5,000 a payment, payment data alone is not enough.** The signals that might still work come from outside the payment: many new accounts linked to one device or onboarding, I4C Suspect Registry hits, and victim reports feeding back quickly.

### 3.4 Rules r2.1: patching the evasions, and what the patch costs

**Design and protocol, fixed on 2026-10-01 before any fresh draw was generated.** The stress variants in 3.3 are now a development set, because the design below was written after seeing them. So r2.1 is judged mainly on fresh draws of every variant (a new random stream for the test campaigns) that nobody has looked at.

**The r2.1 design.** Its parameters come only from the base data's train days (`python -m infra.calibrate_r21`), never from the variants.

- **Pass-through floor.** It becomes relative instead of a fixed ₹1 lakh:
  - For an account with history (active 5 of the last 7 days): 3× its own busiest day in the last 7.
  - **Cold start.** For a new account, which is what a first-layer mule usually is: its peer group's 95th-percentile busiest day. That is ₹28,000 for individuals and ₹94,000 for suppliers, from the train days.
  - Either way, at least ₹25,000.
  - The ratio (60% sent on, to 2+ accounts) and the known-forwarder exception are unchanged.
- **New detector: many new payers.** 5 or more different person-to-person payers, each paying an individual's account for the first time, within 24 h, and at least ₹5,000 in total.
  - It counts people, not rupees.
  - On the train days, 99.9% of individual-days had at most 3 new payers.
  - Shops and suppliers are exempt, because many new payers is normal for them.
- **Friction, a separate router option (`RAIL_MODEL_FRICTION=1`).** A model-only alert scoring 0.95 or more gets a one-hour settlement delay (level 1) instead of no action. Rules still decide every hold.
- **Unchanged:** the rule for large inflows from new payers, the near-cap structuring rule, hop-from-flagged, and the model and its threshold.

**Evaluation.**
- **Arms:** r2.0, r2.1, and r2.1 with friction, all using the frozen production model's scores.
- **Data:** the original draws (3.3, the development set) and one fresh draw of each variant (`--stream 2`), plus the base data.
- **Metrics:** the five from 3.3. Added:
  - rules-only recall and precision
  - false accounts a day on the test days, and per analyst a day (2 analysts)
  - false accounts a day over days 1–9 of the base data, for a steadier cost estimate
  - false accounts per real mule if mules were ~500× rarer (3.2)
  - for friction: fraud money delayed, genuine money delayed, and innocent accounts delayed
- **Honesty rules:**
  - r2.1 is not retuned after the fresh draws are seen.
  - If it fails on them, that is reported.
  - The simulation has no victims or analysts reacting during a delay. So a delay only "stops" money if a rule later escalates the account. Delayed money is reported separately, as money someone could have recalled.

**Seeds and streams.** The generator seed is 7. A shifted campaign c draws from `np.random.default_rng([7, c, stream])`:
- stream 1: the original draws (3.3, the development set)
- stream 2: the fresh draws used here
- **stream 3: reserved** for judging r2.2, not generated and not looked at

The fresh-draw numbers below come from the commit tagged `eval-r21-fresh`.

**Results (run 2026-10-01; `rules_r21.json`).** Frozen model throughout. The r2.0 rows reproduce 3.3 exactly.

**Fresh draws (stream 2), which r2.1 was not designed on.** Rules + model:

| Variant | Recall r2.0 → r2.1 | Precision r2.0 → r2.1 | Money stopped r2.0 → r2.1 → r2.1 + friction |
|---|---|---|---|
| redraw (control) | 67% → 78% | 78% → 46% | 18% → 23% → 32% |
| fast | 62% → 69% | 76% → 44% | 12% → 16% → **33%** |
| struct | 33% → **94%** | 55% → 43% | 0% → 20% → 20% |
| low ×0.5 | 37% → 56% | 91% → 50% | 0% → 11% → 20% |
| low ×0.2 | **0% → 37%** | — → 48% | 0% → 9% → 9% |
| low ×0.1 | 0% → 0% | — → 0% (8 false) | 0% |
| low ×0.05 | 0% → 0% | — → 0% (8 false) | 0% |

**The original draws (the development set) show the same pattern.** Struct recall goes 33% → 97%, low ×0.2 0% → 29%, low ×0.5 38% → 54%, the redraw control 58% → 71%, and ×0.1 and below stay at 0%. The fresh draws match the development set, so the gains are not from fitting r2.1 to the variants it was designed on.

**What it costs: a much longer, noisier queue.** False accounts over days 1–9 of the base data, alert-only replay:

| | False accounts a day | Per analyst a day (2 analysts) | Per 100,000 accounts a day | False accounts per real mule at ~500× rarer |
|---|---|---|---|---|
| r2.0 | 6.2 | 3.1 | ~110 | ~50–420 across draws |
| r2.1 | 18.0 | 9.0 | ~320 | ~510–810 across draws |

**r2.1 roughly triples the clean-traffic queue.** Precision falls on every draw, from 55–91% under r2.0 to 39–50% under r2.1.

**Where the false alerts come from.** Not mainly from the new rules:
- The new-payers rule is 26 for 26 on fresh structuring, and costs 6 false accounts in 9 days of base traffic.
- The relative pass-through floor is 8 of 9 and 11 of 12 on its own.
- **Most of the cost is a cascade.** More primary alerts make hop-from-flagged flag everyone the mules pay, which means shops, suppliers and businesses. On the base data its hits went from 10 of 17 to 12 of 30. False accounts by type under r2.1: 53 individuals, 50 merchants, 38 businesses, 21 suppliers.

**Friction** (a model-only lead scoring 0.95+ delays settlement for an hour):
- **Money stopped rose by 4–22 points,** when a rule later escalated the account and the delayed transfers were cancelled.
- **Its biggest effect is on fast mules** (r2.1 alone vs r2.1 + friction: 16% → 33% fresh, 27% → 49% original). It is the only mechanism here that holds back a mule's *first* forward, because it acts the moment the model scores the inflow.
- **The cost was 1 innocent account delayed for about 2 hours per run,** and at most ₹6,000 of genuine money delayed and then released.
- It never blocks anything by itself.
- **The friction figures are an upper-end estimate, not a measured outcome.** Money counts as stopped only if a rule escalates the account during the delay. The simulation has no victims or analysts acting in that hour, and the cost figures come from a handful of runs on synthetic traffic.
- **Delaying a real customer's settlement needs sign-off.** It has legal and operational implications (merchant agreements, RBI rules on settlement timelines, customer communication) that need a partner bank's or PA's approval before any pilot.

**The trade in one line:** on fresh draws r2.1 raises recall (structuring 33% to 94%, low ×0.2 0% to 37%) and cuts precision on every draw (to 39-50%).

**The new-payers detector has a fixed threshold.** "5 or more" sits at the 99.9th percentile of clean traffic, and the structuring variant it catches 26 of 26 on was built by the same person who wrote the detector. An adversary who reads the rule and uses 4 payers per account walks under it. The `struct4` check below measures how far detection degrades when that happens.

**Verdict on r2.1:**
- **Worth shipping:**
  - the new-payers detector (precise, cheap, independent of amounts)
  - the relative floor for the primary pass-through rule
  - friction
  - *Revised after the follow-up checks below: dropping hop-from-flagged is not enough on its own. See the revised verdict.*
- **Not worth shipping as it stands:** the queue cost, driven by hop-from-flagged.
- **The next version (r2.2) should be designed now and judged on another fresh stream (3):**
  - hop-from-flagged only for individuals' accounts
  - only when the flagged sender's money is a large share of the recipient's inflow
- **It is not applied here.** Doing so after seeing these draws would be tuning to the test.

**Follow-up checks, fixed before running.**

1. **The configuration recommended below has not been measured.** It is r2.1 without hop-from-flagged, with and without friction. The headline r2.1 numbers include hop-from-flagged, so this configuration is replayed on the same base data, original draws and fresh draws (`RAIL_HOP_FROM_FLAGGED=0`), and its clean-traffic cost is measured the same way.
   - If recall holds and the queue shrinks, the verdict stands.
   - If recall drops sharply, the hop rule was doing needed work, and r2.2 moves up the list.
2. **An adversary who knows the fan-in threshold.** Variant `struct4` is structuring in which every first-layer mule takes money from at most 4 victims. The ring opens extra fresh mule accounts to spread the victims, so it stays under "5 or more new payers".
   - It uses its own stream (4), so stream 3 stays reserved.
   - It is scored with the frozen model and judged on the same five metrics under r2.0, r2.1, and r2.1 without hop.

**Follow-up results (`rules_r21_nohop.json`).**

**1. r2.1 without hop-from-flagged.** Fresh draws, rules + model:

| Variant | Recall: r2.0 / r2.1 / r2.1 − hop | Precision: r2.0 / r2.1 / r2.1 − hop | Money stopped, r2.1 / r2.1 − hop (no friction) |
|---|---|---|---|
| redraw | 67% / 78% / 67% | 78% / 46% / **90%** | 23% / 23% |
| fast | 62% / 69% / 62% | 76% / 44% / **89%** | 16% / 16% |
| struct | 33% / 94% / **79%** | 55% / 43% / **93%** | 20% / 19% |
| low ×0.5 | 37% / 56% / 44% | 91% / 50% / 86% | 11% / 11% |
| low ×0.2 | 0% / 37% / **11%** | — / 48% / 60% | 9% / 9% |

**Clean-traffic queue** (base data, days 1–9): r2.0 6.2, r2.1 18.0, and **r2.1 − hop 8.3 false accounts a day** (4.2 per analyst).
- The rest of the cost is mostly the relative pass-through floor firing on businesses that forward their takings (34 false accounts in 9 days). False accounts by type: 38 businesses, 26 individuals, 8 suppliers, 3 merchants.
- Model-only leads account for most of the remainder.
- At ~500× rarer mules, r2.1 − hop gives about 35–100 false accounts per real mule on most draws, and 340–510 on the ×0.2 draws, where it finds very few mules. That compares with ~510–810 for r2.1 and ~50–420 for r2.0.

**What that shows:**
- **Hop-from-flagged is the main false-alert source in r2.0 as well.** Without it, precision on the test days is 83–94% on every draw.
- **It is also where much of the recall comes from.** Its catches are the second-layer mules, those that only receive from a flagged account.
- Without it, r2.1's gains shrink:
  - Structuring keeps most of its gain (33% → 79%, from the new-payers rule).
  - The redraw and fast draws fall back to r2.0's recall.
  - The ×0.2 ring mostly disappears again (37% → 11%).
  - Holds stop about the same money, because hop alerts rarely led to holds.

**2. The 4-payer adversary** (`struct4`, stream 4). Every first-layer mule takes money from at most 4 victims.

| | r2.0 | r2.1 | r2.1 − hop |
|---|---|---|---|
| Recall | 68% (21/31) | 84% (26/31) | **42% (13/31)** |
| Precision | 68% | 50% | 87% |
| New-payers alerts (mules / alerts) | — | 9 / 9 | 9 / 9 |
| Money stopped | 0% | 19% | 19% |

- **The new-payers rule degrades as expected, but not to zero.** It drops from 26 alerts on plain structuring to 9, all real mules: 7 second-layer mules that still received from 5 or more new payers, and 2 first-layer.
- **Most first-layer mules are caught by pass-through instead.** Four victims at up to ₹33,000 a day still clears the ₹28,000 cold-start floor (all 8 of its alerts are mules, 6 first-layer and 2 second-layer; one of them was not active on the test days, so it counts as 7 of 8).
- **Without hop-from-flagged, recall halves.** The 4-payer evasion mainly costs second-layer coverage, which only hop provided.

**Revised verdict.**
- **"r2.1 − hop" is not the answer on its own.** It buys precision (83–94%) and a small queue (8.3 a day) by giving back second-layer recall, and it halves recall against the 4-payer adversary.
- **r2.2 is justified.** The case is now measured, not guessed: a hop rule that keeps second-layer coverage without flagging every shop a mule pays.
- **That still doesn't fix the base-rate problem.** Even the most precise configuration here is ~35–100 false accounts per real mule at ~500× rarer fraud. That is a job for the agreement policy (restrict only on agreement or outside confirmation), shadow-mode calibration and queue sizing, not for rule tweaks.

**The stated limit, updated.**
- r2.0's rules find nothing once a ring's payments fall to a median of about ₹12,000; the model still finds about a third of mules there, and nothing at about ₹5,000.
- r2.1 finds a third of mules at a median of about ₹5,000.
- **Below a median of about ₹2,500 a payment (largest ₹10,000), neither version detects the ring,** and r2.1 only adds false alerts.

### 3.5 Aggregator-side fraud (P2M)

**Design and protocol:** `P2M_DESIGN.md`, committed before any P2M code. **Code:** `p2m_gen.py` and `infra/p2m.py`, committed with the calibrated parameters (`p2m_params_p1.0.json`) before any detector result existed. **Results:** `reports/p2m/*.json`.

This is the aggregator's own view: P2M payments into its merchants, its merchants' collect requests with their outcomes, its settlement batches, and its onboarding records. Nothing after settlement is visible, so the GNN does not apply; these are rules.

**Parameters, from train days 3–5, clean merchants only:**
- **D1 (big tickets):** 3 or more first-time payers at or above the category's 99th-percentile ticket within 24 h. The p99 ticket ranges from ₹1,207 (subscriptions) to ₹49,298 (electronics).
- **D2 (payer spread):** first-time payers from 6 or more other states into a local-category merchant within 24 h.
- **D3 (collect pattern):** 14 or more collect requests to non-customers within 24 h, with at least 69% declined or expired.
- **D4 (shared settlement):** one settlement account behind merchants with different declared legal entities. D4 opens a review; D1–D3 hold the merchant's settlement for 24 h.

**Results.** Test days, every draw run so far. Stream 1 was for development; streams 2, 4 and 5 are fresh.

| Draw | Active fraud merchants flagged | Precision, all detectors | Precision, hold detectors (D1–D3) | Rings (fronts flagged) | Fraud money held at a settlement batch | Median first-fraud → first hold alert |
|---|---|---|---|---|---|---|
| development (1) | 5/5 | 43% (6/14) | 100% (4/4) | 1 ring (2 fronts) | 94% | 86 min |
| fresh 2 | 5/5 | 33% (4/12) | 100% (4/4) | none in this draw | 68% | 58 min |
| fresh 4 | 3/3 | 33% (4/12) | 100% | 1 ring (2 fronts) | 68% | 107 min |
| fresh 5 | 3/3 | 33% (4/12) | 100% | 1 ring (2 fronts) | 63% | 103 min |

Streams 4 and 5 were added after stream 2 turned out to contain no ring. That decision was recorded in `P2M_DESIGN.md` before they were generated.

**Where the numbers come from:**
- **Every active fraud merchant was flagged before the settlement batch that would have paid out its first fraud money.**
- **"Held" means held at least once.** With nobody acting, a hold lifts after 24 h (72 h with D4), and the money settles in a later batch. So "held" is the window an analyst had, not money recovered.
- **D4 caught every ring member at onboarding, fronts included,** days before any fraud. That is the onboarding module's first fraud data.
- **D4 also flagged all 8 legitimate family-business merchants.** Two proprietorships sharing one bank account look exactly like a ring from the aggregator's records. That is why all-detector precision is 33–43%, and why D4 opens a review rather than a hold.

**Cost on clean traffic** (identical in every draw, since clean traffic doesn't change with the stream):
- **Holds:** 2–3 false merchants in 9 days, all D2, from travellers paying local shops. That is about 0.5 false holds per 1,000 merchants a day, 66 merchant-hours of held settlement, and ₹6,000–26,000 of genuine money held per test window.
- **Reviews:** 8 D4 reviews, one-off at onboarding (1.9% of merchants).

**The low-value sweep** (fresh stream 2, S1 amounts scaled; S2 unchanged):

| S1 scale | Active flagged | Fraud money held | What was lost |
|---|---|---|---|
| ×1 | 5/5 | 68% | — |
| ×0.5 | 4/5 | 35% | The electronics fake merchant. Its victim payments (median ~₹17,500) no longer reach electronics' p99 of ₹49,298. |
| ×0.2 | 4/5 | 37% | Same |
| ×0.1 | 4/5 | 36% | Same. The kirana fake merchant is still caught, later (12 h rather than 5 h), because ₹3,500 is still above kirana's p99 of ₹1,639. |

**Stated limits:**
- **The scenarios are easy by construction.** Victim payments of ₹10,000+ into categories whose 99th-percentile ticket is ₹1,200–7,300 are exactly what D1 looks for, and the same person wrote the scenarios and the detectors.
- **A fake merchant in a high-ticket category is hard to see.** Electronics, travel and education have p99 tickets of ₹28,000–49,000. D1 misses such a merchant once its payments sit under the category's p99, and D2 applies to local categories only.
- **A collect scam can stay under D3.** It would need fewer than 14 requests a day per merchant VPA, spread across many VPAs, or a much higher approval rate.
- **One "active" merchant in every draw is not fresh.** It is the validation campaign's collect scammer, still running on day 8 and identical across draws. The fresh evidence is 2–4 merchants per draw: the test sets are tiny, and the percentages above are counts of a handful.
- **The projection to real fraud rates is not meaningful here.** The JSON's `falsePerRealAtReportedRate` (2,300–3,800) multiplies a merchant-level count by a payment-level factor. The usable cost figures are the ones above: false holds per 1,000 merchants a day, and D4 reviews as a share of onboardings.
- **Company and director (MCA) linkage is not tested.** The registry stays empty; S3 is detected from the aggregator's own onboarding records only.

### 3.6 Rules r2.2: a narrower hop rule, judged once on stream 3

**Design, criteria and protocol, fixed and committed before stream 3 was generated.** Code: `RAIL_RULES=r2.2` in `rail_engine.py` and `python -m infra.stress r22`. Results: `rules_r22.json`.

**The problem it targets (3.4).** r2.1's hop-from-flagged flagged everyone a mule paid, which is what tripled the queue. Without the hop rule, second-layer recall halved: on the 4-payer adversary it fell from 84% to 42%, and on the ×0.2 ring from 37% to 11%.

**The design.** r2.2 is r2.1 except for the hop rule, which now fires only when all of these hold:
- the recipient is an individual's account (shops, suppliers and businesses are skipped)
- money from flagged senders in the last 24 h is at least ₹6,100, the 90th-percentile individual-to-individual payment on the train days
- that flagged money is at least half of everything the account received in those 24 h

No other parameter was added. The ₹6,100 comes from the train days of the base data. The 50% share is a design choice, not fitted to any variant.

**Pass criteria. r2.2 passes only if all three hold:**
- **C1, second-layer recall comes back.** On the stream-3 draws of `struct4` and `low ×0.2`, r2.2's recall on second-layer mules recovers at least halfway from r2.1 − hop to full r2.1, measured on that same draw.
- **C2, the queue stays small.** On clean traffic (base data, days 1–9), r2.2 raises at most 10 false accounts a day. For comparison: r2.0 6.2, r2.1 − hop 8.3, r2.1 18.
- **C3, no regression.** On the stream-3 redraw, r2.2's recall (rules + model) is at least r2.0's.

**What happens either way:**
- If r2.2 fails any criterion, that is published here and the hop rule stays as it is: r2.0 remains the default, and r2.1 and r2.2 stay opt-in.
- If it passes, it becomes the recommended opt-in configuration. It still doesn't fix the base-rate problem in 3.2.

**Protocol:**
- Stream 3 is generated once, for every variant (`redraw`, `fast`, `struct`, `struct4`, `low ×0.5/0.2/0.1/0.05`), and scored with the frozen production model.
- Four arms are compared, without friction: r2.0, r2.1, r2.1 − hop and r2.2.
- All five metrics from 3.3, second-layer recall and the clean-traffic queue are reported for every arm.
- Nothing is retuned after stream 3 is seen.

**Result: r2.2 fails its pre-registered criteria.** Run 2026-10-01; `rules_r22.json`. Two of the three criteria miss, each by a single unit (one mule, one false account) on samples this small. That is inside the noise, so the right reading is **"not demonstrated", not "r2.2 is worse"**. As committed in advance, the hop rule stays as it is: r2.0 remains the default, and r2.1 and r2.2 stay opt-in. r2.2 is not retuned, and stream 3 is spent: it will not be used to judge anything again.

**Summary:** r2.2 keeps r2.1's structuring recall at far better precision (94% against r2.1's 45–47%), but it did not clear the bar on the small ring or the queue. Rule work stops here; the ×0.2 ring stays a stated limit (section 5).

| Criterion | Bar | r2.2 | Result |
|---|---|---|---|
| C1, struct4 second-layer recall | at least 78% (halfway from 64% to 92%) | 92% (23 of 25) | pass |
| C1, low ×0.2 second-layer recall | at least 15.9% (halfway from 9.1% to 22.7%) | 13.6% (3 of 22) | **fail**, by one mule |
| C2, clean-traffic queue | at most 10.0 false accounts a day | 10.1 (91 in 9 days) | **fail**, by one account |
| C3, recall on the stream-3 redraw | at least r2.0's 79% | 79% | pass |

**One disclosure about the run.** The first verdict run crashed after its replays and before writing or printing any result. The stress runner didn't pass the new per-role counts through (commit e003348). The fix changed no rule, parameter or criterion. The same stream-3 data was re-measured, not regenerated.

**All arms on stream 3** (rules + model, frozen model, no friction):

| Variant | Recall: r2.0 / r2.1 / r2.1 − hop / r2.2 | Precision: r2.0 / r2.1 / r2.1 − hop / r2.2 | Second-layer mules found, r2.2 |
|---|---|---|---|
| redraw | 79% / 79% / 75% / 79% | 81% / 54% / 88% / 88% | 16 of 22 |
| fast | 79% / 79% / 75% / 79% | 81% / 61% / 88% / 88% | 16 of 22 |
| struct | 33% / 97% / 79% / 97% | 52% / 47% / 93% / 94% | 24 of 25 |
| struct4 | 71% / 94% / 71% / 94% | 65% / 45% / 92% / 94% | 23 of 25 |
| low ×0.5 | 43% / 68% / 43% / 64% | 80% / 54% / 80% / 86% | 12 of 22 |
| low ×0.2 | 4% / 25% / 14% / 18% | 50% / 39% / 67% / 71% | 3 of 22 |
| low ×0.1 | 0% / 21% / 7% / 11% | — / 38% / 50% / 60% | 2 of 22 |
| low ×0.05 | 0% / 4% / 4% / 4% | — / 10% / 33% / 33% | 1 of 22 |

**What the failure leaves behind:**
- **On structuring, r2.2 did what it was designed for.** On struct and struct4 it keeps r2.1's recall (97% and 94%) at 94% precision, against r2.1's 45–47%.
- **It does not recover the small ring.** At ×0.2, second-layer coverage stays near the no-hop level.
  - **The ₹6,100 floor is probably not the reason.** A post-hoc diagnostic, run on streams 1 and 2 of the ×0.2 ring (never stream 3) after the result, looked at each second-layer mule's largest 24-hour fraud inflow and its share of that window's inflow. On amounts alone, 11 of 18 and 13 of 21 second-layer mules clear both the ₹6,100 floor and the 50% share.
  - **The likelier limit is upstream.** Hop-from-flagged needs a flagged sender, and at ×0.2 the rules flag only 2 of 6 first-layer mules (stream 3, every rules version). There is little to hop from.
  - This explains the miss; it does not fix it.
- **The queue lands just over the bar.** It is 10.1 false accounts a day, against 18.0 for r2.1 and 8.3 for r2.1 − hop. Hop-from-flagged still accounts for 17 of the 91 false accounts.
- **These observations are not a reason to adjust r2.2 and re-judge it.** Any r2.3 needs a new design written before a new stream (5 or later) is generated.

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
- **Small rings evade everything.** Below a median of about ₹2,500 a payment (largest ₹10,000), neither rules version nor the model, even retrained, detects the ring. At about ₹5,000, r2.1 finds a third of the mules and r2.0 finds none (sections 3.3 and 3.4).
- **The base rate is high.** Fraud is 0.35% of test-day payments, about 500× the reported UPI rate. Precision would fall steeply (section 3.2).
- **The graph is incomplete.** A payment aggregator sees only its own merchants' flows, while mule chains cross banks and PSPs. This engine sees one slice of the graph. The P2P results (sections 2 and 3.1–3.4) assume a view of mule chains that an aggregator does not have. Section 3.5 evaluates the aggregator's own view (P2M payments, collect requests, settlement and onboarding), where the GNN does not apply.

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
