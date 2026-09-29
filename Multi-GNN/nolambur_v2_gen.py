"""Nolambur v2: a synthetic UPI dataset that supports a real train-on-past / test-on-future split.

Why v1 (nolambur_synthetic_gen.py) could not:
  * all 353 fraud edges fall in one 4.5-minute window, and the file starts that same
    second, so any chronological split leaves a side with no fraud or no clean traffic;
  * victims send ₹5-5.5 lakh per transfer, above the ₹1 lakh UPI P2P cap, and no clean
    transfer exceeds ₹2 lakh, so amount alone separates the first hop;
  * mule accounts appear only in fraud edges, so "has any edge to a mule" is the label.

v2, over 10 days:
  * ten campaigns, scheduled so the standard day-based 60/20/20 split (data_loading.py)
    puts six in train (days 0-5), two in validation (6-7) and two in test (8-9);
  * every P2P transfer is <= ₹1,00,000 and a victim sends at most ₹1 lakh per day
    (NPCI P2P limits), so victims pay over several days, often just under the cap;
  * mules also make ordinary purchases and transfers (labelled clean), before and after;
  * legitimate look-alikes: merchants with heavy fan-in, small businesses that pass most
    of their takings on to suppliers the same day, landlords, employers;
  * mules forward on varied schedules: some within minutes, some after hours;
  * some mule accounts are reused by a later campaign, as they are in practice.
Campaign parameters are drawn from one distribution for all ten; the test campaigns are
not made harder on purpose.

Outputs, in nolambur_v2/:
  transactions.csv   same columns as v1, plus channel (P2P / P2M) and campaign
  labels.csv         one row per account: role (victim / l1_mule / l2_mule / clean) and kind
  stats.json         counts, and which campaign falls in which split

    python nolambur_v2_gen.py && python prepare_datasets.py --nolambur-only --dataset v2
"""

from __future__ import annotations

import csv
import json
import math
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SEED = 7
DAYS = 10
BASE = datetime(2024, 3, 11, 0, 0, 0)
OUT = Path(__file__).resolve().parent / "nolambur_v2"

P2P_CAP = 100_000  # NPCI per-transaction limit for P2P
VICTIM_DAILY_CAP = 100_000  # typical per-account daily P2P limit

N_PEOPLE = 5200
N_MERCHANTS = 220
N_BUSINESSES = 70
N_SUPPLIERS = 45

# start (day + fraction) of each campaign; spans stay inside their split
CAMPAIGN_STARTS = [0.42, 1.38, 2.55, 3.40, 4.05, 4.62, 6.20, 6.75, 8.15, 8.70]
MAX_SPAN_HOURS = 26

STATES = ["Tamil Nadu", "Karnataka", "Maharashtra", "Telangana", "Kerala", "Gujarat", "West Bengal", "Delhi", "Uttar Pradesh", "Rajasthan", "Uttarakhand", "Haryana", "Bihar"]
MULE_STATES = ["Uttarakhand", "Rajasthan", "Delhi", "Haryana", "Bihar", "Jharkhand", "West Bengal"]
HANDLES = ["@ybl", "@ibl", "@oksbi", "@okaxis", "@paytm", "@upi", "@apl", "@axl", "@icici"]
BANKS = ["SBI", "HDFC", "ICICI", "Axis", "Kotak", "PNB", "BOB", "Canara", "Union"]

rng = np.random.default_rng(SEED)
HOUR_WEIGHTS = np.array([1, 0.5, 0.3, 0.2, 0.2, 0.4, 1.2, 2.5, 4, 5, 5.5, 6, 6.5, 6, 5.5, 5.5, 6, 6.5, 7, 7.5, 7, 5.5, 3.5, 2], dtype=float)
HOUR_WEIGHTS /= HOUR_WEIGHTS.sum()


def account(role: str, kind: str, state: str | None = None) -> dict:
    return {
        "id": uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | int(rng.integers(0, 2**63))).hex[:12],
        "vpa": "".join(rng.choice(list("abcdefghijklmnopqrstuvwxyz0123456789"), 8)) + str(rng.choice(HANDLES)),
        "state": state or str(rng.choice(STATES)),
        "bank": str(rng.choice(BANKS)),
        "role": role,
        "kind": kind,
    }


def at(day: float, hour_spread: bool = True) -> datetime:
    """A time on `day` (integer part); if hour_spread, the hour follows the diurnal curve."""
    d = int(day)
    if hour_spread:
        h = int(rng.choice(24, p=HOUR_WEIGHTS))
        return BASE + timedelta(days=d, hours=h, seconds=int(rng.integers(0, 3600)))
    return BASE + timedelta(days=day)


def lognormal(median: float, sigma: float, lo: float, hi: float) -> int:
    return int(min(hi, max(lo, rng.lognormal(math.log(median), sigma))))


txns: list[dict] = []
ref = [5_000_000]


def pay(src: dict, dst: dict, amount: float, ts: datetime, channel: str, fraud: bool = False, layer: str = "clean", campaign: str = "") -> None:
    if channel == "P2P":
        assert amount <= P2P_CAP, amount
    if ts >= BASE + timedelta(days=DAYS) or ts < BASE:
        return
    ref[0] += 1
    txns.append({
        "txn_id": uuid.UUID(int=int(rng.integers(0, 2**63))).hex[-16:],
        "upi_ref": f"UPI{ref[0]:010d}",
        "sender_vpa": src["vpa"], "sender_id": src["id"],
        "recv_vpa": dst["vpa"], "recv_id": dst["id"],
        "amount_inr": int(round(amount)),
        "timestamp": ts.replace(microsecond=0).isoformat(),
        "sender_state": src["state"], "recv_state": dst["state"],
        "sender_bank": src["bank"], "recv_bank": dst["bank"],
        "is_fraud": int(fraud), "layer": layer, "channel": channel, "campaign": campaign,
    })


# ------------------------------------------------------------------ population

people = [account("clean", "individual") for _ in range(N_PEOPLE)]
merchants = [account("clean", "merchant") for _ in range(N_MERCHANTS)]
businesses = [account("clean", "business") for _ in range(N_BUSINESSES)]
suppliers = [account("clean", "supplier") for _ in range(N_SUPPLIERS)]
landlords = rng.choice(len(people), 120, replace=False)

contacts = {p["id"]: [people[i] for i in rng.choice(N_PEOPLE, int(rng.integers(3, 9)), replace=False)] for p in people}
activity = rng.lognormal(0, 0.8, N_PEOPLE)  # heavy-tailed: some people transact a lot
activity /= activity.mean()
favourite_merchants = {p["id"]: [merchants[i] for i in rng.choice(N_MERCHANTS, int(rng.integers(2, 6)), replace=False)] for p in people}

# ------------------------------------------------------------------ clean traffic


def everyday(person: dict, day: int, rate: float) -> None:
    for _ in range(rng.poisson(0.55 * rate)):  # P2P to friends and family
        pay(person, contacts[person["id"]][int(rng.integers(0, len(contacts[person["id"]])))], lognormal(1200, 1.1, 10, P2P_CAP), at(day), "P2P")
    for _ in range(rng.poisson(0.75 * rate)):  # purchases
        shop = favourite_merchants[person["id"]][int(rng.integers(0, len(favourite_merchants[person["id"]])))] if rng.random() < 0.8 else merchants[int(rng.integers(0, N_MERCHANTS))]
        pay(person, shop, lognormal(320, 1.0, 5, 60_000), at(day), "P2M")


for day in range(DAYS):
    for i, p in enumerate(people):
        everyday(p, day, activity[i])
    # small businesses: takings from customers, most of it paid on to suppliers the same day
    for b in businesses:
        takings = 0
        for _ in range(rng.poisson(18)):
            amt = lognormal(900, 0.9, 20, 50_000)
            takings += amt
            pay(people[int(rng.integers(0, N_PEOPLE))], b, amt, at(day), "P2M")
        paid, target = 0, takings * rng.uniform(0.6, 0.95)
        while paid < target and target > 5000:
            amt = min(P2P_CAP, lognormal(25_000, 0.7, 2_000, P2P_CAP), target - paid + 1)
            paid += amt
            pay(b, suppliers[int(rng.integers(0, N_SUPPLIERS))], amt, BASE + timedelta(days=day, hours=float(rng.uniform(17, 22))), "P2P")
    # rent and wages once in the ten days
    if day == 1:
        for li in landlords:
            for tenant in rng.choice(N_PEOPLE, int(rng.integers(1, 4)), replace=False):
                pay(people[tenant], people[li], lognormal(14_000, 0.5, 4_000, 60_000), at(day), "P2P")
    if day == 5:
        for b in businesses:
            for staff in rng.choice(N_PEOPLE, int(rng.integers(2, 7)), replace=False):
                pay(b, people[staff], lognormal(18_000, 0.4, 8_000, 60_000), at(day), "P2P")

# ------------------------------------------------------------------ campaigns

mules_l1: list[dict] = []
mules_l2: list[dict] = []
victims: list[dict] = []
campaign_rows: list[dict] = []
victim_ids: set[str] = set()


def camouflage(mule: dict, start: float) -> None:
    """Ordinary-looking activity around the campaign, labelled clean."""
    for _ in range(int(rng.integers(3, 14))):
        day = min(DAYS - 1, max(0, int(start + rng.uniform(-3, 3))))
        if rng.random() < 0.6:
            pay(mule, merchants[int(rng.integers(0, N_MERCHANTS))], lognormal(400, 1.0, 10, 20_000), at(day), "P2M")
        else:
            other = people[int(rng.integers(0, N_PEOPLE))]
            if rng.random() < 0.5:
                pay(mule, other, lognormal(900, 1.0, 50, 30_000), at(day), "P2P")
            else:
                pay(other, mule, lognormal(900, 1.0, 50, 30_000), at(day), "P2P")


for c, start in enumerate(CAMPAIGN_STARTS, 1):
    cid = f"C{c:02d}"
    t0 = BASE + timedelta(days=start)
    span = timedelta(hours=MAX_SPAN_HOURS)
    reuse = [m for m in mules_l2 if rng.random() < 0.08]  # accounts from earlier networks come back
    l1 = [account("l1_mule", "individual", str(rng.choice(MULE_STATES))) for _ in range(int(rng.integers(2, 6)))]
    l2 = [account("l2_mule", "individual", str(rng.choice(MULE_STATES))) for _ in range(int(rng.integers(6, 16)))] + reuse[:4]
    for m in l1 + [x for x in l2 if x not in mules_l2]:
        camouflage(m, start)
    mules_l1 += l1
    mules_l2 += [x for x in l2 if x not in mules_l2]

    # victims are ordinary people with their own history
    pool = [p for p in people if p["id"] not in victim_ids]
    vs = [pool[i] for i in rng.choice(len(pool), int(rng.integers(3, 9)), replace=False)]
    victim_ids |= {v["id"] for v in vs}
    victims += vs

    inbound: dict[str, list[tuple[datetime, float]]] = {m["id"]: [] for m in l1}
    for v in vs:
        days_paying = int(rng.integers(1, 3))
        t = t0 + timedelta(minutes=float(rng.uniform(0, 90)))
        for d in range(days_paying):
            day_total, budget = 0.0, VICTIM_DAILY_CAP
            for _ in range(int(rng.integers(1, 4))):
                if budget < 5_000:
                    break
                style = rng.random()
                if style < 0.45:
                    amt = budget if budget <= P2P_CAP else P2P_CAP - int(rng.integers(1, 2_000))  # up to the cap
                    amt = min(amt, budget)
                elif style < 0.75:
                    amt = min(budget, float(rng.choice([49_999, 50_000, 25_000, 99_000, 95_000])))
                else:
                    amt = min(budget, lognormal(40_000, 0.5, 5_000, P2P_CAP))
                mule = l1[int(rng.integers(0, len(l1)))]
                pay(v, mule, amt, t, "P2P", True, "L0→L1", cid)
                inbound[mule["id"]].append((t, amt))
                budget -= amt
                day_total += amt
                t += timedelta(minutes=float(rng.uniform(4, 45)))
            t = t0 + timedelta(days=d + 1, minutes=float(rng.uniform(0, 240)))

    # L1: forward most of each receipt, on its own schedule
    for m in l1:
        patient = rng.random() < 0.35  # waits hours rather than minutes
        for t_in, amt_in in inbound[m["id"]]:
            delay = rng.lognormal(math.log(150 if patient else 8), 0.6)  # minutes
            t_out = t_in + timedelta(minutes=float(delay))
            remaining = amt_in * rng.uniform(0.75, 0.97)
            while remaining > 3_000:
                amt = min(remaining, lognormal(30_000, 0.6, 5_000, P2P_CAP))
                dst = l2[int(rng.integers(0, len(l2)))]
                pay(m, dst, amt, t_out, "P2P", True, "L1→L2", cid)
                remaining -= amt
                t_out += timedelta(minutes=float(rng.uniform(0.5, 6)))
    # L2: some forward again, a few hours later, to other accounts in the network
    received: dict[str, float] = {}
    for tx in txns:
        if tx["campaign"] == cid and tx["layer"] == "L1→L2":
            received[tx["recv_id"]] = received.get(tx["recv_id"], 0.0) + tx["amount_inr"]
    for m in l2:
        if m["id"] in received and rng.random() < 0.45 and len(l2) > 1:
            t_out = t0 + timedelta(hours=float(rng.uniform(2, MAX_SPAN_HOURS - 2)))
            remaining = received[m["id"]] * rng.uniform(0.5, 0.9)
            while remaining > 3_000:
                amt = min(remaining, lognormal(20_000, 0.6, 3_000, P2P_CAP))
                dst = l2[int(rng.integers(0, len(l2)))]
                if dst["id"] != m["id"]:
                    pay(m, dst, amt, t_out, "P2P", True, "L2→L2", cid)
                remaining -= amt
                t_out += timedelta(minutes=float(rng.uniform(1, 20)))
    split = "train" if start < 6 else "val" if start < 8 else "test"
    campaign_rows.append({"campaign": cid, "start": t0.isoformat(), "split": split, "victims": len(vs), "l1": len(l1), "l2": len(l2), "reusedL2": len(reuse[:4])})

# ------------------------------------------------------------------ write

txns.sort(key=lambda r: r["timestamp"])
OUT.mkdir(exist_ok=True)
fields = ["txn_id", "upi_ref", "sender_vpa", "sender_id", "recv_vpa", "recv_id", "amount_inr", "timestamp", "sender_state", "recv_state", "sender_bank", "recv_bank", "is_fraud", "layer", "channel", "campaign"]
with open(OUT / "transactions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(txns)

accounts = {a["id"]: a for a in people + merchants + businesses + suppliers + mules_l1 + mules_l2}
for v in victims:
    accounts[v["id"]] = {**v, "role": "victim"}
with open(OUT / "labels.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["account_id", "vpa", "state", "bank", "role", "kind", "is_mule"])
    w.writeheader()
    for a in accounts.values():
        w.writerow({"account_id": a["id"], "vpa": a["vpa"], "state": a["state"], "bank": a["bank"], "role": a["role"], "kind": a["kind"], "is_mule": int(a["role"] in ("l1_mule", "l2_mule"))})

fraud = [t for t in txns if t["is_fraud"]]
stats = {
    "version": "v2",
    "seed": SEED,
    "days": DAYS,
    "start": BASE.isoformat(),
    "transactions": len(txns),
    "fraudTransactions": len(fraud),
    "illicitPct": round(100 * len(fraud) / len(txns), 3),
    "accounts": len(accounts),
    "victims": len(victims),
    "l1Mules": len(mules_l1),
    "l2Mules": len(mules_l2),
    "maxP2P": max(t["amount_inr"] for t in txns if t["channel"] == "P2P"),
    "fraudByLayer": {k: sum(1 for t in fraud if t["layer"] == k) for k in ("L0→L1", "L1→L2", "L2→L2")},
    "campaigns": campaign_rows,
}
(OUT / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: v for k, v in stats.items() if k != "campaigns"}, ensure_ascii=False))
for c in campaign_rows:
    print(c)
