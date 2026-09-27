"""Tool implementations - plain functions, testable without the Anthropic SDK.

REAL   : score_transaction, score_transfer_chain, get_account_profile,
         list_downstream_transfers, watch_downstream_stream
SIMULATED (labelled, no external system touched, appended to action_log.jsonl):
         check_suspect_registry, freeze_account, file_1930_report
"""

from __future__ import annotations

import time
from typing import Any

from . import bridge_client, notifications
from .audit import record_action
from .config import SCORE_ACT, SCORE_INVESTIGATE
from .nolambur_data import account_profile, downstream_transfers, resolve_account
from .transaction_graph import chain_to_predict_payload, transaction_to_predict_payload

_MODEL_CAVEAT = (
    "The T-GNN checkpoint is finetune-only (no IBM AML pretrain), val F1 ~0.07. "
    "Read the score as 'how mule-shaped is this edge', not a calibrated probability. "
    "Corroborate with an independent signal before any irreversible action."
)


def _interpret(probability: float) -> str:
    if probability >= SCORE_ACT:
        return "high mule probability"
    if probability >= SCORE_INVESTIGATE:
        return "elevated - investigate"
    if probability >= 0.40:
        return "ambiguous"
    return "low"


# --------------------------------------------------------------------------- real

def score_transaction(
    sender_vpa: str,
    receiver_vpa: str,
    amount_inr: float,
    timestamp: str = "",
) -> dict[str, Any]:
    payload, context = transaction_to_predict_payload(
        sender_vpa, receiver_vpa, amount_inr, timestamp or None
    )
    response = bridge_client.predict(payload)
    prediction = (response.get("predictions") or [{}])[0]
    probability = float(prediction.get("fraud_probability", 0.0))
    return {
        "fraud_probability": round(probability, 4),
        "predicted_label": prediction.get("predicted_label"),
        "interpretation": _interpret(probability),
        "scored_with_background_graph": response.get("scored_with_background_graph", False),
        "linked_accounts": response.get("linked_accounts", 0),
        "features_normalized": response.get("normalized", False),
        "scored_edge": context,
        "model_caveat": _MODEL_CAVEAT,
    }


def score_transfer_chain(legs: list[dict[str, Any]]) -> dict[str, Any]:
    if not legs:
        return {"error": "legs must be a non-empty list of {sender, receiver, amount_inr, timestamp?}"}
    payload, context = chain_to_predict_payload(legs)
    response = bridge_client.predict(payload)
    by_edge = {int(item["edge_index"]): item for item in response.get("predictions", [])}
    scored = []
    for position, leg in enumerate(context["legs"]):
        prediction = by_edge.get(position, {})
        probability = float(prediction.get("fraud_probability", 0.0))
        scored.append({**leg, "fraud_probability": round(probability, 4), "interpretation": _interpret(probability)})
    return {
        "legs": scored,
        "nodes": context["nodes"],
        "scored_with_background_graph": response.get("scored_with_background_graph", False),
        "linked_accounts": response.get("linked_accounts", 0),
        "model_caveat": _MODEL_CAVEAT,
    }


def get_account_profile(vpa: str) -> dict[str, Any]:
    return account_profile(vpa)


def list_downstream_transfers(vpa: str, limit: int = 20) -> dict[str, Any]:
    transfers = downstream_transfers(vpa, limit=max(1, min(limit, 100)))
    return {
        "vpa": resolve_account(vpa).vpa,
        "transfer_count": len(transfers),
        "transfers": transfers,
        "source": "Nolambur synthetic dataset (historical rows, not a live ledger)",
    }


def watch_downstream_stream(seconds: int = 6, filter_state: str = "") -> dict[str, Any]:
    events = bridge_client.collect_stream(max_seconds=float(min(max(seconds, 2), 15)))
    if filter_state:
        needle = filter_state.lower()
        events = [
            event
            for event in events
            if needle in str(event.get("statePair", "")).lower()
            or needle in str(event.get("label", "")).lower()
        ]
    return {
        "source": "GNN bridge /stream - replay of scored Nolambur synthetic transactions, not a live feed",
        "event_count": len(events),
        "events": events[:25],
    }


# ---------------------------------------------------------------------- simulated

def check_suspect_registry(vpa: str) -> dict[str, Any]:
    account = resolve_account(vpa)
    listed = account.is_mule  # simulated: derived from the synthetic label
    return {
        "simulated": True,
        "source": "MOCK NPCI suspect registry - no real registry access in this environment",
        "vpa": account.vpa,
        "listed": listed,
        "record": {
            "category": "mule_account" if listed else None,
            "reports": 3 if listed else 0,
            "first_reported": "2024-03-15" if listed else None,
        },
        "note": "Wire to the real NPCI Suspect Registry API for production use.",
    }


def freeze_account(vpa: str, reason: str) -> dict[str, Any]:
    account = resolve_account(vpa)
    reference = f"FRZ-{int(time.time()) % 100000:05d}"
    record = {
        "action": "freeze_account",
        "vpa": account.vpa,
        "account_id": account.account_id or None,
        "state": account.state or None,
        "reason": reason,
        "freeze_reference": reference,
        "simulated": True,
    }
    record_action(record)
    return {
        **record,
        "note": "SIMULATED - no bank/RBI freeze API connected. Recorded to agents/action_log.jsonl.",
    }


def file_1930_report(vpas: list[str], case_summary: str, total_amount_inr: float) -> dict[str, Any]:
    acknowledgement = f"CFCFRMS-{int(time.time()) % 1000000:06d}"
    record = {
        "action": "file_1930_report",
        "vpas": [resolve_account(vpa).vpa for vpa in vpas],
        "total_amount_inr": float(total_amount_inr),
        "case_summary": case_summary,
        "acknowledgement_no": acknowledgement,
        "simulated": True,
    }
    record_action(record)
    return {
        **record,
        "note": "SIMULATED - no CFCFRMS/1930 API connected. Recorded to agents/action_log.jsonl.",
    }


def notify_officer(message: str, priority: str = "high") -> dict[str, Any]:
    tag = {"low": "INFO", "medium": "NOTICE", "high": "ALERT", "critical": "CRITICAL"}.get(
        priority.lower(), "ALERT"
    )
    return notifications.send_sms(f"[Operation Nolambur - {tag}] {message}")
