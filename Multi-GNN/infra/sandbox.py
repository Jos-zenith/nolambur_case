"""Sandbox counterparties, mounted on the bridge at /sandbox.

  /sandbox/gateway   a bank / payment-gateway webhook receiver for freeze instructions.
                     Verifies the HMAC signature and answers with a lien reference.
  /sandbox/cfcfrms   a stand-in for the 1930 / CFCFRMS complaint portal.
  /sandbox/npci      a stand-in for NPCI's suspect registry. Its answer is derived from the
                     synthetic dataset's mule label, so it is an oracle, not evidence.

All three are mocks. The real CFCFRMS has no public API, so the complaint shape here is
illustrative, not I4C's schema. They exist so the outbox, signing, retries and
idempotency run over real HTTP in development. Point GATEWAY_WEBHOOK_URL / CFCFRMS_URL /
NPCI_REGISTRY_URL at real endpoints and these routes are simply unused.
"""

from __future__ import annotations

import hashlib
import json
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import settings
from .integrations import verify
from .store import get_store

DISCLAIMER = "SANDBOX: mock counterparty, no bank or government system was contacted."


def _ref(prefix: str, key: str) -> str:
    return f"{prefix}-{hashlib.sha1(key.encode()).hexdigest()[:10].upper()}"


class Suspect(BaseModel):
    vpa: str = Field(min_length=3)


class Complaint(BaseModel):
    category: str
    subCategory: str | None = None
    reportingEntity: str
    internalReference: str | None = None
    totalAmountInr: float = Field(ge=0)
    suspects: list[Suspect] = Field(min_length=1)
    description: str = Field(min_length=10)


def router() -> APIRouter:
    r = APIRouter(prefix="/sandbox", tags=["sandbox"])

    @r.post("/gateway/webhooks")
    async def gateway_webhook(request: Request, x_nolambur_signature: str | None = Header(None), idempotency_key: str | None = Header(None)):
        body = await request.body()
        if not verify(body, x_nolambur_signature, settings.GATEWAY_WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="bad or missing X-Nolambur-Signature")
        event = json.loads(body)
        if event.get("event") != "account.freeze_requested":
            raise HTTPException(status_code=422, detail=f"unsupported event {event.get('event')!r}")
        store = get_store()
        lien = _ref("LIEN", idempotency_key or event.get("reference", "") or body.decode())
        existing = store.sandbox_get("gateway", lien)
        if existing:
            return {"lienReference": lien, "status": existing["status"], "duplicate": True, "note": DISCLAIMER}
        store.sandbox_add("gateway", lien, "lien_marked", {**event, "idempotencyKey": idempotency_key})
        return {"lienReference": lien, "status": "lien_marked", "duplicate": False, "note": DISCLAIMER}

    @r.get("/gateway/webhooks")
    def gateway_received(limit: int = 50):
        return {"note": DISCLAIMER, "received": get_store().sandbox_list("gateway", limit)}

    @r.post("/cfcfrms/complaints")
    def file_complaint(complaint: Complaint, idempotency_key: str | None = Header(None)):
        store = get_store()
        key = idempotency_key or complaint.internalReference or f"{time.time()}"
        ack = _ref("CFCFRMS", key)
        existing = store.sandbox_get("cfcfrms", ack)
        if existing:
            return {"acknowledgementNo": ack, "status": existing["status"], "duplicate": True, "note": DISCLAIMER}
        store.sandbox_add("cfcfrms", ack, "registered", {**complaint.model_dump(), "idempotencyKey": idempotency_key})
        return {"acknowledgementNo": ack, "status": "registered", "duplicate": False, "note": DISCLAIMER}

    @r.get("/cfcfrms/complaints/{ack}")
    def complaint_status(ack: str):
        record = get_store().sandbox_get("cfcfrms", ack)
        if not record:
            raise HTTPException(status_code=404, detail="unknown acknowledgement number")
        return {**record, "note": DISCLAIMER}

    @r.get("/npci/suspects/{vpa}")
    def npci_lookup(vpa: str, x_requester: str | None = Header(None)):
        from agents.nolambur_data import resolve_account

        account = resolve_account(vpa)
        listed = account.is_mule
        return {
            "vpa": account.vpa,
            "listed": listed,
            "record": {
                "category": "mule_account" if listed else None,
                "reports": 3 if listed else 0,
                "firstReported": "2024-03-15" if listed else None,
                "reportingBanks": sorted({account.bank}) if listed and account.bank else [],
            },
            "requester": x_requester,
            "note": DISCLAIMER + " Listing is derived from the synthetic dataset's is_mule label.",
        }

    @r.get("/cfcfrms/complaints")
    def complaints(limit: int = 50):
        return {"note": DISCLAIMER, "complaints": get_store().sandbox_list("cfcfrms", limit)}

    return r
