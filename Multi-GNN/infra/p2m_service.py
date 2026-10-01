"""The P2M (aggregator-side) engine behind the bridge: /rail/p2m/* (reports/README.md 3.5).

At start-up a background thread waits until the P2P engine is ready (the free instance has 512 MB,
and the P2P load is the peak), then loads the fresh judging draw of the P2M data (stream 2,
committed as nolambur_p2m_s2/; regenerated with p2m_gen.py only if missing), replays it with the
committed rules p1.0 parameters, and keeps the result. This is a finished replay of synthetic merchants, not
a live stream: the console says so.

    GET  /rail/p2m/status              warming | ready | error, dataset facts, parameters
    GET  /rail/p2m/merchants           every merchant, flagged ones first
    GET  /rail/p2m/merchants/{id}      payments, collect outcomes, settlement batches, alerts, peers
    GET  /rail/p2m/evaluation          this draw's metrics, and every draw in reports/p2m/
    POST /rail/p2m/onboarding          D4 at onboarding: who else settles to this account?
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from infra import p2m

ROOT = Path(__file__).resolve().parent.parent
STREAM = int(os.getenv("P2M_STREAM", "2"))
FOLDER = ROOT / f"nolambur_p2m_s{STREAM}"
DETECTORS = {
    "D1": "Big tickets from first-time payers",
    "D2": "First-time payers from many states",
    "D3": "Collect requests to strangers, mostly failing",
    "D4": "Settlement account shared across entities",
}


def _iso(t: float | None) -> str | None:
    """Back to the data's own naive clock (p2m.Data reads timestamps as local time)."""
    return None if t is None else datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


class P2MService:
    def __init__(self, wait_for: Any = None) -> None:
        self.wait_for = wait_for  # a callable that turns true once the P2P engine has loaded
        self.status = "starting"
        self.error: str | None = None
        self.data: p2m.Data | None = None
        self.eng: p2m.Engine | None = None
        self.params: dict[str, Any] = {}
        self.evaluation: dict[str, Any] | None = None
        self.started = time.time()
        self.seconds: float | None = None

    def start(self) -> None:
        threading.Thread(target=self._load, name="p2m-load", daemon=True).start()

    def _load(self) -> None:
        self.status = "waiting"  # for the P2P engine: loading both at once could exceed the instance's memory
        deadline = time.time() + 900
        while self.wait_for is not None and not self.wait_for() and time.time() < deadline:
            time.sleep(2)
        self.status = "warming"
        self.started = time.time()
        try:
            if not (FOLDER / "merchants.csv").exists():
                subprocess.run([sys.executable, str(ROOT / "p2m_gen.py"), "--stream", str(STREAM), "--out", str(FOLDER)],
                               check=True, stdout=subprocess.DEVNULL, cwd=ROOT)
            self.params = json.loads(p2m.PARAMS.read_text(encoding="utf-8"))
            self.data = p2m.Data(FOLDER)
            p2m._CAT_P99.clear()
            p2m._CAT_P99.update(self.params["catP99"])
            self.eng = p2m.Engine(self.data, self.params).run()
            self.evaluation = p2m.evaluate(self.data, self.params, f"stream {STREAM}", eng=self.eng)
            self._index()
            self.status = "ready"
            self.seconds = round(time.time() - self.started, 1)
        except Exception as exc:  # surfaced on /status; the rest of the bridge keeps running
            logging.exception("P2M load failed")
            self.status, self.error = "error", f"{type(exc).__name__}: {exc}"

    def _index(self) -> None:
        d, eng = self.data, self.eng
        assert d is not None and eng is not None
        pays = d.payments
        self.inflow = pays.groupby("merchant_id")["amount_inr"].agg(["count", "sum"]).to_dict("index")
        self.alerts_by: dict[str, list] = defaultdict(list)
        for a in eng.alerts:
            self.alerts_by[a["merchant"]].append(a)
        self.batches_by: dict[str, list] = defaultdict(list)
        for b in eng.batch_log:
            self.batches_by[b["merchant"]].append(b)
        self.peers: dict[str, list] = defaultdict(list)
        for mid, m in d.m.items():
            self.peers[m["settlement_account"]].append(mid)

    # ------------------------------------------------------------------ views

    def ready(self) -> None:
        if self.status != "ready":
            raise HTTPException(status_code=503, detail={"status": self.status, "error": self.error})

    def facts(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "error": self.error, "stream": STREAM, "rules": self.params.get("rules"), "loadSeconds": self.seconds}
        if self.status == "ready":
            d = self.data
            assert d is not None
            out |= {
                "merchants": len(d.m), "payments": int(len(d.payments)), "collects": int(len(d.collects)),
                "window": [_iso(d.start), _iso(d.start + d.days * p2m.DAY)], "testDays": [_iso(d.start + p2m.TEST[0] * p2m.DAY), _iso(d.start + p2m.TEST[1] * p2m.DAY)],
                "parameters": {k: v for k, v in self.params.items() if k in ("d1Count", "d2States", "d3Requests", "d3FailShare")} | {"catP99": self.params.get("catP99")},
                "detectors": DETECTORS,
                "note": "A finished replay of synthetic merchants (p2m_gen.py, fresh judging draw), not a live stream.",
            }
        return out

    def _merchant_row(self, mid: str) -> dict[str, Any]:
        d = self.data
        assert d is not None and self.eng is not None
        m = d.m[mid]
        alerts = self.alerts_by.get(mid, [])
        batches = self.batches_by.get(mid, [])
        stats = self.inflow.get(mid, {"count": 0, "sum": 0})
        return {
            "id": mid, "vpa": m["vpa"], "category": m["category"], "state": m["state"], "legalEntity": m["legal_entity"],
            "settlementAccount": m["settlement_account"], "onboardedAt": m["onboarded_at"], "chain": m["chain"] or None,
            "payments": int(stats["count"]), "inflow": float(stats["sum"]),
            "detectors": sorted({a["detector"] for a in alerts}), "firstAlert": _iso(min((a["t"] for a in alerts), default=None)),
            "heldBatches": sum(1 for b in batches if b["held"]), "heldAmount": sum(b["amount"] for b in batches if b["held"]),
            "sharedSettlement": len(self.peers[m["settlement_account"]]) - 1,
            "truth": {"fraud": bool(m["is_fraud"]), "scenario": m["scenario"] or None},
        }

    def merchants(self) -> list[dict[str, Any]]:
        self.ready()
        assert self.data is not None
        rows = [self._merchant_row(mid) for mid in self.data.m]
        return sorted(rows, key=lambda r: (r["firstAlert"] is None, r["firstAlert"] or "", -r["inflow"]))

    def merchant(self, mid: str) -> dict[str, Any]:
        self.ready()
        d = self.data
        assert d is not None
        if mid not in d.m:
            raise HTTPException(status_code=404, detail="no such merchant")
        pays = d.payments[d.payments["merchant_id"] == mid].sort_values("timestamp")
        cols = d.collects[d.collects["merchant_id"] == mid]
        outcomes = {k: int(v) for k, v in cols.groupby(["known_payer", "outcome"]).size().items()} if len(cols) else {}
        return {
            **self._merchant_row(mid),
            "alerts": [{"detector": a["detector"], "label": DETECTORS[a["detector"]], "at": _iso(a["t"]), "why": a["why"]} for a in self.alerts_by.get(mid, [])],
            "batches": [{"at": _iso(b["t"]), "payments": b["payments"], "amount": b["amount"], "held": b["held"], "holdUntil": _iso(b["holdUntil"]),
                         "fraudAmount": b["fraudAmount"]} for b in self.batches_by.get(mid, [])],
            "collects": {
                "customers": {o: n for (known, o), n in outcomes.items() if known},
                "nonCustomers": {o: n for (known, o), n in outcomes.items() if not known},
            },
            "recentPayments": [
                {"at": r.timestamp, "payerVpa": r.payer_vpa, "payerState": r.payer_state, "amount": float(r.amount_inr), "initiation": r.initiation, "fraud": bool(r.is_fraud)}
                for r in pays.tail(150).itertuples(index=False)
            ][::-1],
            "peers": [self._merchant_row(p) for p in self.peers[d.m[mid]["settlement_account"]] if p != mid],
        }

    def evaluation_view(self) -> dict[str, Any]:
        self.ready()
        draws = []
        for f in sorted((ROOT / "reports" / "p2m").glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            draws.append({"file": f"reports/p2m/{f.name}", "label": r["label"], "recall": r["recall"], "activeFraudMerchants": r["activeFraudMerchants"],
                          "activeFlagged": r["activeFlagged"], "precision": r["precision"], "holdPrecision": r["secondary"]["holdDetectorsPrecision"],
                          "fraudHeldShare": r["fraudHeldShare"], "medianSecondsToHoldAlert": r["secondary"]["medianSecondsToHoldAlert"]})
        return {"thisDraw": {k: v for k, v in (self.evaluation or {}).items() if k != "folder"}, "draws": draws,
                "caveats": "reports/README.md 3.5: tiny samples (2-4 fresh fraud merchants a draw), easy by construction, held money is the window to act, costs are floors."}

    def onboarding(self, settlement_account: str, legal_entity: str) -> dict[str, Any]:
        self.ready()
        d = self.data
        assert d is not None and self.eng is not None
        others = [self._merchant_row(p) for p in self.peers.get(settlement_account.strip(), [])]
        other_entities = [o for o in others if o["legalEntity"] != legal_entity.strip()]
        flagged = [o for o in others if o["detectors"]]
        if flagged and any(set(o["detectors"]) - {"D4"} for o in flagged):
            decision, why = "hold", f"{len(flagged)} merchant(s) settling to this account are already under alert for payment activity."
        elif other_entities:
            decision, why = "review", (f"This settlement account already receives payouts for {len(other_entities)} merchant(s) under other declared entities. "
                                       "A family business or a group company looks the same as a settlement ring here: review, don't block.")
        elif others:
            decision, why = "approve", f"Shared with {len(others)} merchant(s) under the same declared entity (a chain)."
        else:
            decision, why = "approve", "No other merchant settles to this account."
        return {"decision": decision, "reason": why, "sharedWith": others, "detector": "D4"}


class OnboardingBody(BaseModel):
    settlementAccount: str = Field(min_length=3, max_length=64)
    legalEntity: str = Field(min_length=1, max_length=64)


def mount(app: FastAPI, wait_for: Any = None) -> P2MService:
    svc = P2MService(wait_for)
    router = APIRouter(prefix="/rail/p2m")

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return svc.facts()

    @router.get("/merchants")
    async def merchants() -> list[dict[str, Any]]:
        return svc.merchants()

    @router.get("/merchants/{mid}")
    async def merchant(mid: str) -> dict[str, Any]:
        return svc.merchant(mid)

    @router.get("/evaluation")
    async def evaluation() -> dict[str, Any]:
        return svc.evaluation_view()

    @router.post("/onboarding")
    async def onboarding(body: OnboardingBody) -> dict[str, Any]:
        return svc.onboarding(body.settlementAccount, body.legalEntity)

    app.include_router(router)
    if os.getenv("RAIL_P2M", "1") != "0":
        svc.start()
    else:
        svc.status = "disabled"
    return svc
