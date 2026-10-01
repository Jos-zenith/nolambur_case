"""Aggregator-side detection on P2M traffic: rules p1.0 (reports/P2M_DESIGN.md).

A replay of what a payment aggregator sees: onboarding records, P2M payments into its merchants,
its merchants' collect requests with their outcomes, and its own daily settlement batches (06:00,
for the previous day's payments). Nothing after settlement.

  D1 ticket anomaly    first-time payers paying above the category's p99 ticket, counted per 24 h
  D2 payer spread      first-time payers from many other states into a local-category merchant, 24 h
  D3 collect pattern   collect requests to payers who aren't customers, 24 h, mostly failing
  D4 shared settlement one settlement account behind merchants with different declared entities

D1-D3 hold the merchant's settlement for 24 h (72 h if D4 is also open); D4 alone opens a review.
Holds lift themselves: with nobody acting, held money settles in a later batch.

Parameters come from the train days only, with fraud merchants excluded by label (they are the
training labels), and are written to reports/p2m_params_p1.0.json before any judging draw is run.

    python -m infra.p2m calibrate --data data/p2m/s1/nolambur_p2m
    python -m infra.p2m evaluate  --data data/p2m/s2/nolambur_p2m [--label fresh]
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import statistics
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARAMS = ROOT / "reports" / "p2m_params_p1.0.json"
RULES = "p1.0"
TRAIN_DAYS, WARMUP_DAYS = 6, 3
TEST = (8, 10)
BATCH_HOUR = 6
HOLD_H, HOLD_D4_H = 24, 72
NEW_MERCHANT_DAYS = 30
LOCAL = {"kirana", "restaurant", "pharmacy", "fuel"}
REPORTED_UPI_RATE = 1_264_000 / 185.8e9  # FY 2024-25 incidents / transactions (reports/README.md 3.2)
DAY = 86400.0


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).timestamp()


class Data:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.merchants = pd.read_csv(folder / "merchants.csv", dtype={"chain": str}).fillna({"chain": "", "scenario": "", "campaign": ""})
        self.payments = pd.read_csv(folder / "payments.csv")
        self.collects = pd.read_csv(folder / "collects.csv")
        stats = json.loads((folder / "stats.json").read_text(encoding="utf-8"))
        self.start = datetime.fromisoformat(stats["start"]).timestamp()
        self.days = stats["days"]
        self.m = {r.merchant_id: r._asdict() for r in self.merchants.itertuples(index=False)}

    def day(self, t: float) -> int:
        return int((t - self.start) // DAY)


class Engine:
    """One replay. With params=None it only collects per merchant-day statistics (calibration)."""

    def __init__(self, data: Data, params: dict[str, Any] | None) -> None:
        self.d, self.p = data, params
        self.known: dict[str, set] = defaultdict(set)
        self.pays: dict[str, deque] = defaultdict(deque)  # (t, amount, first, payer_state)
        self.cols: dict[str, deque] = defaultdict(deque)  # (t, failed) for requests to non-customers
        self.own: dict[str, deque] = defaultdict(deque)  # (t, amount): the merchant's own tickets, 7 days
        self.alerts: list[dict[str, Any]] = []
        self.alerted: dict[str, set] = defaultdict(set)
        self.hold_until: dict[str, float] = {}
        self.hold_log: list[tuple[str, float, float]] = []
        self.unsettled: dict[str, list] = defaultdict(list)
        self.held_rows: set = set()  # payment indices held at some batch
        self.settled_at: dict[int, float] = {}
        self.onboarded: dict[str, float] = {}
        self.by_sa: dict[str, list] = defaultdict(list)
        self.daystats: dict[tuple, dict] = defaultdict(lambda: {"firstAbove": 0, "states": set(), "colNew": 0, "colFail": 0})
        self.batch_log: list[dict[str, Any]] = []  # one row per merchant per batch with money due: held or settled

    # ------------------------------------------------------------------ events

    def run(self) -> "Engine":
        d = self.d
        ev: list[tuple] = []
        for mid, m in d.m.items():
            ev.append((max(_ts(m["onboarded_at"]), d.start), 0, "onboard", mid))
        for i, r in enumerate(d.collects.itertuples(index=False)):
            ev.append((_ts(r.resolved_at), 1, "collect", i))
        for i, r in enumerate(d.payments.itertuples(index=False)):
            ev.append((_ts(r.timestamp), 2, "pay", i))
        for day in range(1, d.days + 1):
            ev.append((d.start + day * DAY + BATCH_HOUR * 3600, 3, "batch", day))
        ev.sort()
        cols = d.collects.to_dict("records")
        pays = d.payments.to_dict("records")
        for t, _, kind, x in ev:
            if kind == "onboard":
                self._onboard(x, t)
            elif kind == "collect":
                self._collect(cols[x], t)
            elif kind == "pay":
                self._pay(x, pays[x], t)
            else:
                self._batch(x, t)
        return self

    def _alert(self, mid: str, det: str, t: float, why: str) -> None:
        if det in self.alerted[mid]:
            return
        self.alerted[mid].add(det)
        self.alerts.append({"merchant": mid, "detector": det, "t": t, "why": why})
        if det != "D4":
            hours = HOLD_D4_H if "D4" in self.alerted[mid] else HOLD_H
            until = t + hours * 3600
            if until > self.hold_until.get(mid, 0):
                self.hold_until[mid] = until
                self.hold_log.append((mid, t, until))

    def _onboard(self, mid: str, t: float) -> None:
        m = self.d.m[mid]
        self.onboarded[mid] = _ts(m["onboarded_at"])
        sa = m["settlement_account"]
        others = [o for o in self.by_sa[sa] if self.d.m[o]["legal_entity"] != m["legal_entity"]]
        self.by_sa[sa].append(mid)
        if self.p is not None and others:
            for x in [mid, *others]:
                self._alert(x, "D4", t, f"settlement account {sa} is shared by {len(others) + 1} merchants with different declared entities")

    def _prune(self, q: deque, t: float, window: float) -> None:
        while q and q[0][0] < t - window:
            q.popleft()

    def _pay(self, i: int, r: dict, t: float) -> None:
        mid, payer, amt = r["merchant_id"], r["payer_id"], float(r["amount_inr"])
        m = self.d.m[mid]
        first = payer not in self.known[mid]
        self.known[mid].add(payer)
        self.unsettled[mid].append(i)
        q, own = self.pays[mid], self.own[mid]
        self._prune(q, t, DAY)
        self._prune(own, t, 7 * DAY)
        cat_p99 = (self.p or {}).get("catP99", {}).get(m["category"]) or _CAT_P99.get(m["category"], math.inf)
        bar = cat_p99
        established = t - self.onboarded.get(mid, t) >= NEW_MERCHANT_DAYS * DAY
        if established and len(own) >= 50:
            bar = max(bar, float(np.percentile([a for _, a in own], 99)))
        own.append((t, amt))
        q.append((t, amt, first, r["payer_state"], amt >= bar))
        stats = self.daystats[(mid, self.d.day(t))]
        if first and amt >= bar:
            stats["firstAbove"] += 1
        if first and r["payer_state"] != m["state"]:
            stats["states"].add(r["payer_state"])
        if self.p is None:
            return
        above = sum(1 for x in q if x[2] and x[4])
        if above >= self.p["d1Count"]:
            self._alert(mid, "D1", t, f"{above} first-time payers paid at or above ₹{bar:,.0f} (the category's p99) in 24 h")
        if m["category"] in LOCAL:
            states = {x[3] for x in q if x[2] and x[3] != m["state"]}
            if len(states) >= self.p["d2States"]:
                self._alert(mid, "D2", t, f"first-time payers from {len(states)} other states in 24 h, into a local {m['category']} merchant")

    def _collect(self, r: dict, t: float) -> None:
        mid, payer = r["merchant_id"], r["payer_id"]
        if int(r.get("known_payer", 0)) or payer in self.known[mid]:
            return
        failed = r["outcome"] != "approved"
        q = self.cols[mid]
        self._prune(q, t, DAY)
        q.append((t, failed))
        stats = self.daystats[(mid, self.d.day(t))]
        stats["colNew"] += 1
        stats["colFail"] += int(failed)
        if self.p is None:
            return
        n = len(q)
        fail = sum(1 for _, f in q if f) / n
        if n >= self.p["d3Requests"] and fail >= self.p["d3FailShare"]:
            self._alert(mid, "D3", t, f"{n} collect requests to non-customers in 24 h, {fail:.0%} declined or expired")

    def _batch(self, day: int, t: float) -> None:
        cutoff = self.d.start + day * DAY
        pays = self.d.payments
        for mid, rows in self.unsettled.items():
            due = [i for i in rows if _ts(pays.at[i, "timestamp"]) < cutoff]
            if not due:
                continue
            amount = float(sum(pays.at[i, "amount_inr"] for i in due))
            fraud = float(sum(pays.at[i, "amount_inr"] for i in due if pays.at[i, "is_fraud"]))
            held = self.hold_until.get(mid, 0) > t
            self.batch_log.append({"merchant": mid, "t": t, "payments": len(due), "amount": amount, "fraudAmount": fraud, "held": held,
                                   "holdUntil": self.hold_until.get(mid) if held else None})
            if held:
                self.held_rows.update(due)
                continue
            for i in due:
                self.settled_at[i] = t
            self.unsettled[mid] = [i for i in rows if i not in set(due)]


_CAT_P99: dict[str, float] = {}


# ---------------------------------------------------------------------- calibration


def calibrate(data: Data) -> dict[str, Any]:
    """Train days, clean merchants only. Tickets: p99 per category. Counts: the p99.9 of clean
    merchant-days (days 3-5, after the first-payer warm-up), and the detector fires above it."""
    clean = {mid for mid, m in data.m.items() if not m["is_fraud"]}
    p = data.payments
    tday = ((p["timestamp"].map(_ts) - data.start) // DAY).astype(int)
    train = p[(tday < TRAIN_DAYS) & p["merchant_id"].isin(clean)]
    cats = train["merchant_id"].map(lambda x: data.m[x]["category"])
    cat_p99 = {c: float(np.percentile(g, 99)) for c, g in train.groupby(cats)["amount_inr"]}
    _CAT_P99.clear()
    _CAT_P99.update(cat_p99)
    eng = Engine(data, None).run()
    rows = [(mid, day, s) for (mid, day), s in eng.daystats.items() if mid in clean and WARMUP_DAYS <= day < TRAIN_DAYS]
    first_above = [s["firstAbove"] for _, _, s in rows]
    local_states = [len(s["states"]) for mid, _, s in rows if data.m[mid]["category"] in LOCAL]
    col_new = [s["colNew"] for _, _, s in rows if s["colNew"]]
    fail = [s["colFail"] / s["colNew"] for _, _, s in rows if s["colNew"] >= 5]
    pct = lambda xs, q: float(np.percentile(xs, q)) if xs else 0.0  # noqa: E731
    params = {
        "rules": RULES,
        "catP99": cat_p99,
        "d1Count": max(2, int(math.floor(pct(first_above, 99.9))) + 1),
        "d2States": max(3, int(math.floor(pct(local_states, 99.9))) + 1),
        "d3Requests": max(5, int(math.floor(pct(col_new, 99.9))) + 1),
        "d3FailShare": min(0.95, round(pct(fail, 99.9) + 0.05, 3)),
        "basis": {
            "merchantDays": len(rows), "firstAboveMax": max(first_above, default=0), "localStatesMax": max(local_states, default=0),
            "collectMerchantDays": len(col_new), "collectNewP999": pct(col_new, 99.9), "collectFailP999": pct(fail, 99.9),
            "note": "train days 3-5 (after a 3-day first-payer warm-up), clean merchants only; each detector fires above the p99.9 of these merchant-days; "
                    "the fail-share bar is p99.9 + 0.05",
        },
    }
    return params


# ---------------------------------------------------------------------- evaluation


def evaluate(data: Data, params: dict[str, Any], label: str, eng: Engine | None = None) -> dict[str, Any]:
    _CAT_P99.clear()
    _CAT_P99.update(params["catP99"])
    eng = eng or Engine(data, params).run()
    s0 = data.start
    t0, t1 = s0 + TEST[0] * DAY, s0 + TEST[1] * DAY
    pays, cols = data.payments, data.collects
    pt = pays["timestamp"].map(_ts)
    ct = cols["requested_at"].map(_ts)
    in_test = (pt >= t0) & (pt < t1)
    fraud_m = {mid for mid, m in data.m.items() if m["is_fraud"]}
    active = set(pays.loc[in_test & (pays["is_fraud"] == 1), "merchant_id"]) | set(cols.loc[(ct >= t0) & (ct < t1) & (cols["is_fraud"] == 1), "merchant_id"])
    busy = set(pays.loc[in_test, "merchant_id"])
    first_alert: dict[str, float] = {}
    dets: dict[str, set] = defaultdict(set)
    for a in eng.alerts:
        if a["t"] < t1:
            first_alert[a["merchant"]] = min(first_alert.get(a["merchant"], math.inf), a["t"])
            dets[a["merchant"]].add(a["detector"])
    # counted in the test window: an alert raised there, or an open review (D4) on a merchant trading there
    counted = {m for m in first_alert if any(t0 <= a["t"] < t1 for a in eng.alerts if a["merchant"] == m) or ("D4" in dets[m] and m in busy)}
    tp_active = active & set(first_alert)
    fraud_counted = counted & fraud_m
    # money: fraud inflow on the test days held at a settlement batch before it settled
    fr = pays[in_test & (pays["is_fraud"] == 1)]
    held_fraud = sum(fr.loc[i, "amount_inr"] for i in fr.index if i in eng.held_rows)
    cl = pays[in_test & (pays["is_fraud"] == 0)]
    held_genuine = sum(cl.loc[i, "amount_inr"] for i in cl.index if i in eng.held_rows)
    # timing, per active fraud merchant
    first_fraud: dict[str, float] = {}
    for mid in active:
        ts = list(pt[in_test & (pays["is_fraud"] == 1) & (pays["merchant_id"] == mid)]) + list(ct[(ct >= t0) & (ct < t1) & (cols["is_fraud"] == 1) & (cols["merchant_id"] == mid)])
        first_fraud[mid] = min(ts)
    to_alert = [first_alert[m] - first_fraud[m] for m in active if m in first_alert]
    before_batch = 0
    for m in active:
        f = first_fraud[m]
        batch = s0 + (math.floor((f - s0) / DAY) + 1) * DAY + BATCH_HOUR * 3600  # the batch that would carry the first fraud payment
        before_batch += int(m in first_alert and first_alert[m] < batch)
    # cost on clean traffic, days 1-9: merchants whose first alert falls on those days
    clean_first = {m: t for m, t in first_alert.items() if m not in fraud_m}
    by_det_clean: dict[str, int] = defaultdict(int)
    for a in eng.alerts:
        if a["merchant"] not in fraud_m and a["t"] == clean_first.get(a["merchant"]):
            by_det_clean[a["detector"]] += 1
    d4_review = sum(1 for m, t in clean_first.items() if dets[m] == {"D4"})
    clean_days = [m for m, t in clean_first.items() if s0 + DAY <= t < t1 and dets[m] != {"D4"}]
    clean_hold_hours = 0.0  # merged per merchant: an extended hold is one interval, not two
    spans: dict[str, list] = defaultdict(list)
    for m, t, until in eng.hold_log:
        if m not in fraud_m:
            spans[m].append((max(t, s0 + DAY), min(until, t1)))
    for m, iv in spans.items():
        end = -math.inf
        for a, b in sorted(iv):
            a = max(a, end)
            if b > a:
                clean_hold_hours += (b - a) / 3600
            end = max(end, b)
    # secondary (added after the development run): the hold-capable detectors on their own
    hold_first: dict[str, float] = {}
    for a in eng.alerts:
        if a["detector"] != "D4" and a["t"] < t1:
            hold_first[a["merchant"]] = min(hold_first.get(a["merchant"], math.inf), a["t"])
    hold_counted = {m for m in hold_first if any(t0 <= a["t"] < t1 and a["detector"] != "D4" for a in eng.alerts if a["merchant"] == m)}
    to_hold_alert = [hold_first[m] - first_fraud[m] for m in active if m in hold_first]
    fp = len(counted - fraud_m)
    prevalence = float(fr["amount_inr"].count()) / float(in_test.sum())
    factor = prevalence / REPORTED_UPI_RATE
    return {
        "label": label, "rules": params["rules"], "folder": str(data.folder.relative_to(ROOT)) if data.folder.is_relative_to(ROOT) else str(data.folder),
        "recall": len(tp_active) / len(active) if active else None,
        "activeFraudMerchants": len(active), "activeFlagged": len(tp_active),
        "precision": len(fraud_counted) / len(counted) if counted else None,
        "merchantsCounted": len(counted), "fraudCounted": len(fraud_counted), "frontsFlagged": sum(1 for m in fraud_counted if data.m[m]["scenario"] == "S3-front"),
        "falseMerchants": fp,
        "fraudInflow": float(fr["amount_inr"].sum()), "fraudHeldBeforeSettlement": float(held_fraud),
        "fraudHeldShare": float(held_fraud / fr["amount_inr"].sum()) if len(fr) else None,
        "medianSecondsToAlert": statistics.median(to_alert) if to_alert else None,
        "flaggedBeforeFirstBatch": before_batch, "genuineHeld": float(held_genuine),
        "secondary": {
            "note": "added after the development run: D4 fires at onboarding, so it dominates timing and its reviews on family businesses dominate precision",
            "holdDetectorsRecall": sum(1 for m in active if m in hold_first) / len(active) if active else None,
            "holdDetectorsPrecision": len(hold_counted & fraud_m) / len(hold_counted) if hold_counted else None,
            "holdDetectorsCounted": len(hold_counted),
            "medianSecondsToHoldAlert": statistics.median(to_hold_alert) if to_hold_alert else None,
            "d4Only": {"fraudMerchantsCounted": sum(1 for m in counted & fraud_m if dets[m] == {"D4"}), "cleanMerchantsCounted": sum(1 for m in counted - fraud_m if dets[m] == {"D4"})},
        },
        "byMerchant": [{"merchant": m, "scenario": data.m[m]["scenario"], "category": data.m[m]["category"], "detectors": sorted(dets[m]),
                        "secondsToAlert": (first_alert[m] - first_fraud[m]) if m in first_alert else None} for m in sorted(active)],
        "cleanCost": {
            "window": "days 1-9", "falseMerchantsPerDay": len(clean_days) / (TEST[1] - 1), "byFirstDetector": dict(by_det_clean),
            "d4ReviewsOnCleanMerchants": d4_review, "cleanHoldMerchantHours": clean_hold_hours,
            "falsePerRealAtReportedRate": (fp / len(fraud_counted) * factor) if fraud_counted else None, "reportedFactor": factor,
        },
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["calibrate", "evaluate"])
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", type=Path, help="evaluate: write the result JSON here")
    args = ap.parse_args(argv)
    data = Data(args.data if args.data.is_absolute() else ROOT / args.data)
    if args.cmd == "calibrate":
        params = calibrate(data)
        PARAMS.write_text(json.dumps(params, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in params.items() if k != "catP99"}, indent=2))
        return
    params = json.loads(PARAMS.read_text(encoding="utf-8"))
    out = evaluate(data, params, args.label or args.data.parent.name)
    if args.out:
        args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "byMerchant"}, indent=2, default=str))
    for m in out["byMerchant"]:
        print(m)


if __name__ == "__main__":
    main()
