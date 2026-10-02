# Protocol: the same approach on data this project did not generate

Written 2026-10-01, before either dataset was loaded or inspected. Only the files' existence, size and checksum
were checked. The pass marks below are fixed now and are not changed after the runs. A miss is reported as a miss.

**The objection this answers.** The rules and the synthetic data were written by the same person. So the
results so far may only show that the rules fit their own generator. These two datasets were made by others.

| Dataset | Who made it | Real or synthetic | Task |
|---|---|---|---|
| Elliptic ([Weber et al. 2019](https://arxiv.org/abs/1908.02591)) | Elliptic, from the Bitcoin blockchain | **Real**, labelled by heuristics | Is a transaction (node) illicit? |
| IBM AML HI-Small ([Altman et al. 2023](https://arxiv.org/abs/2306.16424)) | IBM's AMLworld generator | Synthetic, not ours | Is a transfer (edge) laundering? |

**Sources of the files.**
- Elliptic: `https://data.pyg.org/datasets/elliptic/` (PyTorch Geometric's mirror).
- IBM HI-Small: Hugging Face mirror `eexzzm/IBM-Transactions-for-Anti-Money-Laundering-HI-Small-Trans`. Its CSV has SHA-256
  `b19d39f5…c5b040`, the same file as the independent mirror `bbfizp/AMLSim-HI-Small`. Before any modelling it must match
  IBM's published size of 5,078,345 transactions; if not, the IBM runs are void.

## Common rules

- **Temporal splits only.** Everything is fitted on the earliest period, the threshold is picked on the next one, and
  results come from the last period only.
- **Thresholds and rule parameters come from the training period only.** No look at test labels until the final evaluation.
- **Baselines run alongside,** including the published ones, and a tabular model with no graph.
- **Seeds.** Three seeds for every GNN on Elliptic. One on IBM (CPU budget), stated as such.
- **CPU budget for IBM:** 10 hours. If an epoch takes over 2 hours, train fewer epochs and report the model as
  under-trained. The test set is never shrunk to fit.
- **Intervals.** 95% Wilson intervals on precision and recall.

## Elliptic

**Split** (as Weber et al.): time steps 1–34 for fitting, 35–49 for the test. Inside 1–34, steps 1–29 fit and steps 30–34
pick the threshold (maximum illicit F1). Unknown-label nodes stay in the graph but are not scored.

**Models.**
- **RF-LF:** Random Forest (50 trees, max_features 50, as the paper) on the 94 local features.
- **RF-AF:** the same on all 166 features, for reference only.
- **GIN:** a 2-layer GIN node classifier on the local features. It is this project's GNN family; GINe needs edge
  features, and Elliptic has none. Weighted cross-entropy, illicit weight picked on steps 30–34.
- **RF-LF + GIN:** Random Forest on the local features plus the GIN's node embeddings.
- **Hop rule:** the one rule that transfers: flag a transaction if a transaction paying into it scored at or above the
  threshold. One hop only, as `hop_from_flagged`. The amount, cap and window rules need amounts and account
  identities, which Elliptic does not have. They are not tested here.

**Pass marks** (illicit class, test steps 35–49, mean of 3 seeds):

| ID | Claim | Pass if |
|---|---|---|
| E1 | The GNN matches published graph models | GIN F1 ≥ 0.628 (Weber's GCN) |
| E2 | The graph adds value beyond node features | RF-LF + GIN F1 ≥ RF-LF F1 + 0.02, and higher in all 3 seeds |
| E3 | The hop rule adds recall at usable precision | GIN + hop recall ≥ GIN recall + 0.05, with precision ≥ 0.50 |

Reported without a mark: F1 per test step, and before vs after step 43 (Weber reports that all models fail after a dark
market shut down).

## IBM AML HI-Small

**Split** (as Altman et al.): transactions ordered by time, 60% fit, 20% validation (threshold), 20% test.

**Models.**
- **Tabular:** histogram gradient boosting on the edge's own features (log amount, currencies, payment format, hour). No graph.
- **GINe:** this repository's Multi-GNN edge classifier (`main.py`), trained from scratch on HI-Small.
- **Rules:** this project's account-level detectors, with parameters set from the fitting period's clean accounts only:
  - pass-through: share forwarded within 24 h, and a floor at the clean p99;
  - fan-in: distinct new payers in 24 h at the clean p99;
  - hop from a flagged account.
  The UPI cap and ₹ floors do not apply; their thresholds are recalibrated, not reused.
- **Rules + GINe:** an account is alerted if a rule fires or one of its edges scores at or above the threshold.

**Pass marks** (test period):

| ID | Claim | Pass if |
|---|---|---|
| I1 | The GNN matches a published baseline | GINe minority F1 ≥ 28.7% (Altman's GIN) |
| I2 | The graph adds value | GINe F1 ≥ tabular F1 + 5 points |
| I3 | Transplanted rules add coverage | Account recall, rules + GINe ≥ GINe alone + 5 points, with precision no more than 10 points lower |

Reported without a mark: GINe against Altman's best (63.2%, gradient boosting with graph features), and the
rules' own account-level precision and recall.

## What a result means

- **E1–E3 pass:** the approach holds on real data with a temporal split. The objection is answered for the graph part.
- **E1 or E2 fails:** on real data the graph does not beat node features. Say so; the pitch then rests on rules and features.
- **I3 fails:** the rules do not travel to another generator. That would confirm the objection for the rules.
