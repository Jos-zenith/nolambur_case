"""Payment-rail engine: the backend of the Merchant Risk Console.

Runs the rule detectors and the trained GIN checkpoint on every payment as it arrives.
By default payments arrive live (RAIL_SOURCE=webhook | kafka | kinesis, infra/ingest.py)
and the clock is their event time. RAIL_SOURCE=replay instead replays the Nolambur
dataset (nolambur_transactions.csv) in timestamp order with full-graph scores, for the
demo and for evaluation. Analyst actions go through the
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
import bisect
import copy
import gc
import json
import math
import os
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
from pydantic import BaseModel, Field, ValidationError

from infra import feedback as infra_feedback
from infra import integrations, rbac, sandbox, settings as infra_settings
from infra.graph import MemoryGraph, make_graph, summarize
from infra.ingest import HIGH_WATER, Payment, PaymentBatch, Source, make_source

SCRIPT_DIR = Path(__file__).resolve().parent
LIVE_ROW_BASE = 1_000_000  # row ids for ingested payments, clear of the CSV's 0..N
MAX_BATCH = 2000  # payments scored and ingested per tick
MAX_INBOX = 50_000
DEMO_PREFIX = "test."  # account ids of the test scams sent from the overview page
DEMO_COOLDOWN = 10.0  # seconds between new test scams, across all visitors
DEMO_MAX = 200  # test scams per bridge process
RULE_VERSIONS = ("r2.0", "r2.1", "r2.2")
RULE_VERSION = os.getenv("RAIL_RULES", "r2.0")  # r2.1 is opt-in; see the R21_* constants
if RULE_VERSION not in RULE_VERSIONS:
    raise ValueError(f"RAIL_RULES must be one of {RULE_VERSIONS}, not {RULE_VERSION!r}")
TICK_SECONDS = 0.5
LEAD_IN_SECONDS = 45

SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}
DETECTORS = {
    "inflow_new_payers": "Inflow burst from new payers",
    "pass_through": "Rapid pass-through",
    "structuring": "Transfers split under the UPI cap",
    "fan_in_new_payers": "Many new payers in a day (r2.1)",
    "hop_from_flagged": "Funds from a flagged account",
    "model_only": "Model-only flag",
}
PRIMARY = ("inflow_new_payers", "pass_through", "structuring", "fan_in_new_payers")

# r2.0 thresholds. Aggregated over windows, because the UPI P2P cap is ₹1 lakh a transfer
# (NPCI): a large sum arrives as several smaller transfers, so a per-transfer threshold is
# either unreachable or trivially split under.
P2P_CAP = 100_000
INFLOW_FLOOR = 150_000  # new-payer inflow in 24 h, at least...
INFLOW_BASELINE_MULT = 3.0  # ...and at least 3x the account's largest daily inflow in the last 7 days
PASS_FLOOR = 100_000
PASS_RATIO = 0.6
PASS_WINDOWS = ((3600, "1 hour"), (6 * 3600, "6 hours"), (86400, "24 hours"))
FORWARDER_RATIO = 0.5  # an account that already forwards half its inflow is a known forwarder...
FORWARDER_SCALE = 3.0  # ...and only alerts on 3x its usual daily inflow
NEAR_CAP = 0.9 * P2P_CAP
BASELINE_DAYS = 7
BASELINE_MIN_ACTIVE = 5  # a baseline counts only for an account active on 5 of the last 7 days, so a new
                         # mule cannot raise its own bar by drip-feeding itself for a day or two

# r2.1 (RAIL_RULES=r2.1). Written after the stress tests (reports/README.md 3.3) showed the fixed
# ₹1 lakh pass-through floor misses rings that move half as much, and the near-cap rule misses
# structuring into small payments. Peer values come from the train days of the base data only
# (python -m infra.calibrate_r21); live, they would be recomputed daily from recent traffic.
R21_PASS_FLOOR = 25_000  # modest absolute floor, for every account
R21_OWN_MULT = 3.0  # an account with history: 3x its own busiest day in the last 7
R21_PEER_BUSIEST = {"individual": 28_000, "supplier": 94_000}  # p95 of each kind's busiest day of P2P inflow
R21_FANIN_PAYERS = 5  # distinct P2P payers new to an individual's account in 24 h; p99.9 on the train days is 3
R21_FANIN_MIN_TOTAL = 5_000
FRICTION_SCORE = 0.95  # RAIL_MODEL_FRICTION=1: a model-only alert this confident delays settlement (level 1)

# r2.2 (RAIL_RULES=r2.2) = r2.1 with a narrower hop rule (reports/README.md 3.6, fixed before stream 3).
# r2.1's hop-from-flagged flagged everyone a mule paid; without it, second-layer recall halved.
R22_HOP_MIN = 6_100  # flagged inflow in 24 h: the p90 individual-to-individual P2P payment on the train days
R22_HOP_SHARE = 0.5  # ...and at least half the account's inflow in those 24 h

# Graded actions (the decision router picks a level; see RailEngine._route).
LEVELS = {0: "alert_only", 1: "delay_settlement", 2: "hold_outbound", 3: "full_hold"}
LEVEL_LABEL = {0: "Alert only", 1: "Delay settlement", 2: "Hold outbound transfers", 3: "Full hold pending supervisor"}
LEVEL_SECONDS = {1: 3600, 2: 86400, 3: 3 * 86400}  # a restriction lifts itself after this unless confirmed
APPEAL_SLA_SECONDS = 86400  # an appeal not decided in time lifts the restriction


def _window(rows: list["Row"], since: float) -> list["Row"]:
    """Rows (time-ordered) at or after `since`."""
    return rows[bisect.bisect_left(rows, since, key=lambda x: x.t):]


def _just_below(amount: float) -> bool:
    """Near the P2P cap, or a just-under amount such as 49,999."""
    a = int(round(amount))
    return NEAR_CAP <= a <= P2P_CAP or (a >= 9_999 and a % 1000 == 999)


def _inr(n: float) -> str:
    s = f"{int(round(n))}"
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return f"₹{head},{tail}"


@dataclass(slots=True)  # one per payment per engine: slots halve their memory
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
    channel: str = "P2P"  # P2P | P2M
    new_payee: bool = False  # the payer's first transfer to this payee (set on ingest)
    delayed: bool = False  # held back by a delay-settlement restriction on the payer

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
            "delayed": self.delayed,
            "channel": self.channel,
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
    action: str = "alert_only"  # the router's level for this alert (LEVELS)

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
            "action": self.action,
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

    def __init__(self, raw: pd.DataFrame, scores, labels: pd.DataFrame, meta: dict[str, Any] | None = None):
        self.meta = meta or {"version": "v1", "file": "nolambur_transactions.csv"}
        ts = pd.to_datetime(raw["timestamp"])
        order = ts.sort_values(kind="stable").index
        score_list = scores.tolist()
        channels = raw["channel"].astype(str).tolist() if "channel" in raw else ["P2P"] * len(raw)
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
                    channel=channels[i],
                )
            )
        self.role = dict(zip(labels["account_id"].astype(str), labels["role"].astype(str)))
        self.bank = dict(zip(labels["account_id"].astype(str), labels["bank"].astype(str)))
        self.kind = dict(zip(labels["account_id"].astype(str), labels["kind"].astype(str))) if "kind" in labels else {}
        self.vpa_to_id: dict[str, str] = {}
        for r in self.rows:
            self.vpa_to_id.setdefault(r.from_vpa, r.from_id)
            self.vpa_to_id.setdefault(r.to_vpa, r.to_id)
        self.start_t = self.rows[0].t
        self.end_t = self.rows[-1].t
        fraud_ts = [r.ts for r in self.rows if r.is_fraud == 1]
        self.fraud_window = (min(fraud_ts), max(fraud_ts)) if fraud_ts else (None, None)
        self.accounts = len(set(self.role) | set(self.vpa_to_id.values()))
        self.kind = dict(zip(labels["account_id"].astype(str), labels["kind"].astype(str))) if "kind" in labels else {}
        # evaluation window: v2 is split by day (train 0-5, val 6-7, test 8-9); v1 has no usable split
        day0 = datetime.fromtimestamp(self.start_t, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        splits = self.meta.get("splitDays")
        self.splits = {k: (day0 + a * 86400, day0 + b * 86400) for k, (a, b) in splits.items()} if splits else None


class RailEngine:
    def __init__(self, data: Dataset, speed: float | None = None, record_actions: bool = True, store=None, source: str = "replay", auto_hold: bool = False,
                 model_threshold: float = 0.9):
        self.data = data
        self.auto_hold = auto_hold  # the decision router acts (graded restrictions); off = alert only
        self.model_threshold = model_threshold
        self.rules = os.getenv("RAIL_RULES", RULE_VERSION)
        self.model_friction = os.getenv("RAIL_MODEL_FRICTION", "0") == "1"
        self.hop_rule = os.getenv("RAIL_HOP_FROM_FLAGGED", "1") != "0"  # 0: the hop detector is off (reports/README.md 3.4)
        speed = speed if speed is not None else float(data.meta.get("defaultSpeed", 4.0))
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
        # graded restrictions from the decision router: account -> level, expiry, appeal. Level 1
        # delays the account's outgoing transfers, 2 blocks them, 3 blocks both directions.
        self.held: dict[str, dict[str, Any]] = {}
        self.pending_delayed: dict[str, list[Row]] = defaultdict(list)  # outgoing transfers held back by level 1
        self.daily_in: dict[str, dict[int, float]] = defaultdict(dict)
        self.daily_out: dict[str, dict[int, float]] = defaultdict(dict)
        self.delayed_amount = 0.0
        self.recovered_fraud = 0.0
        self.recovered_genuine = 0.0
        self.released_delayed = 0.0
        self.restriction_log: list[dict[str, Any]] = []  # every restriction, for the policy evaluation
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
        self._expire()
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
                    channel=p.get("channel") or "P2P",
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
        if self.live:
            self._expire()
        return rows

    def _count_blocked(self, r: Row) -> None:
        if r.is_fraud == 1:
            self.blocked_fraud += r.amount
        elif r.is_fraud == 0:
            self.blocked_genuine += r.amount
        else:
            self.blocked_unlabelled += r.amount

    def _level(self, account_id: str) -> int:
        return 4 if account_id in self.frozen else self.held.get(account_id, {}).get("level", 0)

    def _ingest(self, template: Row) -> None:
        r = copy.copy(template)  # each engine blocks and flags its own copy
        # graded blocking: frozen or level >= 2 stops outgoing; frozen or level 3 also stops incoming
        if self._level(r.from_id) >= 2 or self._level(r.to_id) >= 3:
            r.blocked = True
            self._count_blocked(r)
            self.replayed.append(r)
            self.batch.append(r)
            self.graph.add(r)
            return
        if self._level(r.from_id) == 1:
            r.delayed = True  # held back until the restriction lifts; cancelled if it escalates
            self.delayed_amount += r.amount
            self.pending_delayed[r.from_id].append(r)
        self.replayed.append(r)
        self.batch.append(r)
        self.graph.add(r)
        r.new_payee = r.to_id not in self.payees[r.from_id]
        self.payees[r.from_id].add(r.to_id)
        self.inbound[r.to_id].append(r)
        self.outbound[r.from_id].append(r)
        day = int(r.t // 86400)
        self.daily_in[r.to_id][day] = self.daily_in[r.to_id].get(day, 0.0) + r.amount
        self.daily_out[r.from_id][day] = self.daily_out[r.from_id].get(day, 0.0) + r.amount

        for a in self._alerts_on(r.from_id):  # lead: how long before this account's money moved on
            if a.lead_seconds is None and a.detector in ("inflow_new_payers", "structuring"):
                a.lead_seconds = r.t - a.created_t

        self._check_inflow_new_payers(r)
        self._check_structuring(r)
        if self.rules in ("r2.1", "r2.2"):
            self._check_fan_in(r)
        self._check_pass_through(r)
        if self.hop_rule:
            self._check_hop_from_flagged(r)
        self._check_model_only(r)

    def _alerts_on(self, account_id: str) -> list[Alert]:
        return list(self.alerts_by_account.get(account_id, ()))

    def _stopped(self, account_id: str) -> bool:
        """Frozen, or restricted at level 2+: its outgoing transfers are blocked."""
        return self._level(account_id) >= 2

    def _flagged(self, account_id: str) -> bool:
        return self._stopped(account_id) or any(a.status != "cleared" for a in self._alerts_on(account_id))

    # ------------------------------------------------------------------ detectors

    def _baseline(self, acct: str, t: float) -> tuple[float, float, int]:
        """The account's own last BASELINE_DAYS days before today: largest daily inflow,
        share of inflow it sent on, and how many of those days it was active."""
        day = int(t // 86400)
        ins = [self.daily_in[acct].get(d, 0.0) for d in range(day - BASELINE_DAYS, day)]
        outs = [self.daily_out[acct].get(d, 0.0) for d in range(day - BASELINE_DAYS, day)]
        active = sum(1 for a, b in zip(ins, outs) if a or b)
        total_in = sum(ins)
        return max(ins), (sum(outs) / total_in if total_in >= 20_000 else 0.0), active

    def _check_inflow_new_payers(self, r: Row) -> None:
        """P2P money from payers who had never paid this account, summed over 24 h (72 h at twice
        the bar), above max(₹1.5 lakh, 3x the account's own largest day in the last week)."""
        if not r.new_payee or r.channel != "P2P":
            return
        acct = r.to_id
        base, _, active = self._baseline(acct, r.t)
        if active < BASELINE_MIN_ACTIVE:
            base = 0.0
        threshold = max(INFLOW_FLOOR, INFLOW_BASELINE_MULT * base)
        for window, mult, label in ((86400, 1.0, "24 hours"), (3 * 86400, 2.0, "72 hours")):
            hits = [x for x in _window(self.inbound[acct], r.t - window) if x.new_payee and x.channel == "P2P"]
            total = sum(x.amount for x in hits)
            payers = {x.from_id for x in hits}
            if total < threshold * mult or (len(payers) < 2 and len(hits) < 3):
                continue
            out_of_state = sum(1 for x in hits if x.from_state != x.to_state)
            self._upsert(
                "inflow_new_payers",
                acct,
                severity="critical" if len(payers) >= 3 or total >= 2 * threshold * mult else "high",
                base=78 + 3 * min(len(payers), 5),
                title="Large inflow from payers new to this account",
                reason=(
                    f"{len(payers)} payer{'s' if len(payers) > 1 else ''} who had never paid this account sent {_inr(total)} in {len(hits)} transfers "
                    f"within {label}. The bar was {_inr(threshold * mult)}: "
                    + (f"the larger of {_inr(INFLOW_FLOOR * mult)} and {INFLOW_BASELINE_MULT:g}x the account's own busiest day in the last week ({_inr(base)}). "
                       if base else f"the floor, because the account has too little history for its own baseline. ")
                    + "Scam victims pay mule accounts this way, several transfers under the ₹1 lakh UPI cap."
                ),
                facts=[
                    {"label": "New payers", "value": str(len(payers))},
                    {"label": f"From them, {label}", "value": _inr(total)},
                    {"label": "Account's busiest day, last 7", "value": _inr(base) if base else f"not used (active < {BASELINE_MIN_ACTIVE} days)"},
                    {"label": "From another state", "value": f"{out_of_state} of {len(hits)}"},
                    {"label": "Account state", "value": r.to_state},
                ],
                rows=hits,
            )
            return

    def _check_structuring(self, r: Row) -> None:
        """Several P2P transfers near the ₹1 lakh cap (or just-under amounts like ₹49,999) into
        one account within 24 h, from 2+ payers, at least one of them new."""
        if r.channel != "P2P" or not _just_below(r.amount):
            return
        acct = r.to_id
        hits = [x for x in _window(self.inbound[acct], r.t - 86400) if x.channel == "P2P" and _just_below(x.amount)]
        payers = {x.from_id for x in hits}
        if len(hits) < 3 or len(payers) < 2 or not any(x.new_payee for x in hits):
            return
        self._upsert(
            "structuring",
            acct,
            severity="critical" if len(hits) >= 5 else "high",
            base=74 + 2 * min(len(hits), 8),
            title="Transfers sized just under the UPI cap",
            reason=(
                f"{len(hits)} transfers from {len(payers)} payers in 24 hours were near the ₹1 lakh per-transfer cap or at just-under amounts "
                f"({', '.join(_inr(x.amount) for x in hits[:4])}{'…' if len(hits) > 4 else ''}). Splitting a large payment into cap-sized pieces is how "
                "a victim is made to move several lakh over UPI."
            ),
            facts=[
                {"label": "Transfers near the cap", "value": str(len(hits))},
                {"label": "Payers", "value": str(len(payers))},
                {"label": "Total", "value": _inr(sum(x.amount for x in hits))},
                {"label": "New payers among them", "value": str(len({x.from_id for x in hits if x.new_payee}))},
            ],
            rows=hits,
        )

    def _check_pass_through(self, r: Row) -> None:
        """₹1L+ in and 60%+ of it out again in 2+ transfers to 2+ accounts, within 1 h, 6 h or 24 h.
        An account that already forwards most of its money (a shop paying suppliers) needs 3x its
        usual daily inflow to alert."""
        acct = r.from_id
        base_in, base_ratio, active = self._baseline(acct, r.t)
        floor = self._pass_floor(acct, base_in, active)
        for window, label in PASS_WINDOWS:
            ins = _window(self.inbound[acct], r.t - window)
            outs = _window(self.outbound[acct], r.t - window)
            inflow = sum(x.amount for x in ins)
            outflow = sum(x.amount for x in outs)
            if inflow < floor or len(outs) < 2 or len({x.to_id for x in outs}) < 2 or outflow < PASS_RATIO * inflow:
                continue
            if active >= BASELINE_MIN_ACTIVE and base_ratio >= FORWARDER_RATIO and inflow < FORWARDER_SCALE * base_in:
                return  # an established forwarder at its usual scale
            ratio = min(outflow / inflow, 9.99)
            first_in = min(x.t for x in ins)
            later = [x.t for x in outs if x.t >= first_in]
            turnaround = (min(later) - first_in) if later else 0
            self._upsert(
                "pass_through",
                acct,
                severity="critical" if ratio >= 0.85 and window <= 6 * 3600 else "high",
                base=70 + int(min(ratio, 1) * 20),
                title=f"Money forwarded within {label}",
                reason=(
                    f"Received {_inr(inflow)} and sent {_inr(outflow)} ({round(ratio * 100)}%) on to {len({x.to_id for x in outs})} accounts within {label}. "
                    f"The first onward transfer left {round(turnaround / 60, 1)} minutes after the first inflow."
                    + (f" It usually forwards {round(base_ratio * 100)}% of a smaller daily inflow ({_inr(base_in)})." if active >= BASELINE_MIN_ACTIVE and base_ratio else "")
                ),
                facts=[
                    {"label": f"In, last {label}", "value": _inr(inflow)},
                    {"label": f"Out, last {label}", "value": _inr(outflow)},
                    {"label": "Out / in", "value": f"{round(ratio * 100)}%"},
                    {"label": "Onward recipients", "value": str(len({x.to_id for x in outs}))},
                    {"label": "First in → first out", "value": f"{round(turnaround / 60, 1)} min"},
                ],
                rows=sorted(ins + outs, key=lambda x: x.t),
            )
            return

    def _pass_floor(self, acct: str, base_in: float, active: int) -> float:
        """r2.0: ₹1 lakh for everyone. r2.1: relative. An account with history needs 3x its own
        busiest day; a new one (cold start: no usable history) needs its peer group's p95 busiest
        day. Both at least the ₹25,000 floor."""
        if self.rules not in ("r2.1", "r2.2"):
            return PASS_FLOOR
        if active >= BASELINE_MIN_ACTIVE:
            return max(R21_PASS_FLOOR, R21_OWN_MULT * base_in)
        return max(R21_PASS_FLOOR, R21_PEER_BUSIEST.get(self.data.kind.get(acct, ""), 0.0))

    def _check_fan_in(self, r: Row) -> None:
        """r2.1: 5+ different P2P payers, each paying this individual's account for the first
        time, within 24 h. It counts people, not rupees, so splitting money smaller doesn't hide
        it. Individuals only: shops and suppliers are meant to have many new payers."""
        if not r.new_payee or r.channel != "P2P" or self.data.kind.get(r.to_id, "individual") != "individual":
            return
        acct = r.to_id
        hits = [x for x in _window(self.inbound[acct], r.t - 86400) if x.new_payee and x.channel == "P2P"]
        payers = {x.from_id for x in hits}
        total = sum(x.amount for x in hits)
        if len(payers) < R21_FANIN_PAYERS or total < R21_FANIN_MIN_TOTAL:
            return
        self._upsert(
            "fan_in_new_payers",
            acct,
            severity="critical" if len(payers) >= 2 * R21_FANIN_PAYERS else "high",
            base=72 + 2 * min(len(payers), 10),
            title="Many new payers in a day",
            reason=(
                f"{len(payers)} different people who had never paid this account sent it money within 24 hours ({_inr(total)} in {len(hits)} transfers). "
                f"On ordinary days an individual's account gets at most 3 new payers in 99.9% of cases. Scam victims are sent to mule accounts this way, "
                "at any amount."
            ),
            facts=[
                {"label": "New payers, 24 h", "value": str(len(payers))},
                {"label": "From them", "value": _inr(total)},
                {"label": "Transfers", "value": str(len(hits))},
            ],
            rows=hits,
        )

    def _is_hop_source(self, account_id: str, t: float) -> bool:
        """Frozen or held, or flagged by a primary rule in the last 24h. Hop alerts don't propagate further."""
        if self._stopped(account_id):
            return True
        return any(
            a.detector in PRIMARY and a.status != "cleared" and a.created_t >= t - 86400
            for a in self._alerts_on(account_id)
        )

    def _hop_r22(self, r: Row) -> bool:
        """r2.2: only an individual's account, and only when flagged money in the last 24 h is at
        least ₹6,100 and at least half of everything it received in that time. Shops, suppliers and
        businesses that a mule happens to pay are left alone."""
        if self.data.kind.get(r.to_id, "individual") != "individual":
            return False
        recent = _window(self.inbound[r.to_id], r.t - 86400)
        flagged = sum(x.amount for x in recent if self._is_hop_source(x.from_id, x.t))
        total = sum(x.amount for x in recent)
        return flagged >= R22_HOP_MIN and total > 0 and flagged / total >= R22_HOP_SHARE

    def _check_hop_from_flagged(self, r: Row) -> None:
        """Receives money from an account that a primary rule flagged in the last 24 hours."""
        if self._stopped(r.to_id) or not self._is_hop_source(r.from_id, r.t):
            return
        if self.rules == "r2.2" and not self._hop_r22(r):
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
        """The model scores the edge at or above its threshold (chosen on the validation days) but
        no rule has fired on the receiver."""
        th = self.model_threshold
        if r.gnn < th or any(a.detector != "model_only" for a in self._alerts_on(r.to_id)):
            return
        hits = [x for x in self.inbound[r.to_id] if x.gnn >= th]
        self._upsert(
            "model_only",
            r.to_id,
            severity="medium",
            base=45,
            title="Model flags this account's inflow",
            reason=(
                f"The GIN checkpoint scores {len(hits)} inbound transfer{'s' if len(hits) > 1 else ''} at {th:.2f} or higher, "
                "but no rule has fired. Treat as a lead to check, not a finding."
            ),
            facts=[
                {"label": "Highest model score", "value": f"{max(x.gnn for x in hits):.3f}"},
                {"label": f"Transfers scored {th:.2f}+", "value": str(len(hits))},
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
        if account_id in self.frozen:  # a restricted account keeps collecting evidence; a frozen one is closed
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

    def _route(self, alert: Alert) -> tuple[int, str]:
        """The decision router: rule and score combination -> action level.

            model-only lead, or medium severity          0 alert only
            high severity                                1 delay settlement
            high + model >= threshold, or critical       2 hold outbound
            critical + model >= threshold + corroborated 3 full hold (pending supervisor)
        corroborated = two or more different detectors open on the account. An account an
        analyst has already cleared in this run steps down one level.
        """
        active = [a for a in self._alerts_on(alert.account_id) if a.status not in ("cleared", "superseded")]
        rules = [a for a in active if a.detector != "model_only"]
        detectors = {a.detector for a in rules}
        model = max((a.gnn_max for a in active), default=0.0) >= self.model_threshold
        # the decision is about the account: its strongest open rule alert, with every detector that agrees
        severity = max((a.severity for a in rules), key=lambda x: SEV_RANK[x], default="low")
        if not rules and self.model_friction and max((a.gnn_max for a in active), default=0.0) >= max(FRICTION_SCORE, self.model_threshold):
            level, why = 1, f"model-only lead scored {FRICTION_SCORE:.2f}+: delay settlement (friction, not a hold)"
        elif not rules or SEV_RANK[severity] <= SEV_RANK["medium"]:
            level, why = 0, "lead or medium severity: alert only"
        elif severity == "high":
            level, why = (2, f"high severity and model >= {self.model_threshold:.2f}") if model else (1, "high severity, model below threshold")
        elif model and len(detectors) >= 2:
            level, why = 3, f"critical, model >= {self.model_threshold:.2f}, {len(detectors)} detectors agree"
        else:
            level, why = 2, "critical" + (f", model >= {self.model_threshold:.2f}" if model else "") + ", one detector"
        if level and any(a.status == "cleared" for a in self._alerts_on(alert.account_id)):
            level, why = level - 1, why + "; stepped down: an analyst cleared this account before"
        return level, why

    def _maybe_hold(self, alert: Alert) -> None:
        """Apply the router's level. Restrictions only escalate automatically; lifting one is a
        person's decision, an expiry, or a missed appeal deadline."""
        level, why = self._route(alert)
        alert.action = LEVELS[level]
        acct = alert.account_id
        current = self.held.get(acct)
        if not self.auto_hold or level == 0 or acct in self.frozen or alert.status not in ("open", "escalated", "held"):
            return
        if current and current["level"] >= level:
            return
        self.held[acct] = {
            "at": current["at"] if current else self.sim_t,
            "by": "system",
            "alertId": alert.id,
            "policy": why,
            "level": level,
            "action": LEVELS[level],
            "label": LEVEL_LABEL[level],
            "expiresT": self.sim_t + LEVEL_SECONDS[level],
            "appeal": current.get("appeal") if current else None,
        }
        self.restriction_log.append({"account": acct, "level": level, "at": self.sim_t, "alertId": alert.id, "role": self.data.role.get(acct, "unknown"), "end": None, "how": None})
        if level >= 2:
            self._cancel_delayed(acct)
            alert.status = "held"
            alert.case_id = self._attach_to_case(alert).id
            self.graph.mark(acct, frozen=True)
        self._log(
            "restrict", "system",
            f"{LEVEL_LABEL[level]} on {alert.vpa} until {datetime.fromtimestamp(self.sim_t + LEVEL_SECONDS[level], timezone.utc).strftime('%d %b %H:%M')}: {why}.",
            role="system", alert_id=alert.id, account_id=acct, case_id=alert.case_id, level=level,
        )
        self.events.append({"type": "held", "accountId": acct, "vpa": alert.vpa, "alertId": alert.id, "level": level, "action": LEVELS[level]})

    def _cancel_delayed(self, acct: str) -> None:
        """Escalation or freeze while transfers were delayed: they never leave."""
        for r in self.pending_delayed.pop(acct, []):
            r.blocked = True
            if r.is_fraud == 1:
                self.recovered_fraud += r.amount
            elif r.is_fraud == 0:
                self.recovered_genuine += r.amount
            self._count_blocked(r)

    def _lift(self, acct: str, how: str, actor: str = "system", note: str = "") -> None:
        restriction = self.held.pop(acct, None)
        if not restriction:
            return
        for r in self.pending_delayed.pop(acct, []):  # delayed transfers go through
            self.released_delayed += r.amount
        for entry in reversed(self.restriction_log):
            if entry["account"] == acct and entry["end"] is None:
                entry["end"], entry["how"] = self.sim_t, how
        alert = self.alerts.get(restriction["alertId"])
        if alert and alert.status == "held" and how != "cleared":
            alert.status = "open"  # back to the queue: a person still has to decide
            self.events.append({"type": "alert", "alert": alert.public()})
        if not any(a.status in ("open", "escalated", "held") for a in self._alerts_on(acct)):
            self.graph.mark(acct, flagged=False, frozen=False)
        else:
            self.graph.mark(acct, frozen=False)
        if how != "cleared":
            self._log(how, actor, note or f"{restriction['label']} on {self._vpa(acct)} lifted: {how.replace('_', ' ')}.", role="system" if actor == "system" else None,
                      alert_id=restriction["alertId"], account_id=acct)
        self.events.append({"type": "released", "accountId": acct, "vpa": self._vpa(acct), "how": how})

    def _expire(self) -> None:
        """Time limits: a restriction nobody confirmed lifts itself; so does one whose appeal was not decided in time."""
        for acct, restriction in list(self.held.items()):
            appeal = restriction.get("appeal")
            if appeal and appeal["status"] == "open" and self.sim_t >= appeal["dueT"]:
                appeal["status"] = "lapsed"
                self._lift(acct, "appeal_sla_release", note=f"Appeal on {self._vpa(acct)} not decided within {APPEAL_SLA_SECONDS // 3600} h: restriction lifted.")
            elif self.sim_t >= restriction["expiresT"]:
                self._lift(acct, "restriction_expired")

    def appeal(self, alert_id: str, statement: str, actor: str, role: str) -> dict[str, Any]:
        """Record the account holder's appeal against a restriction (taken by support or an analyst)."""
        alert = self.alerts.get(alert_id)
        if not alert:
            return {"error": "Alert not found", "status": 404}
        restriction = self.held.get(alert.account_id)
        if not restriction:
            return {"error": "This account has no active restriction to appeal", "status": 409}
        if not statement.strip():
            return {"error": "The appeal needs the account holder's statement", "status": 422}
        if restriction.get("appeal") and restriction["appeal"]["status"] == "open":
            return {"error": "An appeal is already open", "status": 409}
        restriction["appeal"] = {"at": self.sim_t, "by": actor, "statement": statement.strip()[:2000], "dueT": self.sim_t + APPEAL_SLA_SECONDS, "status": "open"}
        self._log("appeal_received", actor, statement.strip()[:300], role=role, alert_id=alert.id, account_id=alert.account_id)
        self.events.append({"type": "alert", "alert": alert.public()})
        return {"alert": alert.public(), "restriction": restriction}

    def decide_appeal(self, alert_id: str, decision: str, note: str, actor: str, role: str) -> dict[str, Any]:
        """uphold keeps the restriction; release lifts it and clears the alert (a labelled false positive)."""
        alert = self.alerts.get(alert_id)
        restriction = self.held.get(alert.account_id) if alert else None
        appeal = (restriction or {}).get("appeal")
        if not appeal or appeal["status"] != "open":
            return {"error": "No open appeal on this alert's account", "status": 409}
        if decision not in ("uphold", "release"):
            return {"error": "decision must be uphold or release", "status": 422}
        if not note.strip():
            return {"error": "A note is required", "status": 422}
        appeal.update(status="upheld" if decision == "uphold" else "released", decidedBy=actor, decidedT=self.sim_t, note=note.strip())
        self._log(f"appeal_{'upheld' if decision == 'uphold' else 'released'}", actor, note.strip(), role=role, alert_id=alert.id, account_id=alert.account_id)
        if decision == "release":
            return self.act(alert.id, "clear", f"Appeal released: {note.strip()}", actor, role)
        return {"alert": alert.public(), "restriction": restriction}

    def _vpa(self, account_id: str) -> str:
        rows = self.inbound.get(account_id) or self.outbound.get(account_id)
        if rows:
            r = rows[0]
            return r.to_vpa if r.to_id == account_id else r.from_vpa
        return account_id

    # ------------------------------------------------------------------ actions

    def is_override(self, alert: Alert, action: str) -> bool:
        """Clearing something the model scored at or above its threshold, or lifting a restriction."""
        return action == "clear" and (alert.account_id in self.held or alert.gnn_max >= self.model_threshold)

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
            restriction = self.held.get(alert.account_id)
            if restriction and not any(a.status == "held" for a in self._alerts_on(alert.account_id)):
                self._lift(alert.account_id, "cleared", actor)
            if not any(a.status not in ("cleared", "superseded") for a in self._alerts_on(alert.account_id)):
                self.graph.mark(alert.account_id, flagged=False, frozen=False)
        elif action == "escalate":
            if not was_held:  # a held alert keeps its hold; escalating just files it to a case
                alert.status = "escalated"
            alert.case_id = self._attach_to_case(alert).id
        elif action == "freeze":
            alert.status = "frozen"
            alert.case_id = self._attach_to_case(alert).id
            if alert.account_id in self.held:
                for entry in reversed(self.restriction_log):
                    if entry["account"] == alert.account_id and entry["end"] is None:
                        entry["end"], entry["how"] = self.sim_t, "frozen"
                self.held.pop(alert.account_id, None)
            self._cancel_delayed(alert.account_id)
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
        # Same definitions as evaluate_temporal, over what has replayed so far: a mule counts once
        # scam money has touched it (mules also shop, and nobody can catch that), recall is rules
        # or model, lead is per mule from its first alert to the first scam money leaving it.
        mule_roles = ("l1_mule", "l2_mule")
        role = self.data.role
        first_in: dict[str, float] = {}
        first_out: dict[str, float] = {}
        for r in self.replayed:
            if r.is_fraud != 1:
                continue
            if role.get(r.to_id) in mule_roles and r.t < first_in.get(r.to_id, math.inf):
                first_in[r.to_id] = r.t
            if role.get(r.from_id) in mule_roles and r.t < first_out.get(r.from_id, math.inf):
                first_out[r.from_id] = r.t
        mules_active = set(first_in) | set(first_out)
        first_alert: dict[str, float] = {}
        for a in self.alerts.values():
            first_alert[a.account_id] = min(first_alert.get(a.account_id, math.inf), a.created_t)
        # Accounts outside the labelled dataset (new live payers) have no truth; leave them out.
        labelled = [a for a in alerts if a.truth_role != "unknown"]
        rule_accounts = {a.account_id for a in labelled if a.detector != "model_only"}
        alerted_accounts = {a.account_id for a in labelled}
        mules_alerted = alerted_accounts & mules_active
        leads = [first_out[m] - first_alert[m] for m in mules_active if m in first_alert and m in first_out]
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
            "leadN": len(leads),
            "alertedBeforeMoneyLeft": sum(1 for x in leads if x > 0),
            # account level, rules + model, every labelled account ever alerted (a mule or not)
            "precision": (sum(1 for a in alerted_accounts if role.get(a) in mule_roles) / len(alerted_accounts)) if alerted_accounts else None,
            "muleRecall": (len(mules_alerted) / len(mules_active)) if mules_active else None,
            "muleRecallRules": (len(rule_accounts & mules_active) / len(mules_active)) if mules_active else None,
            "mulesSeen": len(mules_active),
            "mulesAlerted": len(mules_alerted),
            "frozenAccounts": len(self.frozen),
            "heldAccounts": sum(1 for h in self.held.values() if h["level"] >= 2),
            "delayedAccounts": sum(1 for h in self.held.values() if h["level"] == 1),
            "restrictionsByLevel": {LEVELS[k]: sum(1 for h in self.held.values() if h["level"] == k) for k in (1, 2, 3)},
            "appealsOpen": sum(1 for h in self.held.values() if (h.get("appeal") or {}).get("status") == "open"),
            "delayedAmount": self.delayed_amount,
            "recoveredFraudAmount": self.recovered_fraud,
            "modelThreshold": self.model_threshold,
            "ruleVersion": RULE_VERSION,
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

    def network(self, limit: int = 40, per_account: int = 6) -> dict[str, Any]:
        """The money graph around the accounts under alert: who paid whom, one edge per pair,
        biggest flows first. Most severe and most recent alerts are kept when over `limit`."""
        worst: dict[str, Alert] = {}
        for a in self.alerts.values():
            if a.status in ("superseded", "cleared"):
                continue
            cur = worst.get(a.account_id)
            if cur is None or (SEV_RANK[a.severity], a.updated_t) > (SEV_RANK[cur.severity], cur.updated_t):
                worst[a.account_id] = a
        picked = sorted(worst.values(), key=lambda a: (SEV_RANK[a.severity], a.updated_t), reverse=True)[:limit]
        centre = {a.account_id for a in picked}

        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for acct in centre:
            flows: dict[tuple[str, str], list[Row]] = defaultdict(list)
            for r in self.inbound.get(acct, []):
                flows[(r.from_id, r.to_id)].append(r)
            for r in self.outbound.get(acct, []):
                flows[(r.from_id, r.to_id)].append(r)
            ranked = sorted(flows.items(), key=lambda kv: sum(r.amount for r in kv[1]), reverse=True)
            # keep links between alerted accounts, then the biggest other flows
            keep = [kv for kv in ranked if kv[0][0] in centre and kv[0][1] in centre]
            keep += [kv for kv in ranked if not (kv[0][0] in centre and kv[0][1] in centre)][:per_account]
            for (src, dst), rows in keep:
                if (src, dst) in pairs:
                    continue
                pairs[(src, dst)] = {
                    "source": src,
                    "target": dst,
                    "amount": round(sum(r.amount for r in rows), 2),
                    "count": len(rows),
                    "gnnMax": round(max(r.gnn for r in rows), 4),
                    "blocked": any(r.blocked for r in rows),
                    "lastT": max(r.t for r in rows),
                }

        ids = centre | {e["source"] for e in pairs.values()} | {e["target"] for e in pairs.values()}
        nodes = []
        for acct in ids:
            a = worst.get(acct)
            nodes.append({
                "id": acct,
                "vpa": self._vpa(acct),
                "level": self._level(acct),
                "severity": a.severity if a else None,
                "alertId": a.id if a else None,
                "detector": a.detector if a else None,
                "gnnMax": round(a.gnn_max, 4) if a else None,
                "test": acct.startswith(DEMO_PREFIX),
            })
        return {"simT": self.sim_t, "nodes": nodes, "edges": list(pairs.values()), "alertedAccounts": len(worst), "shown": len(centre)}

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

    def account_status(self, vpa: str) -> dict[str, Any]:
        """For the registry check: is this settlement VPA flagged, held or frozen here?"""
        acct = self.account_for(vpa.strip())
        if not acct:
            return {"seen": False, "flagged": False, "frozen": False, "held": False, "alerts": []}
        return {
            "seen": True,
            "accountId": acct,
            "flagged": self._flagged(acct),
            "frozen": acct in self.frozen,
            "held": acct in self.held,
            "alerts": [a.id for a in self._alerts_on(acct) if a.status != "cleared"],
        }

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
        "version": data.meta.get("version", "v1"),
        "file": data.meta.get("file", "nolambur_transactions.csv"),
        "splits": {k: [datetime.fromtimestamp(a, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), datetime.fromtimestamp(b, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")] for k, (a, b) in data.splits.items()} if data.splits else None,
        "scores": data.meta.get("scores"),
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


TRAINING_METRICS = SCRIPT_DIR / "models" / ("local_finetuned_gin_nolambur_v2.metrics.json" if infra_settings.NOLAMBUR_DATASET == "v2" else "local_finetuned_gin_nolambur.metrics.json")


def _training_log() -> dict[str, Any]:
    """The last finetune run: per-epoch F1 and the held-out test result.

    Read from logs/logs.log when it exists (local runs). A deployed bridge has no logs/
    (it is gitignored), so it falls back to the metrics file saved next to the checkpoint,
    which `python rail_engine.py --save-training-metrics` writes from the log.
    """
    path = SCRIPT_DIR / "logs" / "logs.log"
    if not path.exists():
        if TRAINING_METRICS.exists():
            return {**json.loads(TRAINING_METRICS.read_text(encoding="utf-8")), "source": TRAINING_METRICS.name}
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
    return {"epochs": runs[-1] if runs else [], "test": test, "lastEpochAt": stamp, "runsInLog": len(runs), "source": "logs/logs.log"}


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson interval for a proportion k/n: the test set is small, so say how small."""
    if not n:
        return None
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _with_ci(m: dict[str, Any]) -> dict[str, Any]:
    return {**m, "precisionCi": _wilson(m["tp"], m["tp"] + m["fp"]), "recallCi": _wilson(m["tp"], m["tp"] + m["fn"])}


def _roc_auc(y: list[int], s: list[float]) -> float | None:
    """Mann-Whitney U with tie correction: P(score of a fraud edge > score of a clean one)."""
    import numpy as np

    y_arr, s_arr = np.asarray(y), np.asarray(s, dtype=float)
    pos, neg = int(y_arr.sum()), int(len(y_arr) - y_arr.sum())
    if not pos or not neg:
        return None
    order = s_arr.argsort(kind="mergesort")
    ranks = np.empty(len(s_arr))
    sorted_s = s_arr[order]
    i = 0
    while i < len(sorted_s):  # average ranks over ties
        j = i
        while j + 1 < len(sorted_s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[y_arr == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def _average_precision(y: list[int], s: list[float]) -> float | None:
    """Area under the precision-recall curve, step-wise (as sklearn's average_precision_score)."""
    import numpy as np

    y_arr, s_arr = np.asarray(y), np.asarray(s, dtype=float)
    if not y_arr.sum():
        return None
    order = np.argsort(-s_arr, kind="mergesort")
    y_sorted, s_sorted = y_arr[order], s_arr[order]
    distinct = np.r_[np.flatnonzero(np.diff(s_sorted)), len(s_sorted) - 1]  # last index of each score value
    tp = np.cumsum(y_sorted)[distinct]
    precision = tp / (distinct + 1)
    recall = tp / y_arr.sum()
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def choose_threshold(data: Dataset) -> dict[str, Any]:
    """The model-alert threshold that maximises F1 on the validation days (never on test)."""
    if not data.splits:
        return {"threshold": 0.9, "source": "fixed (v1 has no validation period)"}
    a, b = data.splits["val"]
    rows = [r for r in data.rows if a <= r.t < b]
    best = (0.9, -1.0, {})
    for th in [x / 100 for x in range(5, 100)]:
        tp = sum(1 for r in rows if r.gnn >= th and r.is_fraud)
        fp = sum(1 for r in rows if r.gnn >= th and not r.is_fraud)
        fn = sum(1 for r in rows if r.gnn < th and r.is_fraud)
        m = _prf(tp, fp, fn)
        if m["f1"] >= best[1]:
            best = (th, m["f1"], m)
    return {"threshold": best[0], "source": "max F1 on the validation days", "validation": {**best[2], "edges": len(rows)}}


def evaluate(data: Dataset, model_threshold: float | None = None) -> dict[str, Any]:
    if data.splits:
        return evaluate_temporal(data, model_threshold)
    return evaluate_v1(data)


def evaluate_temporal(data: Dataset, model_threshold: float | None = None) -> dict[str, Any]:
    """Everything reported here is measured on the test days only (v2: days 8-9), with a model
    trained on days 0-5 and a threshold picked on days 6-7. Rules replay the whole dataset,
    because they need each account's history, but only test-day alerts and mules count."""
    t0, t1 = data.splits["test"]
    in_test = lambda t: t0 <= t < t1  # noqa: E731
    test_rows = [r for r in data.rows if in_test(r.t)]
    chosen = choose_threshold(data)
    th = model_threshold if model_threshold is not None else chosen["threshold"]
    days = (t1 - t0) / 86400
    y = [r.is_fraud for r in test_rows]
    scores = [r.gnn for r in test_rows]

    # ---- model, edge level (online, time-respecting scores)
    thresholds = []
    for x in sorted({0.3, 0.5, 0.7, 0.9, 0.95, round(th, 2)}):
        tp = sum(1 for r in test_rows if r.gnn >= x and r.is_fraud)
        fp = sum(1 for r in test_rows if r.gnn >= x and not r.is_fraud)
        thresholds.append({"threshold": x, "chosen": abs(x - th) < 1e-9, **_prf(tp, fp, sum(y) - tp)})
    ranked = sorted(test_rows, key=lambda r: -r.gnn)
    model = {
        "edges": len(test_rows),
        "positives": sum(y),
        "rocAuc": _roc_auc(y, scores),
        "averagePrecision": _average_precision(y, scores),
        "threshold": th,
        "thresholdSource": chosen["source"],
        "validation": chosen.get("validation"),
        "atThreshold": _with_ci(next(t for t in thresholds if t["chosen"])),
        "thresholds": thresholds,
        "precisionAtK": [{"k": k, "precision": sum(r.is_fraud for r in ranked[:k]) / k} for k in (25, 50, 100, 200) if k <= len(ranked)],
        "flaggedPerDay": sum(1 for r in test_rows if r.gnn >= th) / days,
    }
    per_layer = []
    for layer in sorted({r.layer for r in test_rows}):
        subset = [r for r in test_rows if r.layer == layer]
        per_layer.append({"layer": layer, "rows": len(subset), "flagged": sum(1 for r in subset if r.gnn >= th),
                          "amountMedian": statistics.median(r.amount for r in subset), "amountMax": max(r.amount for r in subset)})
    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    hist = [{"bin": f"{lo:.1f}–{min(hi, 1):.1f}", "fraud": sum(1 for r in test_rows if lo <= r.gnn < hi and r.is_fraud),
             "clean": sum(1 for r in test_rows if lo <= r.gnn < hi and not r.is_fraud)} for lo, hi in zip(bins, bins[1:])]

    # ---- rules, account level, alert-only replay
    offline = RailEngine(data, record_actions=False, auto_hold=False, model_threshold=th)
    offline.run_to_end()
    mule_roles = ("l1_mule", "l2_mule")
    active_fraud = [r for r in test_rows if r.is_fraud]
    mules = {a for r in active_fraud for a in (r.from_id, r.to_id) if data.role.get(a) in mule_roles}
    test_alerts = [a for a in offline.alerts.values() if in_test(a.created_t)]
    rule_alerts = [a for a in test_alerts if a.detector != "model_only"]
    rule_accounts = {a.account_id for a in rule_alerts}
    model_accounts = {a.account_id for a in test_alerts if a.detector == "model_only"}
    by_detector = []
    for det in DETECTORS:
        accts = {a.account_id for a in test_alerts if a.detector == det}
        hits = len(accts & mules)
        by_detector.append({"detector": det, "label": DETECTORS[det], "alerts": len(accts), "mules": hits, "precision": hits / len(accts) if accts else None})
    queue = []
    for a in sorted(test_alerts, key=lambda a: (-a.score, a.created_t)):  # the analyst's queue order
        if a.account_id not in {q.account_id for q in queue}:
            queue.append(a)
    analysts = int(os.getenv("RAIL_ANALYSTS", "2"))
    alerts_per_day = len(queue) / days
    # lead: first alert on a mule vs. the first time fraud money left it
    first_alert: dict[str, float] = {}
    for a in offline.alerts.values():
        if a.account_id in mules:
            first_alert[a.account_id] = min(first_alert.get(a.account_id, math.inf), a.created_t)
    first_out: dict[str, float] = {}
    first_in: dict[str, float] = {}
    for r in active_fraud:
        if r.from_id in mules:
            first_out[r.from_id] = min(first_out.get(r.from_id, math.inf), r.t)
        if r.to_id in mules:
            first_in[r.to_id] = min(first_in.get(r.to_id, math.inf), r.t)
    lead = [first_out[m] - first_alert[m] for m in mules if m in first_alert and m in first_out]
    to_alert = [first_alert[m] - first_in[m] for m in mules if m in first_alert and m in first_in]
    detectors = {
        "window": "test days only",
        "accountLevel": _with_ci(_prf(len(rule_accounts & mules), len(rule_accounts - mules), len(mules - rule_accounts))),
        "combined": _with_ci(_prf(len((rule_accounts | model_accounts) & mules), len((rule_accounts | model_accounts) - mules), len(mules - rule_accounts - model_accounts))),
        "modelOnlyAccounts": len(model_accounts),
        "modelOnlyMules": len(model_accounts & mules),
        "mulesActive": len(mules),
        "byDetector": by_detector,
        "precisionAtK": [{"k": k, "precision": sum(1 for a in queue[:k] if a.account_id in mules) / k} for k in (5, 10, 20, 50) if k <= len(queue)],
        "alertsPerDay": alerts_per_day,
        "analysts": analysts,
        "alertsPerAnalystPerDay": alerts_per_day / analysts,
        "leadSeconds": {"n": len(lead), "median": _pct(lead, 0.5), "p10": _pct(lead, 0.1), "p90": _pct(lead, 0.9),
                        "alertedBeforeMoneyLeft": sum(1 for x in lead if x > 0), "mulesThatForwarded": len(first_out), "note": "first time fraud money left a mule minus its first alert; negative = alerted after"},
        "secondsToAlert": {"n": len(to_alert), "median": _pct(to_alert, 0.5), "p90": _pct(to_alert, 0.9), "note": "first fraud inflow to a mule until its first alert"},
        "byRole": {role: {"active": sum(1 for m in mules if data.role.get(m) == role),
                          "found": sum(1 for m in (rule_accounts | model_accounts) & mules if data.role.get(m) == role)} for role in mule_roles},
        "ruleVersion": offline.rules,
        "modelFriction": offline.model_friction,
        "hopFromFlagged": offline.hop_rule,
    }

    del offline  # two whole-dataset replays at once do not fit a 512 MB instance
    gc.collect()

    # ---- the graded-action policy, nobody acting
    policy = RailEngine(data, record_actions=False, auto_hold=True, model_threshold=th)
    policy.run_to_end()
    prow = [r for r in policy.replayed if in_test(r.t)]
    fraud_total = sum(r.amount for r in prow if r.is_fraud == 1)
    recovered = sum(r.amount for r in prow if r.is_fraud == 1 and r.blocked and r.delayed)
    blocked = sum(r.amount for r in prow if r.is_fraud == 1 and r.blocked and not r.delayed)
    restr = [e for e in policy.restriction_log if in_test(e["at"])]
    innocent = [e for e in restr if e["role"] not in mule_roles]
    hours = lambda e: ((e["end"] if e["end"] is not None else policy.sim_t) - e["at"]) / 3600  # noqa: E731
    policy_out = {
        "ladder": [{"level": k, "action": LEVELS[k], "label": LEVEL_LABEL[k], "limitHours": LEVEL_SECONDS.get(k, 0) / 3600 if k else None} for k in LEVELS],
        "appealSlaHours": APPEAL_SLA_SECONDS / 3600,
        "fraudTotal": fraud_total,
        "fraudBlocked": blocked,
        "fraudRecoveredFromDelay": recovered,
        "fraudStopped": blocked + recovered,
        "fraudLost": fraud_total - blocked - recovered,
        "genuineBlocked": sum(r.amount for r in prow if r.is_fraud == 0 and r.blocked),
        "genuineDelayedThenReleased": sum(r.amount for r in prow if r.is_fraud == 0 and r.delayed and not r.blocked),
        "fraudDelayed": sum(r.amount for r in prow if r.is_fraud == 1 and r.delayed),
        "restrictions": {LEVELS[k]: sum(1 for e in restr if e["level"] == k) for k in (1, 2, 3)},
        "restrictedAccounts": len({e["account"] for e in restr}),
        "restrictedMules": len({e["account"] for e in restr if e["role"] in mule_roles}),
        "innocentRestricted": len({e["account"] for e in innocent}),
        "innocentRestrictionHours": sum(hours(e) for e in innocent),
        "lifted": {how: sum(1 for e in restr if e["how"] == how) for how in ("restriction_expired", "appeal_sla_release", "cleared", "frozen")},
        "note": "Test days, replay with nobody acting except the router. Blocked = never sent; recovered = delayed, then cancelled when the restriction escalated. Money stopped is an estimate of loss avoided; it ignores recovery through the banks.",
    }

    del policy, prow
    gc.collect()
    checkpoint = Path(data.meta.get("checkpoint", ""))
    return {
        "dataset": dataset_facts(data),
        "evaluation": "temporal",
        "split": {k: [datetime.fromtimestamp(a, timezone.utc).isoformat(timespec="seconds"), datetime.fromtimestamp(b, timezone.utc).isoformat(timespec="seconds")] for k, (a, b) in data.splits.items()},
        "model": {
            "architecture": "GINe (edge-feature GIN), 2 message-passing layers",
            "checkpoint": checkpoint.name,
            "checkpointBytes": checkpoint.stat().st_size if checkpoint.exists() else None,
            "checkpointModified": datetime.fromtimestamp(checkpoint.stat().st_mtime).isoformat(timespec="minutes") if checkpoint.exists() else None,
            "edgeFeatures": data.meta.get("features"),
            "training": "Finetune only, trained on the train days (0-5); threshold picked on the validation days (6-7).",
            "scoring": data.meta.get("scores"),
        },
        "trainingLog": _training_log(),
        "test": {**model, "perLayer": per_layer, "histogram": hist},
        "detectors": detectors,
        "policy": policy_out,
    }


def evaluate_v1(data: Dataset) -> dict[str, Any]:
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
    held_ids = {e["account"] for e in policy.restriction_log if e["level"] >= 2}
    hold_delay = [e["at"] - policy.alerts[e["alertId"]].first_evidence_t for e in policy.restriction_log if e["level"] >= 2]
    auto_hold = {
        "policy": "graded router (r2.0); held = hold outbound or full hold",
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


def load_rail_dataset(load_v1: Callable[[], tuple[pd.DataFrame, Any]]) -> Dataset:
    """NOLAMBUR_DATASET=v2 (default): nolambur_v2/ with time-respecting online scores from
    infra/scorer.py. v1: the original CSV with the bridge's full-graph scores."""
    if infra_settings.NOLAMBUR_DATASET == "v1":
        raw, scores = load_v1()
        labels = pd.read_csv(SCRIPT_DIR / "nolambur_labels.csv")
        return Dataset(raw, scores, labels, {"version": "v1", "file": "nolambur_transactions.csv", "defaultSpeed": 4.0,
                                             "scores": "full-graph pass at start-up: a score can see later edges", "features": ["Timestamp", "Amount Received", "Received Currency", "Payment Format"],
                                             "checkpoint": str(SCRIPT_DIR / "models" / "local_finetuned_gin_nolambur.pt")})
    import numpy as np
    from infra import scorer as online

    spec = online.DATASETS["v2"]
    raw = pd.read_csv(spec["raw"])
    labels = pd.read_csv(spec["labels"])
    scores_path = spec["dir"] / "online_scores.npy"
    meta_path = scores_path.with_suffix(".json")
    current = online.checkpoint_sha(spec["checkpoint"])
    if not scores_path.exists() or json.loads(meta_path.read_text(encoding="utf-8")).get("checkpointSha") != current:
        online.precompute("v2")  # a few minutes; ship online_scores.npy to skip it
    scores = np.load(scores_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return Dataset(raw, scores, labels, {
        "version": "v2", "file": "nolambur_v2/transactions.csv", "defaultSpeed": 240.0,
        "splitDays": {"train": [0, 6], "val": [6, 8], "test": [8, 10]},
        "scores": f"online and time-respecting (infra/scorer.py): each edge scored from edges up to its own {meta['bucketSeconds']:g}-second bucket, {meta['windowHours']:g}-hour window",
        "features": meta["features"], "checkpoint": str(spec["checkpoint"]),
    })


def make_live_scorer(data: Dataset):
    """Incremental scorer for payments that arrive at run time (v2 only; v1 uses /predict)."""
    if data.meta.get("version") != "v2":
        return None
    from infra import scorer as online

    model, norm = online.load_gin(online.DATASETS["v2"]["checkpoint"])
    mode = "cached" if infra_settings.RAIL_SCORING == "cached" else "exact"
    return online.OnlineScorer(model, norm, mode=mode, refresh_seconds=infra_settings.RAIL_SCORING_REFRESH)


class RailService:
    """Owns the engine, drives the replay clock and fans events out to SSE clients."""

    def __init__(self, predict_chain: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None) -> None:
        self.engine: RailEngine | None = None
        self.evaluation: dict[str, Any] | None = None
        self.threshold: dict[str, Any] | None = None
        self.scorer = None  # infra.scorer.OnlineScorer (v2)
        self.scorer_rows = 0  # replayed rows already added to the scorer's graph
        self.scorer_stats = {"batches": 0, "lastMs": None, "lastSubgraphEdges": None}
        self.status = "starting"
        self.error: str | None = None
        self.paused = False
        self.subscribers: set[asyncio.Queue] = set()
        self.predict_chain = predict_chain
        self.mode = infra_settings.RAIL_SOURCE if infra_settings.RAIL_SOURCE in ("webhook", "kafka", "kinesis", "replay") else "webhook"
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.source: Source = make_source()
        self.store = None
        self.store_error: str | None = None
        self.ingest_stats = {"webhookAccepted": 0, "rejected": 0, "scored": 0, "scoreErrors": 0, "lastScoreError": None, "lastBatch": 0, "lastScoreMs": None}
        self._flushing = False
        self.demos: dict[str, dict[str, Any]] = {}
        self.demo_last_start = 0.0

    async def start(self, load: Callable[[], tuple[pd.DataFrame, Any]]) -> None:
        self.status = "warming"
        try:
            from infra.store import get_store

            self.store = await asyncio.to_thread(get_store)
            integrations.ensure_worker()  # also resumes deliveries left pending by a previous process
        except Exception as error:  # the console runs without persistence rather than not at all
            self.store_error = f"{type(error).__name__}: {error}"[:300]
        try:
            data = await asyncio.to_thread(load_rail_dataset, load)
            self.threshold = await asyncio.to_thread(choose_threshold, data)
            th = self.threshold["threshold"]
            self.evaluation = await asyncio.to_thread(evaluate, data, th)
            self.scorer = await asyncio.to_thread(make_live_scorer, data)
            self.engine = await asyncio.to_thread(
                lambda: RailEngine(data, None, True, self.store, self.mode, auto_hold=infra_settings.RAIL_AUTO_HOLD, model_threshold=th)
            )
            self.status = "ready"
        except Exception as error:
            self.status = "error"
            self.error = f"{type(error).__name__}: {error}"
            return
        loop = asyncio.get_running_loop()

        def push(payments: list[dict[str, Any]], ack: Callable[[], None] | None = None) -> None:  # called from consumer threads too
            loop.call_soon_threadsafe(self.inbox.put_nowait, (self.source.backend, payments, ack))

        if self.mode in ("kafka", "kinesis"):
            asyncio.create_task(self.source.start(push, self.backlog))
        else:
            await self.source.start(push, self.backlog)
        asyncio.create_task(self._loop())

    def backlog(self) -> int:
        """Payments waiting in the inbox (consumers pause above ingest.HIGH_WATER)."""
        return sum(len(item[1]) for item in list(self.inbox._queue))  # type: ignore[attr-defined]

    def _drain_inbox(self) -> tuple[list[tuple[str, dict[str, Any]]], list[Callable[[], None]]]:
        """Up to MAX_BATCH payments, and the acks of the batches this tick finishes. A batch
        split across ticks is acked with its last part."""
        items: list[tuple[str, dict[str, Any]]] = []
        acks: list[Callable[[], None]] = []
        while len(items) < MAX_BATCH and not self.inbox.empty():
            source, payments, ack = self.inbox.get_nowait()
            room = MAX_BATCH - len(items)
            items.extend((source, p) for p in payments[:room])
            if len(payments) > room:  # put the rest back at the front of the next tick
                self.inbox._queue.appendleft((source, payments[room:], ack))  # type: ignore[attr-defined]
            elif ack:
                acks.append(ack)
        return items, acks

    def _feed_scorer(self, rows: list[Row]) -> None:
        """Replayed rows join the scorer's graph (already scored offline), so a payment that
        arrives mid-replay is scored with the same context."""
        if not self.scorer or not rows:
            return
        import numpy as np
        from infra import scorer as online

        engine = self.engine
        feats = online.edge_features(
            self.scorer.feature_names,
            seconds_of_day=np.array([(r.t % 86400) + 10 for r in rows]),
            amount=np.array([r.amount for r in rows]),
            p2m=np.array([1.0 if r.channel == "P2M" else 0.0 for r in rows]),
            timestamp=np.array([r.t - engine.data.start_t for r in rows]),
        )
        self.scorer.add([r.from_id for r in rows], [r.to_id for r in rows], np.array([r.t for r in rows]), feats)

    def _score_online(self, payments: list[dict[str, Any]]) -> list[float | None]:
        import numpy as np
        from infra import scorer as online

        engine = self.engine
        if not engine.live:  # replay mode: the payment joins at the replay clock
            payments = [{**p, "timestamp": datetime.fromtimestamp(engine.sim_t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")} for p in payments]
        epoch, feats = online.payment_features(self.scorer.feature_names, payments)
        src = [p.get("payer_account_id") or engine.account_for(p["payer_vpa"]) or p["payer_vpa"] for p in payments]
        dst = [p.get("payee_account_id") or engine.account_for(p["payee_vpa"]) or p["payee_vpa"] for p in payments]
        batch = self.scorer.ingest(src, dst, epoch, feats)
        self.scorer_stats.update(batches=self.scorer_stats["batches"] + 1, lastMs=round(batch.ms, 2), lastSubgraphEdges=batch.subgraph_edges)
        return [float(x) for x in batch.probs]

    async def _score(self, payments: list[dict[str, Any]]) -> list[float | None]:
        """v2: incremental 2-hop scoring of just this batch (infra/scorer.py). v1: one /predict
        splice onto the full background graph."""
        if self.scorer:
            started = time.perf_counter()
            try:
                out = self._score_online(payments)
                self.ingest_stats["scored"] += len(payments)
                self.ingest_stats["lastScoreMs"] = round((time.perf_counter() - started) * 1000, 1)
                return out
            except Exception as error:
                self.ingest_stats["scoreErrors"] += len(payments)
                self.ingest_stats["lastScoreError"] = f"{type(error).__name__}: {error}"[:300]
                return [None] * len(payments)
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
            self._feed_scorer(replay_rows)
            items, acks = self._drain_inbox()
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
            for ack in acks:  # the engine has these now: let the consumers commit / checkpoint
                ack()
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
                "inboxDepth": self.backlog(),
                "highWater": HIGH_WATER,
                "deadLetters": self.store.dead_letters_recent(8) if self.store else [],
                **self.ingest_stats,
                "ingestedThisRun": eng.live_count if eng else 0,
                "duplicatesDropped": eng.duplicates if eng else 0,
            },
            "graph": {**(eng.graph.describe() if eng else {}), "fallbackReason": eng.graph_error if eng else None},
            "scoring": {"mode": "incremental 2-hop subgraph (infra/scorer.py)" if self.scorer.mode == "exact" else "cached layer-1 embeddings + fresh 1-hop (infra/scorer.py)", **self.scorer.describe(), **self.scorer_stats,
                        "threshold": self.threshold} if self.scorer else {"mode": "full-graph /predict splice (v1)"},
            "store": {**(self.store.describe() if self.store else {"backend": None}), "error": self.store_error, **(self.store.counts() if self.store else {})},
            "integrations": integrations.describe() if self.store else {"error": self.store_error},
            "runId": eng.run_id if eng else None,
            "registry": self._registry_status(),
        }

    def _registry_status(self) -> dict[str, Any]:
        try:
            from infra.registry import get_registry

            st = get_registry().status()
            return {k: st[k] for k in ("companies", "directors", "directorships", "disqualifiedDirectors", "linkedAccounts", "provider")}
        except Exception as error:
            return {"error": f"{type(error).__name__}: {error}"[:300]}

    def rescore_legs(self, legs: list[dict[str, Any]]) -> dict[str, Any]:
        """v2 investigation: score the alert's transfers again as new edges on the current graph
        (everything seen so far), next to the time-respecting score each got when it arrived."""
        payments = [{"payer_vpa": leg["sender"], "payee_vpa": leg["receiver"], "amount_inr": leg["amount_inr"], "timestamp": leg["timestamp"][:19]} for leg in legs]
        import numpy as np
        from infra import scorer as online

        engine = self.engine
        epoch, feats = online.payment_features(self.scorer.feature_names, payments)
        src = [engine.account_for(p["payer_vpa"]) or p["payer_vpa"] for p in payments]
        dst = [engine.account_for(p["payee_vpa"]) or p["payee_vpa"] for p in payments]
        probe = online.OnlineScorer(self.scorer.model, {"edge_features": self.scorer.feature_names, "edge_attr_mean": self.scorer.mean.tolist(), "edge_attr_std": self.scorer.std.tolist()}, math.inf)
        n = self.scorer.n  # a throwaway copy of the graph, so the probe edges do not stay in it
        probe.node_of = dict(self.scorer.node_of)
        probe.in_edges = [list(x) for x in self.scorer.in_edges]
        probe.src, probe.dst, probe.t, probe.feat, probe.n = self.scorer.src[:n].copy(), self.scorer.dst[:n].copy(), self.scorer.t[:n].copy(), self.scorer.feat[:n].copy(), n
        probe.now = self.scorer.now
        batch = probe.score(probe.add(src, dst, epoch, feats))
        return {
            "legs": [{**leg, "fraud_probability": float(p)} for leg, p in zip(legs, batch.probs)],
            "nodes": [],
            "scoredWithBackgroundGraph": True,
            "linkedAccounts": sum(1 for a in src + dst if a in self.scorer.node_of),
            "normalized": True,
            "subgraphEdges": batch.subgraph_edges,
            "ms": round(batch.ms, 2),
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
            self.engine.speed = max(0.5, min(speed, 3600))
        if paused is not None:
            self.paused = paused
        return {"speed": self.engine.speed, "paused": self.paused, "metrics": self.engine.metrics()}


class DemoBody(BaseModel):
    stage: int = Field(ge=1, le=3)
    id: str | None = Field(default=None, pattern=r"^[0-9a-f]{6}$")


def demo_accounts(demo_id: str) -> dict[str, str]:
    """The test scam's cast; each VPA is also its account id."""
    cast = {f"victim{i}": f"{DEMO_PREFIX}victim{i}.{demo_id}@okdemo" for i in (1, 2, 3)}
    cast["mule"] = f"{DEMO_PREFIX}mule.{demo_id}@ybl"
    cast |= {f"layer2_{i}": f"{DEMO_PREFIX}l2-{i}.{demo_id}@ibl" for i in (1, 2, 3)}
    cast["cashout"] = f"{DEMO_PREFIX}cashout.{demo_id}@paytm"
    return cast


def demo_payments(demo_id: str, stage: int, arrived: list[float] | None = None) -> list[dict[str, Any]]:
    """Stage 1: three victims pay one new account just under the ₹1 lakh UPI cap. Stage 2: it
    forwards 90% of what arrived across three accounts. Stage 3: each of those that received
    money sends 95% of it on to one cash-out account. `arrived`: what reached each sender."""
    c = demo_accounts(demo_id)
    split = [0.34, 0.30, 0.26]
    if stage == 1:
        legs = [(i, c[f"victim{i + 1}"], c["mule"], amt) for i, amt in enumerate([99_000.0, 98_500.0, 99_999.0])]
    elif stage == 2:
        legs = [(i, c["mule"], c[f"layer2_{i + 1}"], round(sum(arrived or []) * f, 2)) for i, f in enumerate(split)]
    else:
        legs = [(i, c[f"layer2_{i + 1}"], c["cashout"], round(a * 0.95, 2)) for i, a in enumerate(arrived or [])]
    return [
        {"txn_id": f"{DEMO_PREFIX}{demo_id}.{stage}.{i}", "payer_vpa": a, "payee_vpa": b, "amount_inr": amt, "timestamp": None,
         "payer_state": None, "payee_state": None, "payer_account_id": a, "payee_account_id": b}
        for i, a, b, amt in legs
        if amt > 0
    ]


def demo_rows(eng: "RailEngine", demo: dict[str, Any]) -> dict[str, Row]:
    """The engine's own copies of a test scam's payments; blocked ones are only in `replayed`."""
    seen: dict[str, Row] = {}
    for r in reversed(eng.replayed):
        if len(seen) == len(demo["txns"]):
            break
        if r.txn_id in demo["txns"]:
            seen[r.txn_id] = r
    return seen


class ActionBody(BaseModel):
    action: str
    note: str = ""


class AppealBody(BaseModel):
    statement: str


class AppealDecisionBody(BaseModel):
    decision: str  # uphold | release
    note: str = ""


class ControlBody(BaseModel):
    speed: float | None = None
    restart: bool = False
    paused: bool | None = None


class OnboardingBody(BaseModel):
    vpas: list[str] = []
    cin: str | None = None  # company applicant: run the MCA registry checks too
    dins: list[str] = []  # directors the applicant declared
    register: bool = False  # record the VPAs against the CIN, so later applicants linked to it are checked against them


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
            who.require("override", "lifting a restriction or clearing a model-flagged alert")
        result = eng.act(alert_id, body.action, body.note, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.post("/alerts/{alert_id}/appeal")
    async def alert_appeal(alert_id: str, body: AppealBody, who: rbac.Principal = Who):
        """Record the account holder's appeal against a restriction (received by support)."""
        who.require("appeal_record", "recording an appeal")
        result = engine().appeal(alert_id, body.statement, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.post("/alerts/{alert_id}/appeal/decision")
    async def alert_appeal_decision(alert_id: str, body: AppealDecisionBody, who: rbac.Principal = Who):
        who.require("appeal_decide", "deciding an appeal")
        result = engine().decide_appeal(alert_id, body.decision, body.note, who.actor, who.role)
        if "error" in result:
            return JSONResponse(result, status_code=result.pop("status"))
        return result

    @router.get("/loadtest")
    async def loadtest_report() -> dict[str, Any]:
        """The latest load-test report (python -m infra.loadtest), if one has been run."""
        out = {}
        for name in ("loadtest", "loadtest_cached", "loadtest_http"):
            path = SCRIPT_DIR / "reports" / f"{name}.json"
            if path.exists():
                out[name] = json.loads(path.read_text(encoding="utf-8"))
        if not out:
            raise HTTPException(status_code=404, detail="no load-test report yet: python -m infra.loadtest engine")
        return out

    @router.post("/alerts/{alert_id}/investigate")
    async def investigate(alert_id: str, who: rbac.Principal = Who) -> dict[str, Any]:
        """Runs the agent tools an investigator would: score the chain live, check the registry."""
        who.require("investigate")
        eng = engine()
        if alert_id not in eng.alerts:
            raise HTTPException(status_code=404, detail="Alert not found")
        legs = eng.chain_legs(alert_id)
        started = time.perf_counter()
        scored = await asyncio.to_thread(service.rescore_legs, legs) if service.scorer else await asyncio.to_thread(predict_chain, legs)
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
        eng = engine()
        vpas = [v.strip() for v in body.vpas if v.strip()][:10]
        cin = (body.cin or "").strip()
        if not vpas and not cin:
            raise HTTPException(status_code=422, detail="give settlement VPAs, a CIN, or both")
        if vpas:
            result = await service.graph_call(eng.onboarding_check, vpas)
        else:
            result = {"decision": "approve", "reason": "No settlement VPAs given; registry checks only.", "results": [], "checkedAgainstRows": len(eng.replayed), "graph": eng.graph.backend}
        if cin:
            try:
                from infra.registry import get_registry, merge

                reg = await asyncio.to_thread(get_registry)
                report = await asyncio.to_thread(reg.report, cin, None, eng.account_status, [d for d in body.dins if d.strip()][:20])
                result = merge(result, report)
                if body.register and vpas:
                    result["registered"] = await asyncio.to_thread(reg.link_accounts, cin, vpas, f"onboarding:{who.actor}")
            except Exception as error:  # the transaction check still answers
                result["registryError"] = f"{type(error).__name__}: {error}"[:300]
        result["latencyMs"] = (time.perf_counter() - started) * 1000
        return result

    # ------------------------------------------------------------------ MCA registry

    async def _registry():
        try:
            from infra.registry import get_registry

            return await asyncio.to_thread(get_registry)
        except Exception as error:
            raise HTTPException(status_code=503, detail=f"registry unavailable: {type(error).__name__}: {error}"[:300])

    @router.get("/registry/status")
    async def registry_status() -> dict[str, Any]:
        reg = await _registry()
        return await asyncio.to_thread(reg.status)

    @router.get("/registry/company/{cin}")
    async def registry_company(cin: str) -> dict[str, Any]:
        """The full linkage report for one CIN, checked against the rail's current state."""
        reg = await _registry()
        return await asyncio.to_thread(reg.report, cin, None, engine().account_status)

    @router.get("/registry/director/{din}")
    async def registry_director(din: str) -> dict[str, Any]:
        reg = await _registry()
        out = await asyncio.to_thread(reg.director, din)
        if not out:
            raise HTTPException(status_code=404, detail=f"DIN {din} is not in the registry")
        return out

    @router.post("/registry/import")
    async def registry_import(request: Request, kind: str, source: str | None = None, who: rbac.Principal = Who) -> dict[str, Any]:
        """Load a CSV sent as the request body (text/csv): kind = companies | directorships | disqualified | accounts."""
        who.require("registry_import", "loading registry data")
        reg = await _registry()
        text = (await request.body()).decode("utf-8-sig", errors="replace")
        try:
            out = await asyncio.to_thread(reg.load, kind, text, source or f"upload:{kind}")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        eng = engine()
        eng._log("registry_import", who.actor, f"Loaded {out['loaded']} {kind} rows from {out['source']} ({out['skipped']} skipped).", role=who.role)
        return out

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
        depth = service.backlog()
        if depth + len(batch) > MAX_INBOX:
            return JSONResponse({"detail": "ingest backlog full, retry later", "queued": depth}, status_code=429, headers={"Retry-After": "2"})
        service.inbox.put_nowait(("webhook", [p.model_dump() for p in batch], None))
        service.ingest_stats["webhookAccepted"] += len(batch)
        return {
            "accepted": len(batch),
            "queued": depth + len(batch),
            "mode": service.mode,
            "clock": "replay clock" if not eng.live else "payment timestamp",
            "paused": service.paused,
        }

    # ------------------------------------------------------------------ test scam

    @router.post("/demo/scam")
    async def demo_scam(body: DemoBody) -> dict[str, Any]:
        """Send one stage of a test mule chain through the webhook path: the same queue, GNN
        scorer, detectors and router as any payment. Accounts are new and prefixed `test.`."""
        eng = engine()
        now = time.time()
        if body.id is None:
            if body.stage != 1:
                raise HTTPException(status_code=400, detail="start a new test scam at stage 1")
            if now - service.demo_last_start < DEMO_COOLDOWN:
                wait = math.ceil(DEMO_COOLDOWN - (now - service.demo_last_start))
                return JSONResponse({"detail": f"another test scam just started; try again in {wait}s"}, status_code=429, headers={"Retry-After": str(wait)})
            if len(service.demos) >= DEMO_MAX:
                raise HTTPException(status_code=429, detail="test-scam limit for this bridge process reached; restart the bridge")
            service.demo_last_start = now
            demo_id = uuid.uuid4().hex[:6]
            service.demos[demo_id] = {"stages": set(), "txns": {}, "payments": []}
        else:
            demo_id = body.id
            if demo_id not in service.demos:
                raise HTTPException(status_code=404, detail="unknown test scam")
        demo = service.demos[demo_id]
        if body.stage in demo["stages"]:
            raise HTTPException(status_code=409, detail=f"stage {body.stage} already sent")
        if body.stage > 1 and body.stage - 1 not in demo["stages"]:
            raise HTTPException(status_code=409, detail=f"send stage {body.stage - 1} first")
        arrived: list[float] | None = None
        if body.stage > 1:  # only money that reached the sender can move on, as with a real balance
            rows = demo_rows(eng, demo)
            prev = [p for p in demo["payments"] if demo["txns"][p["txn_id"]] == body.stage - 1]
            if any(p["txn_id"] not in rows for p in prev):
                raise HTTPException(status_code=409, detail=f"stage {body.stage - 1} is still in the queue")
            got = {int(p["txn_id"].rsplit(".", 1)[1]): p["amount_inr"] for p in prev if not rows[p["txn_id"]].blocked and not rows[p["txn_id"]].delayed}
            arrived = [sum(got.values())] if body.stage == 2 else [got.get(i, 0.0) for i in range(3)]
            if not sum(arrived):
                raise HTTPException(status_code=409, detail="nothing to send: no money got through the previous stage")
        payments = demo_payments(demo_id, body.stage, arrived)
        demo["stages"].add(body.stage)
        demo["payments"] += payments
        for p in payments:
            demo["txns"][p["txn_id"]] = body.stage
        service.inbox.put_nowait(("webhook", payments, None))
        service.ingest_stats["webhookAccepted"] += len(payments)
        return {"id": demo_id, "stage": body.stage, "accepted": len(payments), "paused": service.paused, "replayDone": eng.done}

    @router.get("/demo/scam/{demo_id}")
    async def demo_scam_status(demo_id: str) -> dict[str, Any]:
        eng = engine()
        demo = service.demos.get(demo_id)
        if demo is None:
            raise HTTPException(status_code=404, detail="unknown test scam")
        accounts = demo_accounts(demo_id)
        seen = demo_rows(eng, demo)
        payments = []
        for p in demo["payments"]:
            r = seen.get(p["txn_id"])
            payments.append({
                "txnId": p["txn_id"], "stage": demo["txns"][p["txn_id"]], "from": p["payer_vpa"], "to": p["payee_vpa"], "amount": p["amount_inr"],
                "status": "queued" if r is None else "blocked" if r.blocked else "delayed" if r.delayed else "settled",
                "gnn": None if r is None else round(r.gnn, 4),
            })
        alerts = [a.public() for acct in accounts.values() for a in eng._alerts_on(acct) if a.status != "superseded"]
        return {
            "id": demo_id,
            "stages": sorted(demo["stages"]),
            "payments": payments,
            "alerts": sorted(alerts, key=lambda a: a["createdT"]),
            "accounts": {name: {"id": acct, "level": eng._level(acct), "action": "frozen" if acct in eng.frozen else LEVELS.get(eng._level(acct), "alert_only")} for name, acct in accounts.items()},
            "threshold": eng.model_threshold,
            "paused": service.paused,
        }

    @router.get("/graph/network")
    async def network(limit: int = 40) -> dict[str, Any]:
        return engine().network(max(5, min(limit, 120)))

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


if __name__ == "__main__":
    import sys

    if "--save-training-metrics" not in sys.argv:
        sys.exit("usage: python rail_engine.py --save-training-metrics   (writes models/*.metrics.json from logs/logs.log)")
    metrics = _training_log()
    if not metrics.get("test"):
        sys.exit("logs/logs.log has no finished finetune run; train first")
    metrics.pop("source", None)
    TRAINING_METRICS.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"wrote {TRAINING_METRICS.relative_to(SCRIPT_DIR)}: test F1={metrics['test']['f1']}, {len(metrics['epochs'])} epochs")
