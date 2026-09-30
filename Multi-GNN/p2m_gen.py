"""Nolambur P2M: a payment aggregator's own traffic, with aggregator-side fraud (reports/P2M_DESIGN.md).

What the aggregator (PA) sees, and so all this writes:
  merchants.csv  onboarding records: category, declared legal entity, settlement account, onboarding time
  payments.csv   P2M payments into its merchants: payer, payer's home state, amount, initiation (qr / intent / collect)
  collects.csv   collect requests its merchants sent, with the outcome (approved / declined / expired)
Nothing after settlement is generated: the onward hops are outside the PA's view.

Clean world: people pay local shops (mostly in their own state; 5% of payments are made while
travelling, to a local merchant anywhere) and online merchants; billers and
subscriptions collect from their own customers; some online services collect from new sign-ups;
chains share one settlement account under one legal entity, and a few family businesses share one
across two entities (the honest false positive for S3). New legitimate merchants onboard during
the window too.

Fraud, ten campaigns (six train, two validation, two test, as in v2):
  S1  a new merchant takes scam victims' payments of ₹10k-₹1L (intent / QR), mostly from other states
  S2  a new merchant sends collect requests to hundreds of strangers; a few approve (₹2k-₹25k)
  S3  about half the campaigns run their merchants in a ring that shares one settlement account
      with dormant fronts, each front under a different declared legal entity
A campaign's merchants, victims and camouflage traffic draw from their own stream,
default_rng([SEED, campaign, stream]) for test campaigns and [SEED, campaign, 1] otherwise, and
camouflage starts on the campaign's own day: --stream changes the test days only.

    python p2m_gen.py [--stream 1] [--scale 1.0] [--out nolambur_p2m]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SEED = 11
DAYS = 10
BASE = datetime(2024, 3, 11)
CAMPAIGN_STARTS = [0.45, 1.40, 2.50, 3.35, 4.10, 4.65, 6.25, 6.80, 8.20, 8.75]

_cli = argparse.ArgumentParser(description="Nolambur P2M generator")
_cli.add_argument("--stream", type=int, default=1, help="random stream for the test-day campaigns: 1 = development draw, 2 = judging draw, 3 reserved")
_cli.add_argument("--scale", type=float, default=1.0, help="multiply S1 victim payments by this (the low-value sweep)")
_cli.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "nolambur_p2m")
ARGS = _cli.parse_args()

STATES = ["Tamil Nadu", "Karnataka", "Maharashtra", "Telangana", "Kerala", "Gujarat", "West Bengal", "Delhi", "Uttar Pradesh", "Rajasthan", "Haryana", "Bihar"]
HANDLES = ["@ybl", "@ibl", "@oksbi", "@okaxis", "@paytm", "@icici", "@axl"]
# category: (ticket median ₹, sigma, local?, share of merchants)
CATEGORIES = {
    "kirana": (250, 0.8, True, 0.26), "restaurant": (450, 0.7, True, 0.16), "pharmacy": (400, 0.8, True, 0.10),
    "fuel": (800, 0.5, True, 0.07), "electronics": (6_000, 0.9, False, 0.07), "online_services": (900, 0.9, False, 0.12),
    "utility_biller": (1_500, 0.6, False, 0.06), "subscription": (499, 0.4, False, 0.06), "travel": (4_500, 0.8, False, 0.05),
    "education": (8_000, 0.6, False, 0.05),
}
COLLECT_BILLERS = ("utility_biller", "subscription")
N_PEOPLE = 6000
N_MERCHANTS = 400
HOUR_W = np.array([1, 0.5, 0.3, 0.2, 0.2, 0.4, 1.2, 2.5, 4, 5, 5.5, 6, 6.5, 6, 5.5, 5.5, 6, 6.5, 7, 7.5, 7, 5.5, 3.5, 2], float)
HOUR_W /= HOUR_W.sum()

main_rng = np.random.default_rng(SEED)


def hexid(r: np.random.Generator, n: int = 12) -> str:
    return uuid.UUID(int=int(r.integers(0, 2**63)) << 64 | int(r.integers(0, 2**63))).hex[:n]


def vpa(r: np.random.Generator) -> str:
    return "".join(r.choice(list("abcdefghijklmnopqrstuvwxyz0123456789"), 8)) + str(r.choice(HANDLES))


def ticket(r: np.random.Generator, cat: str) -> int:
    med, sig, _, _ = CATEGORIES[cat]
    return int(max(10, min(200_000, r.lognormal(math.log(med), sig))))


def at_day(r: np.random.Generator, day: int) -> datetime:
    return BASE + timedelta(days=day, hours=int(r.choice(24, p=HOUR_W)), seconds=int(r.integers(0, 3600)))


merchants: list[dict] = []
payments: list[dict] = []
collects: list[dict] = []


def merchant(r: np.random.Generator, cat: str, state: str, onboarded: datetime, entity: str, settlement: str, *, fraud: int = 0, scenario: str = "", campaign: str = "", chain: str = "") -> dict:
    m = {"merchant_id": hexid(r), "vpa": vpa(r), "category": cat, "state": state, "legal_entity": entity, "settlement_account": settlement,
         "onboarded_at": onboarded.replace(microsecond=0).isoformat(), "chain": chain, "is_fraud": fraud, "scenario": scenario, "campaign": campaign}
    merchants.append(m)
    return m


def pay(r: np.random.Generator, payer: dict, m: dict, amount: float, ts: datetime, initiation: str, *, fraud: int = 0, campaign: str = "") -> None:
    if ts < BASE or ts >= BASE + timedelta(days=DAYS) or ts < datetime.fromisoformat(m["onboarded_at"]):
        return
    payments.append({"txn_id": hexid(r, 16), "payer_id": payer["id"], "payer_vpa": payer["vpa"], "payer_state": payer["state"], "merchant_id": m["merchant_id"],
                     "amount_inr": int(round(amount)), "timestamp": ts.replace(microsecond=0).isoformat(), "initiation": initiation, "is_fraud": fraud, "campaign": campaign})


def collect(r: np.random.Generator, payer: dict, m: dict, amount: float, ts: datetime, outcome: str, *, fraud: int = 0, campaign: str = "", known: int = 0) -> None:
    """known = the payer is already the merchant's customer (a biller's mandate or account), which the PA records."""
    if ts < BASE or ts >= BASE + timedelta(days=DAYS):
        return
    delay = {"approved": r.uniform(0.5, 20), "declined": r.uniform(0.2, 30), "expired": 30.0}[outcome]  # minutes
    resolved = ts + timedelta(minutes=float(delay))
    collects.append({"request_id": hexid(r, 16), "merchant_id": m["merchant_id"], "payer_id": payer["id"], "payer_state": payer["state"], "amount_inr": int(round(amount)),
                     "requested_at": ts.replace(microsecond=0).isoformat(), "resolved_at": resolved.replace(microsecond=0).isoformat(), "outcome": outcome, "known_payer": known,
                     "is_fraud": fraud, "campaign": campaign})
    if outcome == "approved":
        pay(r, payer, m, amount, resolved, "collect", fraud=fraud, campaign=campaign)


# ------------------------------------------------------------------ clean world

r = main_rng
people = [{"id": hexid(r), "vpa": vpa(r), "state": str(r.choice(STATES))} for _ in range(N_PEOPLE)]
cats = list(CATEGORIES)
shares = np.array([CATEGORIES[c][3] for c in cats])
shares /= shares.sum()
entity_n = [0]


def new_entity() -> str:
    entity_n[0] += 1
    return f"ENT{entity_n[0]:05d}"


def settlement_account() -> str:
    return "SA" + hexid(r, 10)


# chains: one entity, one settlement account, several outlets
for _ in range(6):
    cat = str(r.choice(["restaurant", "pharmacy", "kirana", "fuel"]))
    ent, sa, chain = new_entity(), settlement_account(), "CH" + hexid(r, 6)
    for _ in range(int(r.integers(3, 7))):
        merchant(r, cat, str(r.choice(STATES)), BASE - timedelta(days=float(r.uniform(90, 900))), ent, sa, chain=chain)
# family businesses: two entities, one settlement account (legitimate, and exactly what S3 looks like)
for _ in range(4):
    sa = settlement_account()
    st = str(r.choice(STATES))
    for _ in range(2):
        merchant(r, str(r.choice(["kirana", "restaurant", "pharmacy"])), st, BASE - timedelta(days=float(r.uniform(60, 900))), new_entity(), sa)
while len(merchants) < N_MERCHANTS:
    cat = str(r.choice(cats, p=shares))
    new = r.random() < 0.08  # onboarded in the last 30 days, or during the window
    onboarded = BASE + timedelta(days=float(r.uniform(-30, 8))) if new else BASE - timedelta(days=float(r.uniform(30, 900)))
    merchant(r, cat, str(r.choice(STATES)), onboarded, new_entity(), settlement_account())

clean_merchants = list(merchants)
local_by_state: dict[str, list[dict]] = {}
for m in clean_merchants:
    if CATEGORIES[m["category"]][2]:
        local_by_state.setdefault(m["state"], []).append(m)
online = [m for m in clean_merchants if not CATEGORIES[m["category"]][2] and m["category"] not in COLLECT_BILLERS]
billers = [m for m in clean_merchants if m["category"] in COLLECT_BILLERS]
local_any = [m for m in clean_merchants if CATEGORIES[m["category"]][2]]
signup_collectors = [m for m in online if m["category"] == "online_services"][:10]  # collect from new sign-ups
activity = r.lognormal(0, 0.7, N_PEOPLE)
activity /= activity.mean()
favourites = {}
for p in people:
    local = local_by_state.get(p["state"]) or clean_merchants
    favourites[p["id"]] = [local[i] for i in r.choice(len(local), min(len(local), int(r.integers(2, 6))), replace=False)]

for day in range(DAYS):
    for i, p in enumerate(people):
        for _ in range(r.poisson(0.9 * activity[i])):
            u = r.random()
            if u < 0.78:
                m = favourites[p["id"]][int(r.integers(0, len(favourites[p["id"]])))]
            elif u < 0.83:  # travelling: a local shop, fuel pump or restaurant anywhere
                m = local_any[int(r.integers(0, len(local_any)))]
            else:
                m = online[int(r.integers(0, len(online)))]
            pay(r, p, m, ticket(r, m["category"]), at_day(r, day), "qr" if CATEGORIES[m["category"]][2] and r.random() < 0.7 else "intent")
    for m in signup_collectors:  # sign-ups: collect requests to people new to the merchant
        for _ in range(r.poisson(8)):
            outcome = str(r.choice(["approved", "declined", "expired"], p=[0.65, 0.15, 0.20]))
            collect(r, people[int(r.integers(0, N_PEOPLE))], m, ticket(r, m["category"]), at_day(r, day), outcome)
# billers: each collects once in the window from each of its own customers
for m in billers:
    for ci in r.choice(N_PEOPLE, int(r.integers(30, 120)), replace=False):
        outcome = str(r.choice(["approved", "declined", "expired"], p=[0.88, 0.04, 0.08]))
        collect(r, people[ci], m, ticket(r, m["category"]), at_day(r, int(r.integers(0, DAYS))), outcome, known=1)

# ------------------------------------------------------------------ campaigns

campaign_rows = []
for c, start in enumerate(CAMPAIGN_STARTS, 1):
    cid = f"P{c:02d}"
    split = "train" if start < 6 else "val" if start < 8 else "test"
    cr = np.random.default_rng([SEED, c, ARGS.stream if split == "test" else 1])
    t0 = BASE + timedelta(days=start)
    day0 = int(start)
    ring = cr.random() < 0.5
    shared_sa = "SA" + hexid(cr, 10) if ring else None
    n_active = 1 if cr.random() < 0.6 else 2
    actives = []
    for k in range(n_active):
        scen = "S1" if cr.random() < 0.6 else "S2"
        if scen == "S1":
            cat = str(cr.choice(["kirana", "restaurant", "pharmacy"])) if cr.random() < 0.6 else str(cr.choice(["electronics", "online_services"]))
        else:
            cat = str(cr.choice(["online_services", "subscription", "utility_biller"]))
        onboarded = t0 - timedelta(days=float(cr.uniform(3, 40)))
        actives.append(merchant(cr, cat, str(cr.choice(STATES)), onboarded, "ENT-F" + hexid(cr, 6), shared_sa or ("SA" + hexid(cr, 10)),
                                fraud=1, scenario=scen + ("+S3" if ring else ""), campaign=cid))
    fronts = []
    if ring:
        for _ in range(int(cr.integers(1, 4))):
            fronts.append(merchant(cr, str(cr.choice(cats)), str(cr.choice(STATES)), t0 - timedelta(days=float(cr.uniform(3, 60))), "ENT-F" + hexid(cr, 6), shared_sa,
                                   fraud=1, scenario="S3-front", campaign=cid))
    # camouflage: ordinary small payments, from the campaign's own day on (keeps other days untouched)
    for m in actives + fronts:
        for d in range(day0, min(DAYS, day0 + 2)):
            for _ in range(cr.poisson(3)):
                pay(cr, people[int(cr.integers(0, N_PEOPLE))], m, ticket(cr, m["category"]), at_day(cr, d), "qr")
    n_s1 = n_s2 = 0
    for m in actives:
        if m["scenario"].startswith("S1"):
            m_state = m["state"]
            for _ in range(int(cr.integers(8, 26))):
                v = people[int(cr.integers(0, N_PEOPLE))]
                if v["state"] == m_state and cr.random() < 0.7:
                    continue  # most victims are elsewhere
                t = t0 + timedelta(minutes=float(cr.uniform(0, 36 * 60)))
                for _ in range(int(cr.integers(1, 5))):
                    amt = min(100_000, max(10_000, cr.lognormal(math.log(35_000), 0.6))) * ARGS.scale
                    pay(cr, v, m, amt, t, "intent" if cr.random() < 0.7 else "qr", fraud=1, campaign=cid)
                    n_s1 += 1
                    t += timedelta(minutes=float(cr.uniform(5, 180)))
        else:
            for _ in range(int(cr.integers(150, 601))):
                v = people[int(cr.integers(0, N_PEOPLE))]
                t = t0 + timedelta(minutes=float(cr.uniform(0, 30 * 60)))
                u = cr.random()
                approve = cr.uniform(0.03, 0.08)
                outcome = "approved" if u < approve else "declined" if u < approve + cr.uniform(0.55, 0.70) else "expired"
                collect(cr, v, m, min(25_000, max(2_000, cr.lognormal(math.log(8_000), 0.6))), t, outcome, fraud=1, campaign=cid)
                n_s2 += 1
    campaign_rows.append({"campaign": cid, "start": t0.isoformat(), "split": split, "ring": ring, "actives": [m["scenario"] + ":" + m["category"] for m in actives],
                          "fronts": len(fronts), "s1Payments": n_s1, "s2Requests": n_s2})

# ------------------------------------------------------------------ write

out: Path = ARGS.out
out.mkdir(parents=True, exist_ok=True)
payments.sort(key=lambda x: x["timestamp"])
collects.sort(key=lambda x: x["requested_at"])
for name, rows in (("merchants", merchants), ("payments", payments), ("collects", collects)):
    with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
stats = {
    "seed": SEED, "stream": ARGS.stream, "scale": ARGS.scale, "days": DAYS, "start": BASE.isoformat(),
    "merchants": len(merchants), "fraudMerchants": sum(m["is_fraud"] for m in merchants),
    "payments": len(payments), "fraudPayments": sum(p["is_fraud"] for p in payments),
    "collects": len(collects), "fraudCollects": sum(x["is_fraud"] for x in collects),
    "campaigns": campaign_rows,
}
(out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in stats.items() if k != "campaigns"}))
