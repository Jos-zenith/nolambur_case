"""Payment-rail replay engine: the backend of the Merchant Risk Console.

Replays the real Nolambur dataset (nolambur_transactions.csv) in timestamp order,
attaches the trained GIN checkpoint's score to every transaction, and runs the
rule detectors on each transaction as it arrives. Analyst actions go through the
agent tools in agents/tools_impl.py, so freezes and 1930 reports land in
agents/action_log.jsonl like every other agent action.

What each number is:
  * gnn score   - the checkpoint's fraud probability for that edge from one forward
                  pass over the full graph (bridge_api._load_background_scores), the
                  same context the model was evaluated in. It is not an online score:
                  the pass sees edges the replay has not reached yet.
  * detectors   - see only replayed rows (amount, time, sender/receiver, state) and
                  their own alert history. They never read is_fraud, layer or role.
  * labels      - is_fraud / role are used only to report precision and recall.

Live payments (infra/ingest.py) enter through RailEngine.ingest_live: from the webhook
in any mode, or from Kafka / Kinesis when RAIL_SOURCE selects them. They are scored
online (one /predict splice per batch) and carry no label; their accounts' roles are
looked up by id, so a streamed copy of the CSV is still measurable.

Platform adapters (infra/): the audit trail and every analyst decision go to the store
(SQLite or Postgres), multi-hop queries go to the graph store (memory or Neo4j), and
freezes / 1930 reports leave through the integration outbox.

Auto-hold (RAIL_AUTO_HOLD, on by default): a critical alert whose evidence the model
also scores >= 0.9 puts the account on hold at once, actor "system". A hold blocks
transfers exactly like a freeze but stays inside the aggregator (no bank instruction).
A supervisor then freezes it (confirm) or clears it (release). Offline evaluation runs
once without the policy (the detector baseline) and once with it (what it blocks).
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from infra import feedback as infra_feedback
from infra import integrations, rbac, sandbox, settings as infra_settings
from infra.graph import MemoryGraph, make_graph, summarize
from infra.ingest import Payment, PaymentBatch, Source, make_source

SCRIPT_DIR = Path(__file__).resolve().parent
LIVE_ROW_BASE = 1_000_000  # row ids for ingested payments, clear of the CSV's 0..N
MAX_BATCH = 2000  # payments scored and ingested per tick
MAX_INBOX = 50_000
RULE_VERSION = "r1.1"
TICK_SECONDS = 0.5
DEFAULT_SPEED = 4.0
LEAD_IN_SECONDS = 45

SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
DETECTORS = {
    "high_value_new_payee": "High-value inflow from new payers",
    "pass_through": "Rapid pass-through",
    "hop_from_flagged": "Funds from a flagged account",
    "model_only": "Model-only flag",
}


def _inr(n: float) -> str:
    s = f"{int(round(n))}"
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return f"₹{head},{tail}"


@dataclass
class Row:
    row: int
    t: float
    ts: str
    from_id: str
    from_vpa: str
    from_state: str
    to_id: str
    to_vpa: str
    to_state: str
    amount: float
    gnn: float
    is_fraud: int
    layer: str  # "live" for ingested payments
    blocked: bool = False
    source: str = "replay"  # replay | webhook | kafka | kinesis
    txn_id: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "ts": self.ts,
            "t": self.t,
            "fromId": self.from_id,
            "fromVpa": self.from_vpa,
            "fromState": self.from_state,
            "toId": self.to_id,
            "toVpa": self.to_vpa,
            "toState": self.to_state,
            "amount": self.amount,
            "gnn": round(self.gnn, 4),
            "blocked": self.blocked,
            "source": self.source,
            # Ingested payments have no label; is_fraud is -1 for them.
            "label": {"isFraud": bool(self.is_fraud), "layer": self.layer} if self.is_fraud >= 0 else None,
        }


@dataclass
class Alert:
    id: str
    detector: str
    account_id: str
    vpa: str
    state: str
    severity: str
    score: int
    gnn_max: float
    title: str
    reason: str
    facts: list[dict[str, str]]
    rows: list[int]
    first_evidence_t: float
    created_t: float
    updated_t: float
    truth_role: str
    status: str = "open"
    case_id: str | None = None
    lead_seconds: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "detector": self.detector,
            "detectorLabel": DETECTORS[self.detector],
            "ruleVersion": RULE_VERSION,
            "accountId": self.account_id,
            "vpa": self.vpa,
            "state": self.state,
            "severity": self.severity,
            "score": self.score,
            "gnnMax": round(self.gnn_max, 4),
            "title": self.title,
            "reason": self.reason,
            "facts": self.facts,
            "rows": self.rows,
            "firstEvidenceT": self.first_evidence_t,
            "createdT": self.created_t,
            "updatedT": self.updated_t,
            "status": self.status,
            "caseId": self.case_id,
            "leadSeconds": self.lead_seconds,
            "truth": {"role": self.truth_role, "isMule": self.truth_role in ("l1_mule", "l2_mule")},
        }


@dataclass
class Case:
    id: str
    opened_t: float
    account_ids: list[str] = field(default_factory=list)
    alert_ids: list[str] = field(default_factory=list)
    report: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "openedT": self.opened_t, "accountIds": self.account_ids, "alertIds": self.alert_ids, "report": self.report}


class Dataset:
    """The replay source: every CSV row, time-sorted, with its checkpoint score."""

    def __init__(self, raw: pd.DataFrame, scores, labels: pd.DataFrame):
        ts = pd.to_datetime(raw["timestamp"])
        order = ts.sort_values(kind="stable").index
        score_list = scores.tolist()
        self.rows: list[Row] = []
        for i in order:
            r = raw.loc[i]
            self.rows.append(
                Row(
                    row=int(i),
                    t=ts[i].timestamp(),
                    ts=str(r["timestamp"]),
                    from_id=str(r["sender_id"]),
                    from_vpa=str(r["sender_vpa"]),
                    from_state=str(r["sender_state"]),
                    to_id=str(r["recv_id"]),
                    to_vpa=str(r["recv_vpa"]),
                    to_state=str(r["recv_state"]),
                    amount=float(r["amount_inr"]),
                    gnn=float(score_list[i]),
                    is_fraud=int(r["is_fraud"]),
                    layer=str(r["layer"]),
                )
            )
        self.role = dict(zip(labels["account_id"].astype(str), labels["role"].astype(str)))
        self.bank = dict(zip(labels["account_id"].astype(str), labels["bank"].astype(str)))
        self.vpa_to_id: dict[str, str] = {}
        for r in self.rows:
            self.vpa_to_id.setdefault(r.from_vpa, r.from_id)
            self.vpa_to_id.setdefault(r.to_vpa, r.to_id)
        self.start_t = self.rows[0].t
        self.end_t = self.rows[-1].t
        self.fraud_window = (
            min(r.ts for r in self.rows if r.is_fraud),
            max(r.ts for r in self.rows if r.is_fraud),
        )
        self.accounts = len(set(self.role) | set(self.vpa_to_id.values()))


class RailEngine:
    def __init__(self, data: Dataset, speed: float = DEFAULT_SPEED, record_actions: bool = True, store=None, source: str = "replay", auto_hold: bool = False):
        self.data = data
        self.auto_hold = auto_hold
        self.record_actions = record_actions
        self.speed = speed
        self.store = store  # infra.store.Store, or None (offline evaluation)
        self.source = source  # "replay", or the live backend when the CSV replay is off
        self.live = source != "replay"
        if record_actions:
            self.graph, self.graph_error = make_graph(lambda: (self.inbound, self.outbound))
        else:
            self.graph, self.graph_error = MemoryGraph(lambda: (self.inbound, self.outbound)), None
        self.reset()

    # ------------------------------------------------------------------ lifecycle

    def reset(self) -> None:
        self.run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.cursor = 0
        self.sim_t = time.time() if self.live else self.data.start_t - LEAD_IN_SECONDS
        self.replayed: list[Row] = []
        self.inbound: dict[str, list[Row]] = defaultdict(list)
        self.outbound: dict[str, list[Row]] = defaultdict(list)
        self.payees: dict[str, set[str]] = defaultdict(set)
        self.alerts: dict[str, Alert] = {}
        self.alerts_by_account: dict[str, list[Alert]] = defaultdict(list)
        self.alert_by_key: dict[str, str] = {}
        self.frozen: dict[str, dict[str, Any]] = {}
        self.held: dict[str, dict[str, Any]] = {}  # auto-hold: blocks like a freeze, pending review
        self.cases: dict[str, Case] = {}
        self.audit: list[dict[str, Any]] = []
        self.blocked_fraud = 0.0
        self.blocked_genuine = 0.0
        self.blocked_unlabelled = 0.0
        self.tick_counts: list[int] = []
        self.batch: list[Row] = []
        self.events: list[dict[str, Any]] = []
        self.started_real = time.time()
        self.seen_txn: set[str] = set()
        self.live_vpa_to_id: dict[str, str] = {}
        self.live_count = 0
        self.duplicates = 0
        # A live graph keeps its history across restarts; a replay restarts from zero, so its graph does too.
        if not self.live:
            try:
                self.graph.reset()
            except Exception as error:
                self.graph_error = f"reset failed: {error}"[:300]
        if self.store:
            self.store.start_run(self.run_id, self.source, RULE_VERSION, {"graph": self.graph.backend, "speed": self.speed})

    @property
    def done(self) -> bool:
        return not self.live and self.cursor >= len(self.data.rows)

    def advance(self, seconds: float) -> None:
        """Move the replay clock forward and process every row that falls due."""
        target = self.sim_t + seconds
        self.batch = []
        rows = self.data.rows
        while self.cursor < len(rows) and rows[self.cursor].t <= target:
            # Alerts are stamped with the time of the row that raised them, not the tick end.
            self.sim_t = max(self.sim_t, rows[self.cursor].t)
            self._ingest(rows[self.cursor])
            self.cursor += 1
        self.sim_t = target
        self.tick_counts.append(len(self.batch))
        self.tick_counts = self.tick_counts[-120:]

    def run_to_end(self) -> None:
        while not self.done:
            self.advance(3600)

    def drain_events(self) -> list[dict[str, Any]]:
        events, self.events = self.events, []
        return events

    # ------------------------------------------------------------------ ingest

    def account_for(self, vpa: str) -> str | None:
        return self.data.vpa_to_id.get(vpa) or self.live_vpa_to_id.get(vpa)

    def ingest_live(self, payments: list[dict[str, Any]], scores: list[float | None], source: str) -> list[Row]:
        """Detect on ingested payments. Times come from the payment in live mode; during a
        replay they are stamped at the replay clock so they land in the running timeline."""
        self.batch = []
        rows: list[Row] = []
        for p, score in zip(payments, scores):
            if p["txn_id"] in self.seen_txn:
                self.duplicates += 1
                continue
            self.seen_txn.add(p["txn_id"])
            t = self.sim_t
            if self.live and p.get("timestamp"):
                t = pd.Timestamp(p["timestamp"]).timestamp()
            elif self.live:
                t = time.time()
            from_id = p.get("payer_account_id") or self.account_for(p["payer_vpa"]) or p["payer_vpa"]
            to_id = p.get("payee_account_id") or self.account_for(p["payee_vpa"]) or p["payee_vpa"]
            self.live_vpa_to_id.setdefault(p["payer_vpa"], from_id)
            self.live_vpa_to_id.setdefault(p["payee_vpa"], to_id)
            rows.append(
                Row(
                    row=LIVE_ROW_BASE + self.live_count,
                    t=t,
                    ts=datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),  # same naive-as-UTC convention as Dataset
                    from_id=from_id,
                    from_vpa=p["payer_vpa"],
                    from_state=p.get("payer_state") or "",
                    to_id=to_id,
                    to_vpa=p["payee_vpa"],
                    to_state=p.get("payee_state") or "",
                    amount=float(p["amount_inr"]),
                    gnn=float(score) if score is not None else 0.0,
                    is_fraud=-1,
                    layer="live",
                    source=source,
                    txn_id=p["txn_id"],
                )
            )
            self.live_count += 1
        rows.sort(key=lambda r: r.t)
        if rows and self.live and not self.replayed:
            self.sim_t = rows[0].t  # the event-time clock starts at the first payment
        for r in rows:
            self.sim_t = max(self.sim_t, r.t)
            self._ingest(r)
            if self.live:  # in replay mode the cursor indexes the CSV rows, not ingested ones
                self.cursor += 1
        return rows

    def _ingest(self, template: Row) -> None:
        r = Row(**{**template.__dict__})
        if self._stopped(r.from_id) or self._stopped(r.to_id):
            r.blocked = True
            if r.is_fraud == 1:
                self.blocked_fraud += r.amount
            elif r.is_fraud == 0:
                self.blocked_genuine += r.amount
            else:
                self.blocked_unlabelled += r.amount
            self.replayed.append(r)
            self.batch.append(r)
            self.graph.add(r)
            return
        self.replayed.append(r)
        self.batch.append(r)
        self.graph.add(r)
        new_payee = r.to_id not in self.payees[r.from_id]
        self.payees[r.from_id].add(r.to_id)
        self.inbound[r.to_id].append(r)
        self.outbound[r.from_id].append(r)

        for a in self._alerts_on(r.from_id):
            if a.lead_seconds is None and a.detector == "high_value_new_payee":
                a.lead_seconds = r.t - a.created_t

        self._check_high_value(r, new_payee)
        self._check_pass_through(r)
        self._check_hop_from_flagged(r)
        self._check_model_only(r)

    def _alerts_on(self, account_id: str) -> list[Alert]:
        return list(self.alerts_by_account.get(account_id, ()))

    def _stopped(self, account_id: str) -> bool:
        """Frozen or held: its transfers are blocked."""
        return account_id in self.frozen or account_id in self.held

    def _flagged(self, account_id: str) -> bool:
        return self._stopped(account_id) or any(a.status != "cleared" for a in self._alerts_on(account_id))

    # ------------------------------------------------------------------ detectors

    def _check_high_value(self, r: Row, new_payee: bool) -> None:
        """₹4.5L+ from a payer who has never paid this account, from another state."""
        if r.amount < 450_000 or not new_payee or r.from_state == r.to_state:
            return
        hits = [x for x in self.inbound[r.to_id] if x.amount >= 450_000 and x.from_state != x.to_state]
        payers = {x.from_id for x in hits}
        total = sum(x.amount for x in hits)
        self._upsert(
            "high_value_new_payee",
            r.to_id,
            severity="critical" if len(payers) >= 2 else "high",
            base=80 + 5 * len(payers),
            title="High-value transfers from new out-of-state payers",
            reason=(
                f"{len(payers)} payer{'s' if len(payers) > 1 else ''} from another state sent {_inr(total)} in transfers of ₹4.5 lakh or more, "
                "each to a payee they had never paid before. Victims of investment and digital-arrest scams move money this way."
            ),
            facts=[
                {"label": "Payers", "value": str(len(payers))},
                {"label": "Total received", "value": _inr(total)},
                {"label": "Largest transfer", "value": _inr(max(x.amount for x in hits))},
                {"label": "Payer states", "value": ", ".join(sorted({x.from_state for x in hits}))},
                {"label": "Account state", "value": r.to_state},
            ],
            rows=hits,
        )

    def _check_pass_through(self, r: Row) -> None:
        """Within 60 minutes, ₹2L+ came in and 60%+ of it left in 2 or more transfers."""
        acct = r.from_id
        since = r.t - 3600
        ins = [x for x in self.inbound[acct] if x.t >= since]
        outs = [x for x in self.outbound[acct] if x.t >= since]
        inflow = sum(x.amount for x in ins)
        outflow = sum(x.amount for x in outs)
        if inflow < 200_000 or len(outs) < 2 or outflow < 0.6 * inflow:
            return
        ratio = outflow / inflow
        first_in = min(x.t for x in ins)
        turnaround = min(x.t for x in outs if x.t >= first_in) - first_in if any(x.t >= first_in for x in outs) else 0
        self._upsert(
            "pass_through",
            acct,
            severity="critical" if ratio >= 0.9 else "high",
            base=70 + int(ratio * 20),
            title="Money forwarded within the hour",
            reason=(
                f"Received {_inr(inflow)} and sent {_inr(outflow)} ({round(ratio * 100)}%) onward to {len({x.to_id for x in outs})} accounts "
                f"within 60 minutes. The first onward transfer left {round(turnaround / 60, 1)} minutes after the first inflow."
            ),
            facts=[
                {"label": "In, last 60 min", "value": _inr(inflow)},
                {"label": "Out, last 60 min", "value": _inr(outflow)},
                {"label": "Out / in", "value": f"{round(ratio * 100)}%"},
                {"label": "Onward recipients", "value": str(len({x.to_id for x in outs}))},
                {"label": "First in → first out", "value": f"{round(turnaround / 60, 1)} min"},
            ],
            rows=sorted(ins + outs, key=lambda x: x.t),
        )

    def _is_hop_source(self, account_id: str, t: float) -> bool:
        """Frozen or held, or flagged by a primary rule in the last 24h. Hop alerts don't propagate further."""
        if self._stopped(account_id):
            return True
        return any(
            a.detector in ("high_value_new_payee", "pass_through") and a.status != "cleared" and a.created_t >= t - 86400
            for a in self._alerts_on(account_id)
        )

    def _check_hop_from_flagged(self, r: Row) -> None:
        """Receives money from an account that a primary rule flagged in the last 24 hours."""
        if self._stopped(r.to_id) or not self._is_hop_source(r.from_id, r.t):
            return
        hits = [x for x in self.inbound[r.to_id] if self._is_hop_source(x.from_id, x.t)]
        senders = {x.from_id for x in hits}
        total = sum(x.amount for x in hits)
        self._upsert(
            "hop_from_flagged",
            r.to_id,
            severity="high" if total >= 100_000 else "medium",
            base=62 + 4 * len(senders),
            title="Received funds from a flagged account",
            reason=(
                f"Received {_inr(total)} from {len(senders)} account{'s' if len(senders) > 1 else ''} already under alert. "
                "This is the next hop in the chain: the place the money goes after the first mule."
            ),
            facts=[
                {"label": "Flagged senders", "value": ", ".join(sorted({x.from_vpa for x in hits}))},
                {"label": "Received from them", "value": _inr(total)},
                {"label": "Transfers", "value": str(len(hits))},
                {"label": "Account state", "value": r.to_state},
            ],
            rows=hits,
        )

    def _check_model_only(self, r: Row) -> None:
        """The checkpoint scores the edge 0.9+ but no rule has fired on the receiver."""
        if r.gnn < 0.9 or any(a.detector != "model_only" for a in self._alerts_on(r.to_id)):
            return
        hits = [x for x in self.inbound[r.to_id] if x.gnn >= 0.9]
        self._upsert(
            "model_only",
            r.to_id,
            severity="medium",
            base=45,
            title="Model flags this account's inflow",
            reason=(
                f"The GIN checkpoint scores {len(hits)} inbound transfer{'s' if len(hits) > 1 else ''} at 0.9 or higher, "
                "but no rule has fired. Treat as a lead to check, not a finding."
            ),
            facts=[
                {"label": "Highest model score", "value": f"{max(x.gnn for x in hits):.3f}"},
                {"label": "Transfers scored 0.9+", "value": str(len(hits))},
                {"label": "Their value", "value": _inr(sum(x.amount for x in hits))},
            ],
            rows=hits,
        )

    def _upsert(self, detector: str, account_id: str, *, severity: str, base: int, title: str, reason: str, facts: list, rows: list[Row]) -> None:
        key = f"{detector}|{account_id}"
        gnn_max = max((x.gnn for x in rows), default=0.0)
        score = min(99, base + round(10 * gnn_max))
        existing = self.alerts.get(self.alert_by_key.get(key, ""))
        if existing:
            if existing.status == "cleared":
                return
            existing.severity = severity if SEV_RANK[severity] > SEV_RANK[existing.severity] else existing.severity
            existing.score = max(existing.score, score)
            existing.gnn_max = max(existing.gnn_max, gnn_max)
            existing.reason, existing.facts, existing.title = reason, facts, title
            existing.rows = sorted({*existing.rows, *(x.row for x in rows)}, key=lambda i: i)
            existing.first_evidence_t = min(existing.first_evidence_t, min(x.t for x in rows))
            existing.updated_t = self.sim_t
            self._maybe_hold(existing)
            self.events.append({"type": "alert", "alert": existing.public()})
            return
        if self._stopped(account_id):
            return
        # A model-only lead is superseded once a rule fires on the same account.
        if detector != "model_only":
            for a in self._alerts_on(account_id):
                if a.detector == "model_only" and a.status == "open":
                    a.status = "superseded"
                    self.events.append({"type": "alert", "alert": a.public()})
        alert = Alert(
            id=f"ALR-{len(self.alerts) + 1:04d}",
            detector=detector,
            account_id=account_id,
            vpa=self._vpa(account_id),
            state=rows[-1].to_state if rows[-1].to_id == account_id else rows[-1].from_state,
            severity=severity,
            score=score,
            gnn_max=gnn_max,
            title=title,
            reason=reason,
            facts=facts,
            rows=[x.row for x in rows],
            first_evidence_t=min(x.t for x in rows),
            created_t=self.sim_t,
            updated_t=self.sim_t,
            truth_role=self.data.role.get(account_id, "unknown"),
        )
        self.alerts[alert.id] = alert
        self.alerts_by_account[account_id].append(alert)
        self.alert_by_key[key] = alert.id
        self.graph.mark(account_id, flagged=True)
        self._maybe_hold(alert)
        self.events.append({"type": "alert", "alert": alert.public()})

    def _maybe_hold(self, alert: Alert) -> None:
        """The automatic intervention: hold the account on a critical, model-corroborated alert."""
        if not self.auto_hold or alert.severity != "critical" or alert.gnn_max < rbac.OVERRIDE_SCORE:
            return
        if alert.status not in ("open", "escalated") or self._stopped(alert.account_id):
            return
        alert.status = "held"
        alert.case_id = self._attach_to_case(alert).id
        self.held[alert.account_id] = {"at": self.sim_t, "by": "system", "alertId": alert.id, "policy": f"critical + model >= {rbac.OVERRIDE_SCORE}"}
        self.graph.mark(alert.account_id, frozen=True)
        self._log(
            "auto_hold", "system",
            f"Held {alert.vpa}: {DETECTORS[alert.detector].lower()} (critical) and model score {alert.gnn_max:.3f}. Transfers blocked pending review.",
            role="system", alert_id=alert.id, account_id=alert.account_id, case_id=alert.case_id,
        )
        self.events.append({"type": "held", "accountId": alert.account_id, "vpa": alert.vpa, "alertId": alert.id})

    def _vpa(self, account_id: str) -> str:
        rows = self.inbound.get(account_id) or self.outbound.get(account_id)
        if rows:
            r = rows[0]
            return r.to_vpa if r.to_id == account_id else r.from_vpa
        return account_id

    # ------------------------------------------------------------------ actions

    def is_override(self, alert: Alert, action: str) -> bool:
        """Clearing something the model scored >= 0.9, or releasing an automatic hold."""
        return action == "clear" and (alert.status == "held" or alert.gnn_max >= rbac.OVERRIDE_SCORE)

    def act(self, alert_id: str, action: str, note: str, actor: str, role: str = "analyst") -> dict[str, Any]:
        alert = self.alerts.get(alert_id)
        if not alert:
            return {"error": "Alert not found", "status": 404}
        if not note.strip():
            return {"error": "A note is required for every action", "status": 422}
        if alert.status in ("frozen", "cleared", "superseded"):
            return {"error": f"Alert is already {alert.status}", "status": 409}
        override = self.is_override(alert, action)
        was_held = alert.status == "held"
        tool_result = None
        if action == "clear":
            alert.status = "cleared"
            if was_held and not any(a.status == "held" for a in self._alerts_on(alert.account_id)):
                self.held.pop(alert.account_id, None)
                self.events.append({"type": "released", "accountId": alert.account_id, "vpa": alert.vpa})
            if not any(a.status not in ("cleared", "superseded") for a in self._alerts_on(alert.account_id)):
                self.graph.mark(alert.account_id, flagged=False, frozen=False)
        elif action == "escalate":
            if not was_held:  # a held alert keeps its hold; escalating just files it to a case
                alert.status = "escalated"
            alert.case_id = self._attach_to_case(alert).id
        elif action == "freeze":
            alert.status = "frozen"
            alert.case_id = self._attach_to_case(alert).id
            self.held.pop(alert.account_id, None)
            tool_result = self._freeze(alert.account_id, alert.vpa, f"{alert.id}: {note.strip()}", actor)
            for other in self._alerts_on(alert.account_id):
                if other.id != alert.id and other.status in ("open", "escalated", "held"):
                    other.status = "frozen"
                    other.case_id = alert.case_id
                    self._attach_to_case(other)
                    self.events.append({"type": "alert", "alert": other.public()})
        else:
            return {"error": f"Unknown action {action}", "status": 400}
        alert.updated_t = self.sim_t
        if self.store:
            self.store.record_decision(self.run_id, alert.public(), action, actor, note.strip(), self.sim_t)
        logged = "release_hold" if action == "clear" and was_held else action
        self._log(logged, actor, note.strip(), role=role, override=override or None, alert_id=alert.id, account_id=alert.account_id, tool=tool_result)
        self.events.append({"type": "alert", "alert": alert.public()})
        return {"alert": alert.public(), "tool": tool_result, "override": override}

    def _freeze(self, account_id: str, vpa: str, reason: str, actor: str) -> dict[str, Any]:
        result: dict[str, Any] = {"tool": "agents.tools_impl.freeze_account", "simulated": True}
        if self.record_actions:
            try:
                from agents.tools_impl import freeze_account

                result = {"tool": "agents.tools_impl.freeze_account", **freeze_account(vpa, reason)}
            except Exception as error:  # the console must keep working if the agent package breaks
                result["error"] = str(error)
        self.frozen[account_id] = {"at": self.sim_t, "by": actor, "reference": result.get("freeze_reference"), "gateway": result.get("gateway")}
        self.graph.mark(account_id, frozen=True)
        self.events.append({"type": "frozen", "accountId": account_id, "vpa": vpa, "reference": result.get("freeze_reference")})
        return result

    def file_report(self, case_id: str, actor: str, role: str = "supervisor") -> dict[str, Any]:
        case = self.cases.get(case_id)
        if not case:
            return {"error": "Case not found", "status": 404}
        pack = self.evidence_pack(case_id)
        vpas = [a["vpa"] for a in pack["accounts"]]
        summary = (
            f"{case.id}: {len(case.alert_ids)} alerts across {len(vpas)} accounts. "
            f"Frozen: {sum(1 for a in pack['accounts'] if a['frozen'])}. Rule version {RULE_VERSION}."
        )
        result: dict[str, Any] = {"tool": "agents.tools_impl.file_1930_report", "simulated": True}
        try:
            from agents.tools_impl import file_1930_report

            result = {"tool": "agents.tools_impl.file_1930_report", **file_1930_report(vpas, summary, pack["summary"]["moneyIn"])}
        except Exception as error:
            result["error"] = str(error)
        case.report = result
        self._log("file_1930_report", actor, summary, role=role, case_id=case.id, tool=result)
        return {"case": case.public(), "tool": result}

    def notify(self, case_id: str, actor: str, role: str = "supervisor") -> dict[str, Any]:
        case = self.cases.get(case_id)
        if not case:
            return {"error": "Case not found", "status": 404}
        message = f"{case.id}: {len(case.alert_ids)} alerts, {len(case.account_ids)} accounts. Review in the risk console."
        result: dict[str, Any] = {"tool": "agents.tools_impl.notify_officer"}
        try:
            from agents.tools_impl import notify_officer

            result = {"tool": "agents.tools_impl.notify_officer", **notify_officer(message, "high")}
        except Exception as error:
            result["error"] = str(error)
        self._log("notify_officer", actor, message, role=role, case_id=case.id, tool=result)
        return {"tool": result}

    def _attach_to_case(self, alert: Alert) -> Case:
        neighbours = {alert.account_id}
        neighbours |= {x.from_id for x in self.inbound.get(alert.account_id, [])}
        neighbours |= {x.to_id for x in self.outbound.get(alert.account_id, [])}
        case = next((c for c in self.cases.values() if neighbours & set(c.account_ids)), None)
        if not case:
            case = Case(id=f"CASE-{len(self.cases) + 1:03d}", opened_t=self.sim_t)
            self.cases[case.id] = case
            self._log("case_opened", "system", f"Opened from {alert.id}", role="system", case_id=case.id, account_id=alert.account_id)
        if alert.account_id not in case.account_ids:
            case.account_ids.append(alert.account_id)
        if alert.id not in case.alert_ids:
            case.alert_ids.append(alert.id)
        return case

    def _log(self, action: str, actor: str, note: str, **extra: Any) -> None:
        entry = {"id": f"AUD-{len(self.audit) + 1:05d}", "at": time.time(), "simT": self.sim_t, "action": action, "actor": actor, "note": note}
        camel = {"alert_id": "alertId", "account_id": "accountId", "case_id": "caseId"}
        entry.update({camel.get(k, k): v for k, v in extra.items() if v is not None})
        self.audit.append(entry)
        if self.store:
            self.store.record_audit(self.run_id, entry)
        self.events.append({"type": "audit", "entry": entry})

    # ------------------------------------------------------------------ reads

    def metrics(self) -> dict[str, Any]:
        alerts = [a for a in self.alerts.values() if a.status != "superseded"]
        open_ = [a for a in alerts if a.status == "open"]
        by_sev = {k: sum(1 for a in open_ if a.severity == k) for k in SEV_RANK}
        tta = [a.created_t - a.first_evidence_t for a in alerts]
        leads = [a.lead_seconds for a in alerts if a.lead_seconds is not None]
        # Accounts outside the labelled dataset (new live payers) have no truth; leave them out.
        rule_alerts = [a for a in alerts if a.detector != "model_only" and a.truth_role != "unknown"]
        mules_seen = {
            acct
            for r in self.replayed
            if not r.blocked
            for acct in (r.from_id, r.to_id)
            if self.data.role.get(acct) in ("l1_mule", "l2_mule")
        }
        mules_alerted = {a.account_id for a in rule_alerts if a.truth_role in ("l1_mule", "l2_mule")}
        last_minute = sum(1 for r in self.replayed[-400:] if r.t > self.sim_t - 60)
        return {
            "simT": self.sim_t,
            "source": self.source,
            "runId": self.run_id,
            "rowsReplayed": self.cursor,
            "rowsTotal": None if self.live else len(self.data.rows),
            "ingested": self.live_count,
            "duplicatesDropped": self.duplicates,
            "speed": self.speed,
            "done": self.done,
            "txnsLastMinute": last_minute,
            "volumeReplayed": sum(r.amount for r in self.replayed if not r.blocked),
            "openAlerts": len(open_),
            "openBySeverity": by_sev,
            "medianTimeToAlertSec": statistics.median(tta) if tta else None,
            "medianLeadSec": statistics.median(leads) if leads else None,
            "precision": (sum(1 for a in rule_alerts if a.truth_role in ("l1_mule", "l2_mule")) / len(rule_alerts)) if rule_alerts else None,
            "muleRecall": (len(mules_alerted) / len(mules_seen)) if mules_seen else None,
            "mulesSeen": len(mules_seen),
            "mulesAlerted": len(mules_alerted),
            "frozenAccounts": len(self.frozen),
            "heldAccounts": len(self.held),
            "autoHold": self.auto_hold,
            "blockedFraudAmount": self.blocked_fraud,
            "blockedGenuineAmount": self.blocked_genuine,
            "blockedUnlabelledAmount": self.blocked_unlabelled,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics(),
            "alerts": [a.public() for a in self._sorted_alerts()],
            "rows": [r.public() for r in self.replayed[-60:]][::-1],
            "audit": self.audit[-80:][::-1],
            "cases": [c.public() for c in self.cases.values()],
            "frozen": [{"accountId": k, **v} for k, v in self.frozen.items()],
            "held": [{"accountId": k, **v} for k, v in self.held.items()],
            "tickCounts": self.tick_counts[-60:],
            "dataset": dataset_facts(self.data),
        }

    def _sorted_alerts(self) -> list[Alert]:
        return sorted(self.alerts.values(), key=lambda a: (-SEV_RANK[a.severity], -a.score, -a.updated_t))

    def _row_index(self) -> dict[int, Row]:
        return {r.row: r for r in self.replayed}

    def alert_detail(self, alert_id: str) -> dict[str, Any] | None:
        alert = self.alerts.get(alert_id)
        if not alert:
            return None
        index = self._row_index()
        acct = alert.account_id
        return {
            "alert": alert.public(),
            "profile": self.profile(acct),
            "trail": self.trail(acct),
            "evidence": [index[i].public() for i in alert.rows[-20:][::-1] if i in index],
            "otherAlerts": [a.public() for a in self._alerts_on(acct) if a.id != alert.id],
            "audit": [e for e in self.audit if e.get("alertId") == alert.id or e.get("accountId") == acct][::-1],
            "history": self.account_history(acct),
        }

    def account_history(self, acct: str) -> list[dict[str, Any]]:
        """Analyst decisions on this account in earlier runs, from the durable store."""
        if not self.store:
            return []
        try:
            return [
                {"runId": d["run_id"], "alertId": d["alert_id"], "detector": d["detector"], "decision": d["decision"], "actor": d["actor"], "note": d["note"], "at": d["at"]}
                for d in self.store.account_history(acct, exclude_run=self.run_id)
            ]
        except Exception:
            return []

    def downstream(self, acct: str, hops: int = 3, limit: int = 200) -> dict[str, Any]:
        """Time-respecting paths the money took out of this account, from the graph store."""
        paths = self.graph.downstream_paths(acct, hops, limit)
        for p in paths:
            for n in p["nodes"]:
                n["flagged"] = self._flagged(n["id"])
                n["frozen"] = self._stopped(n["id"])
                n["truthRole"] = self.data.role.get(n["id"], "unknown")
        leaves = [p for p in paths if len(p["legs"]) == max((len(q["legs"]) for q in paths), default=0)]
        return {
            "accountId": acct,
            "hops": hops,
            "graph": self.graph.backend,
            "truncated": len(paths) >= limit,
            "paths": paths,
            "longest": leaves[:20],
            **summarize(paths, acct),
            "flaggedReached": len({n["id"] for p in paths for n in p["nodes"][1:] if n["flagged"]}),
        }

    def profile(self, acct: str) -> dict[str, Any]:
        ins = self.inbound.get(acct, [])
        outs = self.outbound.get(acct, [])
        first_in = min((x.t for x in ins), default=None)
        first_out = min((x.t for x in outs), default=None)
        return {
            "accountId": acct,
            "vpa": self._vpa(acct),
            "bank": self.data.bank.get(acct),
            "state": (ins[0].to_state if ins else outs[0].from_state if outs else None),
            "inboundCount": len(ins),
            "outboundCount": len(outs),
            "totalIn": sum(x.amount for x in ins),
            "totalOut": sum(x.amount for x in outs),
            "distinctPayers": len({x.from_id for x in ins}),
            "distinctPayees": len({x.to_id for x in outs}),
            "firstInT": first_in,
            "firstOutT": first_out,
            "frozen": self.frozen.get(acct),
            "held": self.held.get(acct),
            "truthRole": self.data.role.get(acct, "unknown"),
            "note": "Computed from replayed rows only. truthRole is the dataset label; detectors never read it.",
        }

    def trail(self, acct: str) -> dict[str, Any]:
        def group(rows: list[Row], key: Callable[[Row], str], label: Callable[[Row], str], top: int) -> list[dict[str, Any]]:
            groups: dict[str, dict[str, Any]] = {}
            for x in rows:
                k = key(x)
                g = groups.setdefault(k, {"id": k, "label": label(x), "amount": 0.0, "count": 0, "gnnMax": 0.0})
                g["amount"] += x.amount
                g["count"] += 1
                g["gnnMax"] = max(g["gnnMax"], x.gnn)
            ordered = sorted(groups.values(), key=lambda g: -g["amount"])
            if len(ordered) > top:
                rest = ordered[top - 1 :]
                ordered = ordered[: top - 1] + [
                    {"id": "others", "label": f"{len(rest)} others", "amount": sum(g["amount"] for g in rest), "count": sum(g["count"] for g in rest), "gnnMax": max(g["gnnMax"] for g in rest)}
                ]
            for g in ordered:
                g["flagged"] = g["id"] != "others" and self._flagged(g["id"])
                g["frozen"] = self._stopped(g["id"])
            return ordered

        ins = self.inbound.get(acct, [])
        outs = self.outbound.get(acct, [])
        destinations = group(outs, lambda x: x.to_id, lambda x: x.to_vpa, 5)
        for d in destinations:
            onward = self.outbound.get(d["id"], []) if d["id"] != "others" else []
            d["next"] = group(onward, lambda x: x.to_id, lambda x: x.to_vpa, 3)
        return {
            "sources": group(ins, lambda x: x.from_id, lambda x: x.from_vpa, 6),
            "destinations": destinations,
            "totalIn": sum(x.amount for x in ins),
            "totalOut": sum(x.amount for x in outs),
        }

    def chain_legs(self, alert_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """The alert account's inflows and outflows so far, as agent-tool legs."""
        alert = self.alerts[alert_id]
        rows = sorted(self.inbound.get(alert.account_id, []) + self.outbound.get(alert.account_id, []), key=lambda x: x.t)[:limit]
        return [{"sender": x.from_vpa, "receiver": x.to_vpa, "amount_inr": x.amount, "timestamp": x.ts, "row": x.row, "gnnPrecomputed": x.gnn} for x in rows]

    def evidence_pack(self, case_id: str) -> dict[str, Any] | None:
        case = self.cases.get(case_id)
        if not case:
            return None
        ids = set(case.account_ids)
        rows = [r for r in self.replayed if r.from_id in ids or r.to_id in ids]
        alerts = [self.alerts[i] for i in case.alert_ids]
        links = [
            {"fromVpa": r.from_vpa, "toVpa": r.to_vpa, "amount": r.amount, "ts": r.ts, "row": r.row}
            for r in rows
            if r.from_id in ids and r.to_id in ids
        ]
        timeline = sorted(
            [{"simT": a.created_t, "kind": "alert", "text": f"{a.id} {DETECTORS[a.detector]} on {a.vpa} ({a.severity})"} for a in alerts]
            + [
                {"simT": e["simT"], "kind": "action", "text": f"{e['actor']}: {e['action'].replace('_', ' ')}. {e['note']}"}
                for e in self.audit
                if e.get("caseId") == case_id or e.get("accountId") in ids
            ],
            key=lambda x: x["simT"],
        )
        money_in = sum(r.amount for r in rows if r.to_id in ids and r.from_id not in ids and not r.blocked)
        exited = sum(r.amount for r in rows if r.from_id in ids and r.to_id not in ids and not r.blocked)
        return {
            "caseId": case.id,
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "simT": self.sim_t,
            "source": {
                "dataset": "Multi-GNN/nolambur_transactions.csv (synthetic)",
                "model": "Multi-GNN/models/local_finetuned_gin_nolambur.pt",
                "ruleVersion": RULE_VERSION,
                "actionLog": "Multi-GNN/agents/action_log.jsonl",
            },
            "summary": {
                "accounts": len(ids),
                "alerts": len(alerts),
                "transactions": len(rows),
                "moneyIn": money_in,
                "exited": exited,
                "blocked": sum(r.amount for r in rows if r.blocked),
            },
            "accounts": [{**self.profile(a), "frozen": a in self.frozen, "freeze": self.frozen.get(a), "held": self.held.get(a)} for a in case.account_ids],
            "alerts": [a.public() for a in alerts],
            "links": links,
            "timeline": timeline,
            "transactions": [r.public() for r in rows],
            "report": case.report,
        }

    def onboarding_check(self, vpas: list[str]) -> dict[str, Any]:
        """For a merchant applicant's settlement VPAs: who have they transacted with, and are any flagged?"""
        results = []
        for vpa in vpas:
            acct = self.account_for(vpa.strip())
            if not acct:
                results.append({"vpa": vpa, "known": False, "direct": [], "secondHop": [], "gnnMax": 0.0, "txns": 0})
                continue
            rows = self.inbound.get(acct, []) + self.outbound.get(acct, [])
            direct_ids = self.graph.counterparties(acct)  # graph store: memory or Neo4j
            direct = [self._party(d, acct) for d in direct_ids if self._flagged(d)]
            second: dict[str, dict[str, Any]] = {}
            for d in direct_ids:
                for other in self.graph.counterparties(d):
                    if other != acct and other not in direct_ids and self._flagged(other):
                        second[other] = {**self._party(other, d), "via": self._vpa(d)}
            results.append(
                {
                    "vpa": vpa,
                    "known": True,
                    "txns": len(rows),
                    "counterparties": len(direct_ids),
                    "selfFlagged": self._flagged(acct),
                    "direct": direct,
                    "secondHop": list(second.values()),
                    "gnnMax": max((x.gnn for x in rows), default=0.0),
                }
            )
        strong = [r for r in results if r.get("selfFlagged") or r.get("direct") or r.get("gnnMax", 0) >= 0.9]
        weak = [r for r in results if r.get("secondHop")]
        if strong:
            r = strong[0]
            why = (
                f"{r['vpa']} is itself under alert." if r.get("selfFlagged")
                else f"{r['vpa']} transacted directly with {len(r['direct'])} flagged account(s)." if r.get("direct")
                else f"The model scores one of {r['vpa']}'s transfers at {r['gnnMax']:.2f}."
            )
            decision = "hold"
        elif weak:
            decision, why = "approve", f"Only second-hop links ({len(weak[0]['secondHop'])}) to flagged accounts. Approve and monitor."
        else:
            decision, why = "approve", "No direct or second-hop links to flagged accounts in the replayed history."
        return {"decision": decision, "reason": why, "results": results, "checkedAgainstRows": len(self.replayed), "graph": self.graph.backend}

    def _party(self, acct: str, relative_to: str) -> dict[str, Any]:
        return {
            "accountId": acct,
            "vpa": self._vpa(acct),
            "frozen": self._stopped(acct),
            "alerts": [a.id for a in self._alerts_on(acct) if a.status != "cleared"],
        }

    def onboarding_presets(self) -> list[dict[str, Any]]:
        """Sample applicants picked from the real data, once the fraud hour has replayed."""
        role = self.data.role
        presets = []
        l2 = next((a for a in self.alerts.values() if a.truth_role == "l2_mule"), None)
        if l2:
            presets.append({"label": "Settlement VPA that received mule money", "vpas": [l2.vpa]})
        victims = {r.from_id for r in self.replayed if r.is_fraud and role.get(r.from_id) == "victim"}
        two_hop = next(
            (r.to_vpa for r in self.replayed if r.from_id in victims and role.get(r.to_id) == "clean"),
            None,
        )
        if two_hop:
            presets.append({"label": "Paid by a scam victim (second-hop only)", "vpas": [two_hop]})
        clean = next((r.to_vpa for r in self.replayed[-500:] if role.get(r.to_id) == "clean" and not self._flagged(r.to_id)), None)
        if clean:
            presets.append({"label": "Ordinary account", "vpas": [clean]})
        return presets


def dataset_facts(data: Dataset) -> dict[str, Any]:
    return {
        "file": "nolambur_transactions.csv",
        "rows": len(data.rows),
        "accounts": data.accounts,
        "fraudRows": sum(r.is_fraud for r in data.rows),
        "start": data.rows[0].ts,
        "end": data.rows[-1].ts,
        "fraudWindow": list(data.fraud_window),
    }


# ---------------------------------------------------------------------- evaluation


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def _training_log() -> dict[str, Any]:
    """The last finetune run in logs/logs.log: per-epoch F1 and the held-out test result."""
    path = SCRIPT_DIR / "logs" / "logs.log"
    if not path.exists():
        return {"epochs": [], "test": None}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    epoch_re = re.compile(r"\[FINETUNE\] Epoch\s+(\d+) \| Train F1: ([\d.]+) \| Val F1: ([\d.]+) \| Test F1: ([\d.]+)")
    test_re = re.compile(r"Test split \((\d+) edges, (\d+) actually fraud, (\d+) flagged\): F1=([\d.]+) Precision=([\d.]+) Recall=([\d.]+)")
    runs: list[list[dict[str, Any]]] = []
    test = None
    stamp = None
    for line in lines:
        m = epoch_re.search(line)
        if m:
            epoch = int(m.group(1))
            if epoch == 0 or not runs or epoch <= runs[-1][-1]["epoch"]:
                runs.append([])
            runs[-1].append({"epoch": epoch, "train": float(m.group(2)), "val": float(m.group(3)), "test": float(m.group(4))})
            stamp = line[:19]
        t = test_re.search(line)
        if t:
            test = {"edges": int(t.group(1)), "positives": int(t.group(2)), "flagged": int(t.group(3)), "f1": float(t.group(4)), "precision": float(t.group(5)), "recall": float(t.group(6)), "loggedAt": line[:19]}
    return {"epochs": runs[-1] if runs else [], "test": test, "lastEpochAt": stamp, "runsInLog": len(runs)}


def evaluate(data: Dataset) -> dict[str, Any]:
    rows = data.rows
    y = [r.is_fraud for r in rows]

    thresholds = []
    for th in (0.3, 0.5, 0.7, 0.9, 0.95):
        tp = sum(1 for r in rows if r.gnn >= th and r.is_fraud)
        fp = sum(1 for r in rows if r.gnn >= th and not r.is_fraud)
        fn = sum(y) - tp
        thresholds.append({"threshold": th, **_prf(tp, fp, fn)})

    per_layer = []
    for layer in sorted({r.layer for r in rows}):
        subset = [r for r in rows if r.layer == layer]
        amounts = [r.amount for r in subset]
        per_layer.append(
            {
                "layer": layer,
                "rows": len(subset),
                "flaggedAt0_9": sum(1 for r in subset if r.gnn >= 0.9),
                "amountMin": min(amounts),
                "amountMax": max(amounts),
                "amountMedian": statistics.median(amounts),
            }
        )

    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    hist = []
    for lo, hi in zip(bins, bins[1:]):
        hist.append(
            {
                "bin": f"{lo:.1f}–{min(hi, 1):.1f}",
                "fraud": sum(1 for r in rows if lo <= r.gnn < hi and r.is_fraud),
                "clean": sum(1 for r in rows if lo <= r.gnn < hi and not r.is_fraud),
            }
        )

    # Baseline: one amount threshold, no model at all.
    tp = sum(1 for r in rows if r.amount >= 450_000 and r.is_fraud)
    fp = sum(1 for r in rows if r.amount >= 450_000 and not r.is_fraud)
    amount_rule = {"name": "amount ≥ ₹4.5L", **_prf(tp, fp, sum(y) - tp)}

    # The console's detectors, replayed over the whole dataset with nobody acting.
    offline = RailEngine(data, record_actions=False)
    offline.run_to_end()
    all_mules = {a for a, role in data.role.items() if role in ("l1_mule", "l2_mule")}
    # Some labelled mules never appear in a single transaction; no detector can see them.
    mules = {a for a in all_mules if offline.inbound.get(a) or offline.outbound.get(a)}
    rule_accounts = {a.account_id for a in offline.alerts.values() if a.detector != "model_only"}
    model_accounts = {a.account_id for a in offline.alerts.values() if a.detector == "model_only"}
    by_detector = []
    for det in DETECTORS:
        accts = {a.account_id for a in offline.alerts.values() if a.detector == det}
        hits = len(accts & mules)
        by_detector.append({"detector": det, "label": DETECTORS[det], "alerts": len(accts), "mules": hits, "precision": hits / len(accts) if accts else None})
    detectors = {
        "accountLevel": _prf(len(rule_accounts & mules), len(rule_accounts - mules), len(mules - rule_accounts)),
        "modelOnlyAccounts": len(model_accounts),
        "modelOnlyMules": len(model_accounts & mules),
        "combined": _prf(len((rule_accounts | model_accounts) & mules), len((rule_accounts | model_accounts) - mules), len(mules - rule_accounts - model_accounts)),
        "mulesLabelled": len(all_mules),
        "mulesInTransactions": len(mules),
        "mulesSendOnly": len({a for a in mules if not offline.inbound.get(a)}),
        "medianLeadSec": offline.metrics()["medianLeadSec"],
        "byDetector": by_detector,
        "medianTimeToAlertSec": offline.metrics()["medianTimeToAlertSec"],
    }

    policy = RailEngine(data, record_actions=False, auto_hold=True)
    policy.run_to_end()
    mule_roles = ("l1_mule", "l2_mule")
    held_ids = {a.account_id for a in policy.alerts.values() if a.status == "held"}
    hold_delay = [h["at"] - policy.alerts[h["alertId"]].first_evidence_t for h in policy.held.values()]
    auto_hold = {
        "policy": f"critical alert and model score >= {rbac.OVERRIDE_SCORE}",
        "accountsHeld": len(held_ids),
        "mulesHeld": sum(1 for a in held_ids if data.role.get(a) in mule_roles),
        "fraudTotal": sum(r.amount for r in rows if r.is_fraud),
        "fraudBlocked": policy.blocked_fraud,
        "genuineBlocked": policy.blocked_genuine,
        "medianSecondsToHold": statistics.median(hold_delay) if hold_delay else None,
        "note": "Replay with nobody acting except the policy. Blocked = transfers to or from a held account after the hold.",
    }

    checkpoint = SCRIPT_DIR / "models" / "local_finetuned_gin_nolambur.pt"
    settings = json.loads((SCRIPT_DIR / "model_settings.json").read_text(encoding="utf-8"))["gin"]["params"]
    return {
        "dataset": dataset_facts(data),
        "model": {
            "architecture": "GINe (edge-feature GIN), 2 message-passing layers",
            "checkpoint": "models/local_finetuned_gin_nolambur.pt",
            "checkpointBytes": checkpoint.stat().st_size if checkpoint.exists() else None,
            "checkpointModified": datetime.fromtimestamp(checkpoint.stat().st_mtime).isoformat(timespec="minutes") if checkpoint.exists() else None,
            "hidden": round(settings["n_hidden"]),
            "layers": round(settings["n_gnn_layers"]),
            "lr": settings["lr"],
            "positiveClassWeight": settings["w_ce2"],
            "edgeFeatures": ["Timestamp", "Amount Received", "Received Currency", "Payment Format"],
            "training": "Finetune only, on Nolambur. No IBM AML pretrain (needs a GPU).",
        },
        "trainingLog": _training_log(),
        "inSample": {"thresholds": thresholds, "perLayer": per_layer, "histogram": hist},
        "amountRule": amount_rule,
        "detectors": detectors,
        "autoHold": auto_hold,
    }


# ---------------------------------------------------------------------- service


class RailService:
    """Owns the engine, drives the replay clock and fans events out to SSE clients."""

    def __init__(self, predict_chain: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None) -> None:
        self.engine: RailEngine | None = None
        self.evaluation: dict[str, Any] | None = None
        self.status = "starting"
        self.error: str | None = None
        self.paused = False
        self.subscribers: set[asyncio.Queue] = set()
        self.predict_chain = predict_chain
        self.mode = infra_settings.RAIL_SOURCE if infra_settings.RAIL_SOURCE in ("webhook", "kafka", "kinesis") else "replay"
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.source: Source = make_source()
        self.store = None
        self.store_error: str | None = None
        self.ingest_stats = {"webhookAccepted": 0, "rejected": 0, "scored": 0, "scoreErrors": 0, "lastScoreError": None, "lastBatch": 0, "lastScoreMs": None}
        self._flushing = False

    async def start(self, load: Callable[[], tuple[pd.DataFrame, Any]]) -> None:
        self.status = "warming"
        try:
            from infra.store import get_store

            self.store = await asyncio.to_thread(get_store)
            integrations.ensure_worker()  # also resumes deliveries left pending by a previous process
        except Exception as error:  # the console runs without persistence rather than not at all
            self.store_error = f"{type(error).__name__}: {error}"[:300]
        try:
            raw, scores = await asyncio.to_thread(load)
            labels = pd.read_csv(SCRIPT_DIR / "nolambur_labels.csv")
            data = await asyncio.to_thread(Dataset, raw, scores, labels)
            self.evaluation = await asyncio.to_thread(evaluate, data)
            self.engine = await asyncio.to_thread(
                lambda: RailEngine(data, DEFAULT_SPEED, True, self.store, self.mode, auto_hold=infra_settings.RAIL_AUTO_HOLD)
            )
            self.status = "ready"
        except Exception as error:
            self.status = "error"
            self.error = f"{type(error).__name__}: {error}"
            return
        loop = asyncio.get_running_loop()

        def push(payments: list[dict[str, Any]]) -> None:  # called from consumer threads too
            loop.call_soon_threadsafe(self.inbox.put_nowait, (self.source.backend, payments))

        if self.mode in ("kafka", "kinesis"):
            asyncio.create_task(self.source.start(push))
        else:
            await self.source.start(push)
        asyncio.create_task(self._loop())

    def _drain_inbox(self) -> list[tuple[str, dict[str, Any]]]:
        items: list[tuple[str, dict[str, Any]]] = []
        while len(items) < MAX_BATCH and not self.inbox.empty():
            source, payments = self.inbox.get_nowait()
            room = MAX_BATCH - len(items)
            items.extend((source, p) for p in payments[:room])
            if len(payments) > room:  # put the rest back at the front of the next tick
                self.inbox._queue.appendleft((source, payments[room:]))  # type: ignore[attr-defined]
        return items

    async def _score(self, payments: list[dict[str, Any]]) -> list[float | None]:
        """One /predict splice for the whole batch: each payment is an edge on the background graph."""
        if not self.predict_chain:
            return [None] * len(payments)
        legs = [
            {"sender": p["payer_account_id"] or p["payer_vpa"], "receiver": p["payee_account_id"] or p["payee_vpa"], "amount_inr": p["amount_inr"],
             "timestamp": pd.Timestamp(p["timestamp"]).strftime("%Y-%m-%dT%H:%M:%S") if p.get("timestamp") else ""}
            for p in payments
        ]
        started = time.perf_counter()
        try:
            scored = await asyncio.to_thread(self.predict_chain, legs)
            self.ingest_stats["scored"] += len(payments)
            self.ingest_stats["lastScoreMs"] = round((time.perf_counter() - started) * 1000, 1)
            return [float(leg["fraud_probability"]) for leg in scored["legs"]]
        except Exception as error:
            self.ingest_stats["scoreErrors"] += len(payments)
            self.ingest_stats["lastScoreError"] = f"{type(error).__name__}: {error}"[:300]
            return [None] * len(payments)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await self._tick()
            except Exception as error:  # one bad batch must not stop the clock
                self.ingest_stats["lastTickError"] = f"{type(error).__name__}: {error}"[:300]

    async def _tick(self) -> None:
        engine = self.engine
        if engine is None:
            return
        if not self.paused:
            ticked = False
            if not engine.live and not engine.done:
                engine.advance(TICK_SECONDS * engine.speed)
                ticked = True
            replay_rows = list(engine.batch) if ticked else []
            items = self._drain_inbox()
            live_rows: list[Row] = []
            if items:
                payments = [p for _, p in items]
                scores = await self._score(payments)
                by_source: dict[str, list[int]] = defaultdict(list)
                for i, (source, _) in enumerate(items):
                    by_source[source].append(i)
                for source, idx in by_source.items():
                    live_rows += engine.ingest_live([payments[i] for i in idx], [scores[i] for i in idx], source)
                self.ingest_stats["lastBatch"] = len(items)
            if ticked or engine.live or live_rows:
                rows = [r.public() for r in replay_rows + live_rows]
                if ticked:
                    engine.tick_counts[-1] += len(live_rows)
                else:
                    engine.tick_counts = (engine.tick_counts + [len(live_rows)])[-120:]
                self.publish({"type": "tick", "rows": rows, "metrics": engine.metrics()})
        for event in engine.drain_events():
            self.publish(event)
        if engine.graph.backend != "memory" and not self._flushing:
            asyncio.create_task(self._flush_graph(engine))

    async def _flush_graph(self, engine: RailEngine) -> None:
        self._flushing = True
        try:
            await asyncio.to_thread(engine.graph.flush)
        finally:
            self._flushing = False

    async def graph_call(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Memory-graph queries read the engine directly; Neo4j ones leave the event loop."""
        if self.engine and self.engine.graph.backend == "memory":
            return fn(*args)
        return await asyncio.to_thread(fn, *args)

    def platform(self) -> dict[str, Any]:
        eng = self.engine
        return {
            "ingest": {
                "mode": self.mode,
                "replay": {"enabled": self.mode == "replay", "file": "nolambur_transactions.csv"},
                "source": self.source.describe(),
                "webhook": {"endpoint": "POST /rail/ingest/payments", "signed": bool(infra_settings.RAIL_WEBHOOK_SECRET)},
                "inboxDepth": sum(len(p) for _, p in list(self.inbox._queue)),  # type: ignore[attr-defined]
                **self.ingest_stats,
                "ingestedThisRun": eng.live_count if eng else 0,
                "duplicatesDropped": eng.duplicates if eng else 0,
            },
            "graph": {**(eng.graph.describe() if eng else {}), "fallbackReason": eng.graph_error if eng else None},
            "store": {**(self.store.describe() if self.store else {"backend": None}), "error": self.store_error, **(self.store.counts() if self.store else {})},
            "integrations": integrations.describe() if self.store else {"error": self.store_error},
            "runId": eng.run_id if eng else None,
        }

    def publish(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, default=str)
        for queue in list(self.subscribers):
            if queue.qsize() < 500:
                queue.put_nowait(payload)

    def control(self, speed: float | None, restart: bool, paused: bool | None) -> dict[str, Any]:
        assert self.engine is not None
        if restart:
            self.engine.reset()
            self.publish({"type": "reset", "snapshot": self.engine.snapshot()})
        if speed is not None:
            self.engine.speed = max(0.5, min(speed, 600))
        if paused is not None:
            self.paused = paused
        return {"speed": self.engine.speed, "paused": self.paused, "metrics": self.engine.metrics()}


class ActionBody(BaseModel):
    action: str
    note: str = ""


class ControlBody(BaseModel):
    speed: float | None = None
    restart: bool = False
    paused: bool | None = None


class OnboardingBody(BaseModel):
    vpas: list[str]


def mount(app, load: Callable[[], tuple[pd.DataFrame, Any]], predict_chain: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> RailService:
    """Add the /rail and /sandbox routes to the bridge's FastAPI app."""
    service = RailService(predict_chain)
    router = APIRouter(prefix="/rail")

    Who = Depends(rbac.principal)

    def engine() -> RailEngine:
        if service.engine is None:
            detail = {"status": service.status, "error": service.error}
            raise HTTPException(status_code=503, detail=detail)
        return service.engine

    @app.on_event("startup")
    async def _start() -> None:
        asyncio.create_task(service.start(load))

    @router.get("/status")
    async def status() -> dict[str, Any]:
        out: dict[str, Any] = {"status": service.status, "error": service.error, "paused": service.paused}
        if service.engine:
            out["metrics"] = service.engine.metrics()
            out["dataset"] = dataset_facts(service.engine.data)
        return out

    @router.get("/snapshot")
    async def snapshot() -> dict[str, Any]:
        return {**engine().snapshot(), "paused": service.paused}

    @router.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        eng = engine()
        queue: asyncio.Queue = asyncio.Queue()
        service.subscribers.add(queue)

        async def gen():
            try:
                yield f"event: snapshot\ndata: {json.dumps({**eng.snapshot(), 'paused': service.paused}, default=str)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    kind = json.loads(payload)["type"]
                    yield f"event: {kind}\ndata: {payload}\n\n"
            finally:
                service.subscribers.discard(queue)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @router.get("/alerts/{alert_id}")
    async def alert_detail(alert_id: str) -> dict[str, Any]:
        detail = engine().alert_detail(alert_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Alert not found")
        return detail

    @router.post("/alerts/{alert_id}/actions")
    async def alert_action(alert_id: str, body: ActionBody, who: rbac.Principal = Who):
        eng = engine()
        alert = eng.alerts.get(alert_id)
        if body.action in ("clear", "escalate", "freeze"):
            who.require(body.action)
        if alert and eng.is_override(alert, body.action):
            who.require("override", "releasing a hold or clearing a model score >= 0.9")
        result = eng.act(alert_id, body.action, body.note, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.post("/alerts/{alert_id}/investigate")
    async def investigate(alert_id: str, who: rbac.Principal = Who) -> dict[str, Any]:
        """Runs the agent tools an investigator would: score the chain live, check the registry."""
        who.require("investigate")
        eng = engine()
        if alert_id not in eng.alerts:
            raise HTTPException(status_code=404, detail="Alert not found")
        legs = eng.chain_legs(alert_id)
        started = time.perf_counter()
        scored = await asyncio.to_thread(predict_chain, legs)
        elapsed = time.perf_counter() - started
        registry = None
        try:
            from agents.tools_impl import check_suspect_registry

            registry = await asyncio.to_thread(check_suspect_registry, eng.alerts[alert_id].vpa)
        except Exception as error:
            registry = {"error": str(error)}
        return {"legs": legs, "scored": scored, "seconds": elapsed, "registry": registry}

    @router.post("/control")
    async def control(body: ControlBody, who: rbac.Principal = Who) -> dict[str, Any]:
        engine()
        who.require("restart" if body.restart else "control", "restarting the engine" if body.restart else None)
        return service.control(body.speed, body.restart, body.paused)

    @router.get("/cases/{case_id}/evidence-pack")
    async def evidence_pack(case_id: str) -> dict[str, Any]:
        pack = engine().evidence_pack(case_id)
        if not pack:
            raise HTTPException(status_code=404, detail="Case not found")
        return pack

    @router.post("/cases/{case_id}/report")
    async def report(case_id: str, who: rbac.Principal = Who):
        who.require("file_1930_report", "filing a 1930 report")
        result = await asyncio.to_thread(engine().file_report, case_id, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.post("/cases/{case_id}/notify")
    async def notify(case_id: str, who: rbac.Principal = Who):
        who.require("notify", "notifying officers")
        result = await asyncio.to_thread(engine().notify, case_id, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.post("/onboarding/check")
    async def onboarding_check(body: OnboardingBody, who: rbac.Principal = Who) -> dict[str, Any]:
        who.require("onboarding")
        started = time.perf_counter()
        result = await service.graph_call(engine().onboarding_check, [v for v in body.vpas if v.strip()][:10])
        result["latencyMs"] = (time.perf_counter() - started) * 1000
        return result

    # ------------------------------------------------------------------ platform

    @router.post("/ingest/payments")
    async def ingest_payments(request: Request, x_nolambur_signature: str | None = Header(None)):
        """Webhook for payment events: one Payment, or {"payments": [...]}."""
        eng = engine()
        body = await request.body()
        if infra_settings.RAIL_WEBHOOK_SECRET and not integrations.verify(body, x_nolambur_signature, infra_settings.RAIL_WEBHOOK_SECRET):
            service.ingest_stats["rejected"] += 1
            raise HTTPException(status_code=401, detail="bad or missing X-Nolambur-Signature")
        try:
            data = json.loads(body)
            batch = PaymentBatch(**data).payments if isinstance(data, dict) and "payments" in data else [Payment(**data)]
        except (ValueError, TypeError, ValidationError) as error:
            service.ingest_stats["rejected"] += 1
            detail = error.errors() if isinstance(error, ValidationError) else str(error)
            return JSONResponse({"detail": json.loads(json.dumps(detail, default=str))}, status_code=422)
        depth = sum(len(p) for _, p in list(service.inbox._queue))  # type: ignore[attr-defined]
        if depth + len(batch) > MAX_INBOX:
            return JSONResponse({"detail": "ingest backlog full, retry later", "queued": depth}, status_code=429, headers={"Retry-After": "2"})
        service.inbox.put_nowait(("webhook", [p.model_dump() for p in batch]))
        service.ingest_stats["webhookAccepted"] += len(batch)
        return {
            "accepted": len(batch),
            "queued": depth + len(batch),
            "mode": service.mode,
            "clock": "replay clock" if not eng.live else "payment timestamp",
            "paused": service.paused,
        }

    @router.get("/platform")
    async def platform() -> dict[str, Any]:
        return await asyncio.to_thread(service.platform)

    @router.get("/graph/downstream/{account_id}")
    async def downstream(account_id: str, hops: int = 3, limit: int = 200) -> dict[str, Any]:
        eng = engine()
        try:
            return await service.graph_call(eng.downstream, account_id, max(1, min(hops, 5)), max(1, min(limit, 1000)))
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"graph query failed: {error}")

    @router.get("/audit")
    async def audit(account_id: str | None = None, alert_id: str | None = None, run: str = "current", limit: int = 200) -> dict[str, Any]:
        """The durable audit trail. run=current scopes to this replay; run=all spans restarts."""
        eng = engine()
        if not service.store:
            raise HTTPException(status_code=503, detail={"store": service.store_error})
        run_id = eng.run_id if run == "current" else (None if run == "all" else run)
        entries = await asyncio.to_thread(service.store.audit_trail, run_id=run_id, account_id=account_id, alert_id=alert_id, limit=min(limit, 1000))
        return {"runId": run_id, "entries": entries}

    @router.get("/roles")
    async def roles() -> dict[str, Any]:
        return rbac.describe()

    @router.get("/audit/verify")
    async def audit_verify() -> dict[str, Any]:
        """Recompute the audit hash chain; names the first row that was altered."""
        if not service.store:
            raise HTTPException(status_code=503, detail={"store": service.store_error})
        return await asyncio.to_thread(service.store.verify_audit_chain)

    @router.get("/feedback")
    async def feedback() -> dict[str, Any]:
        if not service.store:
            raise HTTPException(status_code=503, detail={"store": service.store_error})
        return await asyncio.to_thread(infra_feedback.report)

    @router.get("/onboarding/presets")
    async def onboarding_presets() -> list[dict[str, Any]]:
        return engine().onboarding_presets()

    @router.get("/evaluation")
    async def evaluation() -> dict[str, Any]:
        if service.evaluation is None:
            raise HTTPException(status_code=503, detail={"status": service.status})
        return service.evaluation

    app.include_router(router)
    app.include_router(sandbox.router())
    return service
