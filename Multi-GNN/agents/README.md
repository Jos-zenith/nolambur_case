# Operation Nolambur — agent orchestrator

A thin end-to-end slice of the multi-agent idea: **Claude runs the coordination
loop** and decides the tool order itself, rather than hard-coded control flow.

```
flagged transaction
      │
      ▼
┌─────────────┐   score_transaction / score_transfer_chain      ← real T-GNN, real graph
│  DETECTOR   │
└─────┬───────┘
      ▼
┌─────────────┐   get_account_profile / list_downstream_transfers ← real Nolambur data
│ INVESTIGATOR│   check_suspect_registry                          ← SIMULATED (mock NPCI)
└─────┬───────┘
      ▼
┌─────────────┐   freeze_account / file_1930_report               ← SIMULATED (action_log.jsonl)
│ COORDINATOR │   notify_officer                                  ← real Twilio SMS if configured
└─────┬───────┘
      ▼
┌─────────────┐   watch_downstream_stream                         ← real /stream replay
│  MONITOR    │   notify_officer                                  ← real Twilio SMS if configured
└─────────────┘
      ▼
  CASE DECISION  (structured JSON: verdict / confidence / corroborating signals / actions)
```

## What's real vs. simulated

| Tool | Backing |
|---|---|
| `score_transaction`, `score_transfer_chain` | real GIN checkpoint via `bridge_api.py` `/predict`, spliced onto the real background graph |
| `get_account_profile`, `list_downstream_transfers` | real rows from `nolambur_transactions.csv` + `nolambur_labels.csv` |
| `watch_downstream_stream` | real `bridge_api.py` `/stream` (a **replay** of scored synthetic transactions, not a live feed) |
| `check_suspect_registry` | **simulated** — mock NPCI registry, result derived from the synthetic `is_mule` label |
| `freeze_account`, `file_1930_report` | **simulated** — no bank / RBI / CFCFRMS API; appended to `action_log.jsonl` |
| `notify_officer` | **real Twilio SMS** when `TWILIO_*` env vars are set; otherwise dry-run (logged to `action_log.jsonl`) |

The orchestrator prompt tells Claude which is which, and requires an independent
corroborating signal before any irreversible (simulated) action — the finetune-only
checkpoint has val F1 ≈ 0.07, so a high score alone is never enough.

## The transaction → GNN shim

`/predict` takes a graph-tensor payload, not a transaction. `transaction_graph.py`
translates:

- edge features in the trained order — `[Timestamp, Amount Received, Received Currency, Payment Format]`;
- `Timestamp` encoded as `seconds since midnight-of-the-first-dataset-row's-date + 10`,
  matching `prepare_datasets.convert_nolambur` (regression-checked in `--self-test`:
  `2024-03-17T05:22:07 → 19337`);
- each party's real account id passed as `node_account_ids`, so the bridge splices
  the edge onto the real background graph instead of scoring it in isolation.

## Run it

From `Multi-GNN/`:

```bash
# 1. deps (in addition to the Multi-GNN env)
pip install -r agents/requirements.txt

# 2. start the inference bridge in another terminal
python bridge_api.py

# 3. credentials
export ANTHROPIC_API_KEY=sk-ant-...        # or: ant auth login

# 4. (optional) real SMS alerts - skip and notify_officer runs dry
export TWILIO_ACCOUNT_SID=AC...
export TWILIO_AUTH_TOKEN=...
export TWILIO_FROM_NUMBER=+1...
export OFFICER_PHONE_NUMBERS=+9198...,+9199...

# 5. run
python -m agents --sample fraud            # victim→L1 burst, TN→Rajasthan
python -m agents --sample clean            # ordinary transfer
python -m agents --sender <vpa> --receiver <vpa> --amount 500000 [--timestamp 2024-03-15T10:32:24]
python -m agents --json '{"sender_vpa":"...","receiver_vpa":"...","amount_inr":500000}'
```

PowerShell env-var syntax: `$env:ANTHROPIC_API_KEY = "sk-ant-..."` (not `VAR=value`).

No key needed for the plumbing checks:

```bash
python -m agents --self-test               # shim + timestamp + bridge round-trip
python -m agents --test-sms "chain flagged: TN->RJ, 5.5L"   # exercise notify_officer
```

## Config (env vars)

| Var | Default | Notes |
|---|---|---|
| `GNN_FASTAPI_URL` | `http://127.0.0.1:8001` | the inference bridge |
| `AGENT_MODEL` | `claude-opus-5` | set `claude-sonnet-5` to roughly halve per-run cost |
| `ANTHROPIC_API_KEY` | — | or `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` | — | all three required for real SMS; else `notify_officer` runs dry |
| `OFFICER_PHONE_NUMBERS` | — | comma-separated E.164 recipients |

Thresholds (`SCORE_INVESTIGATE` 0.72, `SCORE_ACT` 0.85) live in `config.py`.

## Files

| File | Role |
|---|---|
| `nolambur_data.py` | read-only dataset access; VPA↔id resolution; timestamp encoding |
| `transaction_graph.py` | transaction → `/predict` payload shim (single edge + chain) |
| `bridge_client.py` | HTTP client for `/health`, `/predict`, `/stream` |
| `notifications.py` | Twilio SMS (real when configured, dry-run otherwise) |
| `audit.py` | append-only `action_log.jsonl` writer |
| `tools_impl.py` | the 9 tool functions (plain, SDK-free, unit-testable) |
| `tools.py` | JSON schemas + dispatch for the loop |
| `orchestrator.py` | the manual agentic loop + final structured CASE DECISION |
| `run_demo.py` | CLI |

## Not done here

Wiring the decision back into the Next.js dashboard (a `/api/agent` route streaming
the agent's reasoning) — that's the natural next slice.
