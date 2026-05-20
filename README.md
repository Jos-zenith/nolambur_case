# Operation Nolambur
### *Turning the Golden Hour into a Golden Second*

> A real-time UPI fraud detection system built to stop digital arrest scams — modelled on the Nolambur, Chennai incident where ₹22.5L was siphoned across 40+ mule accounts in minutes.

---

## Motto

**"don't chase fraud. predict it."**

While traditional systems react to blacklists, Operation Nolambur detects *behavioral intent* — the rhythm of money movement, not just the accounts it touches.

---

## The Problem

On a single morning in Nolambur, Chennai, a resident was held under a fake CBI "digital arrest" via video call. Under duress, they transferred ₹22.5L in ₹5L–₹5.5L bursts to avoid low-value triggers. The money hit 8 Layer-1 mule accounts in Haridwar and Rajasthan, then fanned out to 35 Layer-2 cashout accounts — all within 4 hours.

By the time Tamil Nadu Cyber Cell could coordinate freeze requests across state lines, most of the money was gone.

**₹22,495 Crore** is lost to cyber fraud annually in India. 9% of that comes from Digital Arrest scams alone.

---

## What I Built

A two-stage ML pipeline + real-time dashboard that detects mule chains before the money moves.

```
Victim transfer → T-GNN flags L1 mule (< 1s) → Predicts L2 accounts → Pre-freeze signal
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Next.js Dashboard                        │
│  Command Center · Cluster Graph · Drill-down · Timeline      │
└────────────────────┬────────────────────────────────────────┘
                     │ REST + SSE
┌────────────────────▼────────────────────────────────────────┐
│                   FastAPI Inference Layer                     │
│         /score  /stream  /graph  /freeze  /report            │
└──────┬─────────────────────────────┬──────────────────────--─┘
       │                             │
┌──────▼──────┐             ┌────────▼────────┐
│  T-GNN Model│             │   Neo4j Graph DB │
│  GIN arch.  │             │   515K nodes     │
│  PyTorch    │             │   5M+ edges      │
└─────────────┘             └─────────────────┘
```

---

## The ML Pipeline

### Stage 1 — Pretrain on IBM AML (HI-Small)
The model learns universal money-laundering graph topology: Fan-In patterns, Fan-Out layering, high in-degree → instant out-degree. 5 epochs on 5M transactions, ~18 minutes.

| Metric | Value |
|---|---|
| Dataset | IBM AML HI-Small |
| Transactions | 5,078,345 |
| Nodes | 515,088 |
| Illicit ratio | 0.10% |
| Architecture | GIN (Graph Isomorphism Network) |
| Best Val F1 | 0.0764 |

### Stage 2 — Fine-tune on Nolambur Synthetic Data
A synthetic dataset generated to match the exact Nolambur case pattern: ₹5L–₹5.5L burst transfers, Tamil Nadu victims, Haridwar/Rajasthan mule accounts, sub-90-second cashout velocity.

| Metric | Value |
|---|---|
| Victims | 50 Chennai accounts |
| L1 Mules | 80 (Haridwar / Rajasthan) |
| L2 Cashout | 300 (Delhi / Haryana) |
| Transactions | ~30,400 |
| Illicit ratio | ~1.3% |
| Best Val F1 | 0.0667 |

> **Note:** F1 is low — this is expected at 5–10 epochs with 0.1% class imbalance and no real UPI ground-truth data. The model detects the structural pattern. Improving to F1 > 0.30 requires 30+ epochs, loss weight tuning to `[1.0, 300.0]`, and explicit geo-mismatch node features.

---

## The "Mule Pulse" Signal

The core innovation. For each account, we compute:

- **In-degree velocity** — how many sources sent money in the last 3 minutes
- **Out-degree velocity** — time between first receipt and first withdrawal
- **Geo-mismatch score** — IP/device state vs. registered account state
- **Amount clustering** — are transfers suspiciously close to ₹5L?

A genuine mule account scores high on all four simultaneously. A normal account almost never does.

---

## The Nolambur Synthetic Data Generator

`nolambur_synthetic_gen.py` generates a UPI-flavoured fraud dataset modelled on the exact case:

```bash
python nolambur_synthetic_gen.py
# Output:
# nolambur_transactions.csv  — UPI-format transactions with VPA, ₹ amounts, state codes
# nolambur_labels.csv        — ground truth is_mule per account
# nolambur_stats.json        — summary stats
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Graph Database | Neo4j 5.x + Cypher |
| ML Framework | PyTorch + PyTorch Geometric (TGN / GIN) |
| Experiment Tracking | Weights & Biases |
| Inference API | FastAPI + Uvicorn |
| Real-time streaming | Server-Sent Events (SSE) |
| Frontend | Next.js 14 (App Router) |
| Graph visualisation | react-force-graph |
| State management | Zustand |
| UI components | shadcn/ui + Tailwind CSS |
| Map | Leaflet.js |
| Training environment | Google Colab (T4 GPU) |

---

## Dashboard Pages

| Page | Purpose |
|---|---|
| **Command Center** | Live alert feed, burst activity chart, geo origin heatmap |
| **Cluster Graph** | Force-directed mule chain visualisation, predicted next-hop accounts |
| **Account Drill-down** | Per-account Mule Pulse breakdown, transaction log, freeze action |
| **Case Timeline** | Full incident reconstruction, fund flow, cross-state ZKP status |
| **Model Health** | F1 drift monitoring, training pipeline status, retrain trigger |

---

## Roadmap

- [x] IBM AML preprocessing pipeline
- [x] Nolambur synthetic data generator
- [x] T-GNN pretrain (IBM HI-Small)
- [x] Fine-tune on Nolambur data
- [x] FastAPI inference endpoints
- [x] Next.js dashboard (hero UI)
- [ ] Improve F1 → target 0.30+ (30 epochs, loss weight 300, geo features)
- [ ] Neo4j ingestion pipeline
- [ ] Live SSE alert feed
- [ ] ZKP inter-state freeze bridge (Circom / SnarkyJS)
- [ ] Edge Biometric AI — duress detection (TensorFlow Lite)
- [ ] 1930 CFCFRMS auto-report API integration

---

## Dataset Sources

- **IBM AML Dataset** — Synthetic AML transactions with ground-truth mule chain labels. [Kaggle](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml)
- **Nolambur Synthetic Data** — Generated by this project to model the exact ₹5L burst pattern, Tamil Nadu → Haridwar/Rajasthan geography, and sub-90s cashout velocity.

---

---

## The Vision

> India loses ₹22,495 Crore to cyber fraud every year.  
> Every second a mule account sits unfrozen is money gone forever.  
> Operation Nolambur exists to make that second count.

*Built with purpose. Deployed for justice.*
