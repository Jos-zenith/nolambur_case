# P2M and aggregator-side fraud: design, fixed before any code or data

Written 2026-10-01, before the generator, detectors or any P2M data exist. The same discipline applies as for r2.1 (README.md 3.4):
- scenarios and detectors are written down first
- parameters come from the train days' clean traffic only
- results are judged on test-day campaigns from a fresh random stream

This document is the protocol. Results will go in a new README section, including failures.

## Why this exists

In v2, every one of the 419 fraud payments is P2P and none of the 52,095 P2M payments is fraud. The pitch is a payment aggregator's risk layer, but the aggregator's own traffic has no fraud in it. That also leaves the onboarding module (settlement-VPA checks, MCA linkage) with no fraud scenario behind it.

## What an aggregator sees (the vantage point)

The detectors may use only what a payment aggregator (PA) sees.

**It sees:**
- **P2M payments into its own onboarded merchants:** payer VPA, payer's PSP handle, amount, time, and initiation mode (QR, intent or collect).
- **Collect requests its merchants send, including declined and expired ones.** The PA's switch sees the request and its outcome.
- **Settlement payouts from each merchant to its settlement bank account,** in daily batches.
- **Its own onboarding records:** merchant ID, category (MCC), declared legal entity, settlement account, onboarding date, and address.

**It does not see:**
- the payer's other transactions
- anything that leaves the settlement bank account afterwards (the onward P2P hops the v2 mule chains use)
- other PAs' merchants

So the 2-hop GNN does not apply here. From the PA's side, the graph is a star of payers around each merchant. The P2M detectors are rules. That's stated rather than hidden.

## Data

- **Generator:** a new generator, `p2m_gen.py`, writes `nolambur_p2m/`. The v2 dataset and its generator stay untouched.
- **Merchants:** about 400, across categories with realistic ticket sizes (kirana, restaurants, pharmacy, fuel, utilities and subscription billers, online services, electronics). Clean payers come from a people population with home states.
- **Chains:** legitimate chains (franchises) share one settlement account and declare one legal entity. These are the clean look-alike for scenario 3.
- **Collect requests:** legitimate billers send them to existing customers and get most approved. That is the clean look-alike for scenario 2.
- **Schedule:** 10 days, with campaigns on every split as in v2.
- **Test-day campaigns:** these draw from `default_rng([seed, campaign, stream])`, so fresh draws exist for judging.
  - Stream 1 is the development draw.
  - Stream 2 is the judging draw.
  - Stream 3 stays reserved.

## Scenarios

**S1: Fake or rented merchant as a mule endpoint.**
- A merchant onboarded in the last 30 days, in a small-ticket category (kirana, say), receives "payments" from scam victims.
  - These are investment or task scams paid over QR or intent: ₹10,000 to ₹1 lakh each, from payers who have never paid it and who live in other states.
- It settles daily, as normal. Past settlement, the money is out of the PA's sight.
- **A low-value version scales amounts down**, as in 3.3, to find where detection breaks down.

**S2: Collect-request scam.**
- A merchant VPA sends collect requests to many people who have never paid it, usually framed as a "refund" or "cashback" that actually debits them.
- Most decline or let the request expire; some approve. Approved amounts are ₹2,000 to ₹25,000.

**S3: Settlement account reused across "unrelated" merchants.**
- Several merchants with different declared legal entities, categories and onboarding dates (spread over weeks) share one settlement account.
- One or more of them also runs S1 or S2. Others are dormant fronts kept in reserve.

## Detectors (rules p1.0)

Every parameter comes from the train days' clean traffic.

| Detector | Signal | Parameter from train days |
|---|---|---|
| D1 ticket anomaly | Payments above the category's p99 ticket into a merchant, in 24 h, from first-time payers; a new merchant (under 30 days) is judged against its category, an older one against its own history too | Category p99 ticket; clean count per merchant-day |
| D2 payer spread | First-time payers from many states into a local-category merchant in 24 h | Category p99.9 of distinct payer states per merchant-day |
| D3 collect pattern | Collect requests to first-time payers in 24 h with a high decline-plus-expiry rate | p99.9 of requests to new payers and of the decline rate, among clean collect senders |
| D4 shared settlement | One settlement account shared by merchants with different declared legal entities, checked at onboarding and on every change | None: a structural rule; chains that declare one entity pass |

**Actions.**
- **The PA's lever is the settlement payout, not the payment.** An alert before the day's batch can hold that merchant's payout: a settlement hold, graded like the P2P ladder.
- D4 alone flags an account for review or an onboarding hold. D4 with D1, D2 or D3 holds settlement.

## Metrics (test days; every metric reported whatever it shows)

1. Merchant-level recall: fraud merchants flagged, out of fraud merchants active.
2. Merchant-level precision.
3. Fraud money held before settlement: fraud inflow to a merchant whose payout was held before the batch that would have carried it, out of all fraud inflow.
4. Median time from first fraud payment to alert, and the share of fraud merchants flagged before their first settlement batch.
5. Cost:
   - false merchants a day and genuine settlement money held (₹ and merchant-hours)
   - false merchants per real one at ~500× rarer fraud (3.2)

Everything is reported on the development draw and the fresh draw. The detectors are not retuned after the fresh draw is seen.

## Stated limits in advance

- **The data is synthetic, and the scenarios and detectors come from the same person.** This is the same caveat as in 3.2–3.4.
- **Nothing past settlement is visible.** A merchant that settles before any detector fires loses that batch's money. Recovery would need the settlement bank.
- **Company and director (MCA) linkage for S3 is not built with real data.** The registry ships empty. S3 is detected from the PA's own onboarding records, the shared settlement account and declared entities, unless synthetic company and director fixtures are approved (open question).
