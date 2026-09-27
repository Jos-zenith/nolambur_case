"""Shared configuration for the agent orchestrator.

Kept deliberately small and env-overridable so the same code runs against a local
bridge, a deployed one, or in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

MULTI_GNN_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = Path(__file__).resolve().parent

# The FastAPI GNN inference bridge (bridge_api.py). Same default as the Next.js
# proxy in app/api/inference/route.ts.
BRIDGE_URL = os.getenv("GNN_FASTAPI_URL", "http://127.0.0.1:8001").rstrip("/")

# Claude model for the orchestrator loop. Opus 5 is the default; set
# AGENT_MODEL=claude-sonnet-5 to roughly halve the per-run cost.
ORCHESTRATOR_MODEL = os.getenv("AGENT_MODEL", "claude-opus-5")

TRANSACTIONS_CSV = MULTI_GNN_DIR / "nolambur_transactions.csv"
LABELS_CSV = MULTI_GNN_DIR / "nolambur_labels.csv"

# Simulated freeze / 1930-report / SMS actions are appended here so a run leaves
# an auditable artifact even though nothing hits a real system.
ACTION_LOG = AGENTS_DIR / "action_log.jsonl"

# Twilio SMS alerts (agents/notifications.py). With the first three set, notify_officer
# sends for real; otherwise it runs dry (logs to action_log.jsonl, delivery="dry_run").
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
OFFICER_PHONE_NUMBERS = [
    number.strip() for number in os.getenv("OFFICER_PHONE_NUMBERS", "").split(",") if number.strip()
]

# Decision thresholds. The finetune-only GIN checkpoint has val F1 ~0.07, so
# these are NOT the only gate - the orchestrator prompt requires an independent
# corroborating signal before any irreversible action.
SCORE_INVESTIGATE = 0.72  # at/above: pull profile + registry, trace downstream
SCORE_ACT = 0.85          # at/above AND corroborated: freeze + file 1930 report
