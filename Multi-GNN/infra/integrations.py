"""Outbound integrations: freeze instructions to the bank gateway and complaints to the
1930 / CFCFRMS portal, delivered through a persistent outbox.

Every outbound call is first written to the integration_outbox table, then a worker
thread POSTs it, retrying with exponential backoff (2, 4, 8, ... s; failed after
MAX_ATTEMPTS). A crash or a gateway outage loses nothing: pending rows are picked up
again when the next process starts the worker. Receivers get an Idempotency-Key
header, so a retry after a lost response is safe.

By default both targets are the bridge's own sandbox (infra/sandbox.py), so the whole
path is exercised over real HTTP without touching a bank or the government portal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from typing import Any

import requests

from . import settings
from .store import get_store

MAX_ATTEMPTS = 6
POLL_SECONDS = 1.0
TIMEOUT = 10

_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(body: bytes, header: str | None, secret: str) -> bool:
    return bool(header) and hmac.compare_digest(sign(body, secret), header or "")


def _post(kind: str, target: str, payload: dict[str, Any], idempotency_key: str) -> requests.Response:
    body = canonical(payload)
    headers = {"Content-Type": "application/json", "Idempotency-Key": idempotency_key}
    if kind.startswith("gateway."):
        headers["X-Nolambur-Signature"] = sign(body, settings.GATEWAY_WEBHOOK_SECRET)
    return requests.post(target, data=body, headers=headers, timeout=TIMEOUT)


def _deliver(item: dict[str, Any]) -> None:
    store = get_store()
    attempts = item["attempts"] + 1
    try:
        response = _post(item["kind"], item["target"], item["payload"], f"outbox-{item['id']}")
        body: Any = response.json() if response.content else None
        if response.status_code < 300:
            store.outbox_update(item["id"], status="delivered", attempts=attempts, delivered_at=time.time(), response=body, last_error=None)
            return
        error = f"HTTP {response.status_code}: {json.dumps(body)[:300] if body is not None else ''}"
        permanent = 400 <= response.status_code < 500 and response.status_code not in (408, 429)
    except (requests.RequestException, ValueError) as exc:
        error, permanent = f"{type(exc).__name__}: {exc}"[:300], False
    if permanent or attempts >= MAX_ATTEMPTS:
        store.outbox_update(item["id"], status="failed", attempts=attempts, last_error=error)
    else:
        store.outbox_update(item["id"], attempts=attempts, last_error=error, next_attempt_at=time.time() + 2**attempts)


def _run_worker() -> None:
    store = get_store()
    while True:
        try:
            for item in store.outbox_due():
                _deliver(item)
        except Exception:  # database hiccup: try again next poll
            pass
        time.sleep(POLL_SECONDS)


def ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="rail-outbox", daemon=True)
            _worker.start()


def deliver_now(item_id: int) -> dict[str, Any] | None:
    """Try one outbox item immediately (used where the caller wants the response inline)."""
    store = get_store()
    item = store.outbox_get(item_id)
    if item and item["status"] == "pending":
        _deliver(item)
    return store.outbox_get(item_id)


# ---------------------------------------------------------------------- senders


def queue_freeze_instruction(reference: str, vpa: str, account_id: str | None, state: str | None, reason: str) -> dict[str, Any]:
    payload = {
        "event": "account.freeze_requested",
        "reference": reference,
        "account": {"vpa": vpa, "accountId": account_id, "state": state},
        "reason": reason,
        "requestedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requestedBy": "operation-nolambur-risk-console",
    }
    item_id = get_store().outbox_add("gateway.freeze", settings.GATEWAY_WEBHOOK_URL, payload, reference)
    ensure_worker()
    return {"outboxId": item_id, "target": settings.GATEWAY_WEBHOOK_URL, "sandbox": settings.is_sandbox(settings.GATEWAY_WEBHOOK_URL), "status": "pending"}


def submit_1930_complaint(reference: str, vpas: list[str], summary: str, total_amount_inr: float) -> dict[str, Any]:
    """POST the complaint now; if the portal is unreachable, leave it in the outbox for retry."""
    payload = {
        "category": "online_financial_fraud",
        "subCategory": "upi_mule_chain",
        "reportingEntity": "operation-nolambur-risk-console",
        "internalReference": reference,
        "totalAmountInr": float(total_amount_inr),
        "suspects": [{"vpa": v} for v in vpas],
        "description": summary,
    }
    target = f"{settings.CFCFRMS_URL}/complaints"
    item_id = get_store().outbox_add("cfcfrms.complaint", target, payload, reference)
    item = deliver_now(item_id) or {}
    ensure_worker()
    response = item.get("response") or {}
    return {
        "outboxId": item_id,
        "target": target,
        "sandbox": settings.is_sandbox(target),
        "status": item.get("status", "pending"),
        "acknowledgementNo": response.get("acknowledgementNo"),
        "error": item.get("last_error"),
    }


def describe() -> dict[str, Any]:
    from agents import config as agent_config

    twilio = bool(agent_config.TWILIO_ACCOUNT_SID and agent_config.TWILIO_AUTH_TOKEN and agent_config.TWILIO_FROM_NUMBER)
    return {
        "gateway": {"url": settings.GATEWAY_WEBHOOK_URL, "sandbox": settings.is_sandbox(settings.GATEWAY_WEBHOOK_URL), "signed": True},
        "cfcfrms": {"url": settings.CFCFRMS_URL, "sandbox": settings.is_sandbox(settings.CFCFRMS_URL)},
        "sms": {"provider": "twilio", "mode": "live" if twilio else "dry_run", "recipients": len(agent_config.OFFICER_PHONE_NUMBERS)},
        "workerAlive": bool(_worker and _worker.is_alive()),
        "recent": [
            {k: item[k] for k in ("id", "kind", "reference", "status", "attempts", "last_error", "created_at", "delivered_at", "response")}
            for item in get_store().outbox_recent(12)
        ],
    }
