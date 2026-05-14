"""
Nolambur Synthetic UPI Fraud Data Generator
============================================
Generates a synthetic dataset modelled on the Nolambur Digital Arrest case:
- ₹5L–₹5.5L burst transfers to avoid low-value triggers
- Mannady-origin accounts targeting Haridwar / Rajasthan mule chains
- High in-degree → near-instant out-degree (Mule Pulse pattern)
- Fan-In (many victims → 1 mule) + Fan-Out (1 mule → many L2 accounts)

Output: nolambur_transactions.csv  — drop-in replacement for IBM AML fields
        nolambur_labels.csv        — ground truth node labels (mule / clean)
"""

import uuid
import random
import csv
import json
from datetime import datetime, timedelta

random.seed(42)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG — mirrors the Nolambur case stats
# ──────────────────────────────────────────────────────────────────────────────
NUM_VICTIMS          = 6          # victim accounts (Chennai / Nolambur)
NUM_L1_MULES         = 8          # Layer-1 mule accounts (Haridwar / Rajasthan)
NUM_L2_MULES         = 35         # Layer-2 cash-out accounts
NUM_CLEAN_ACCOUNTS   = 500        # benign accounts to balance the graph
NUM_CLEAN_TXN        = 4800       # benign transactions (keeps illicit ratio ~0.5%)

FRAUD_AMOUNT_MIN     = 500_000    # ₹5,00,000
FRAUD_AMOUNT_MAX     = 550_000    # ₹5,50,000
CLEAN_AMOUNT_MIN     = 500
CLEAN_AMOUNT_MAX     = 200_000

# States — Nolambur case geography
VICTIM_STATES        = ["Tamil Nadu"]
L1_STATES            = ["Uttarakhand", "Rajasthan"]          # Haridwar / Jaipur
L2_STATES            = ["Uttarakhand", "Rajasthan", "Delhi", "Haryana"]
CLEAN_STATES         = ["Tamil Nadu", "Karnataka", "Maharashtra",
                         "Telangana", "Kerala", "Gujarat", "West Bengal"]

# UPI handle suffixes
UPI_SUFFIXES         = ["@ybl", "@ibl", "@oksbi", "@okaxis", "@paytm",
                        "@upi", "@apl", "@axl", "@icici"]

# Mannady → Haridwar burst window (victim under video-call surveillance)
BURST_WINDOW_SECONDS = 180        # all L1 transfers within 3 minutes
CASHOUT_DELAY_MAX    = 90         # L1→L2 within 90 seconds (Golden Hour)

BASE_TIME = datetime(2024, 3, 15, 10, 30, 0)   # incident timestamp

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def make_vpa(state: str) -> str:
    prefix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))
    return prefix + random.choice(UPI_SUFFIXES)

def make_account(state: str, role: str) -> dict:
    return {
        "id":    str(uuid.uuid4())[:12],
        "vpa":   make_vpa(state),
        "state": state,
        "role":  role,          # victim | l1_mule | l2_mule | clean
        "bank":  random.choice(["SBI","HDFC","ICICI","Axis","Kotak","PNB","BOB"])
    }

def make_txn(src: dict, dst: dict, amount: int,
             ts: datetime, upi_ref: str, is_fraud: bool) -> dict:
    return {
        "txn_id":     str(uuid.uuid4())[:16],
        "upi_ref":    upi_ref,
        "sender_vpa": src["vpa"],
        "sender_id":  src["id"],
        "recv_vpa":   dst["vpa"],
        "recv_id":    dst["id"],
        "amount_inr": amount,
        "timestamp":  ts.isoformat(),
        "sender_state": src["state"],
        "recv_state":  dst["state"],
        "sender_bank": src["bank"],
        "recv_bank":   dst["bank"],
        "is_fraud":    int(is_fraud),
        "layer":       _layer(src["role"], dst["role"])
    }

def _layer(src_role, dst_role):
    if src_role == "victim"  and dst_role == "l1_mule": return "L0→L1"
    if src_role == "l1_mule" and dst_role == "l2_mule": return "L1→L2"
    return "clean"

# ──────────────────────────────────────────────────────────────────────────────
# BUILD ACCOUNTS
# ──────────────────────────────────────────────────────────────────────────────

victims  = [make_account(random.choice(VICTIM_STATES), "victim")
            for _ in range(NUM_VICTIMS)]
l1_mules = [make_account(random.choice(L1_STATES), "l1_mule")
            for _ in range(NUM_L1_MULES)]
l2_mules = [make_account(random.choice(L2_STATES), "l2_mule")
            for _ in range(NUM_L2_MULES)]
clean    = [make_account(random.choice(CLEAN_STATES), "clean")
            for _ in range(NUM_CLEAN_ACCOUNTS)]

all_accounts = victims + l1_mules + l2_mules + clean
print(f"Accounts   : {len(all_accounts):>6}  "
      f"(victims={NUM_VICTIMS}, L1={NUM_L1_MULES}, "
      f"L2={NUM_L2_MULES}, clean={NUM_CLEAN_ACCOUNTS})")

# ──────────────────────────────────────────────────────────────────────────────
# BUILD FRAUD TRANSACTIONS
# ──────────────────────────────────────────────────────────────────────────────

fraud_txns = []
ref_counter = 1000000

# Phase 1 — Fan-In: victims → L1 mules (₹5L–₹5.5L burst within 3 min)
# Each victim is kept on a video call; they transfer to 1–2 L1 mules
for victim in victims:
    targets = random.sample(l1_mules, k=random.randint(1, 2))
    for mule in targets:
        offset = timedelta(seconds=random.randint(0, BURST_WINDOW_SECONDS))
        amount = random.randint(FRAUD_AMOUNT_MIN, FRAUD_AMOUNT_MAX)
        ref    = f"UPI{ref_counter:010d}"
        ref_counter += 1
        fraud_txns.append(
            make_txn(victim, mule, amount, BASE_TIME + offset, ref, True)
        )

# Phase 2 — Fan-Out: L1 mules → L2 cash-out accounts (within 90 sec)
# Simulates the "Mule Pulse": high in-degree then instant out-degree
for mule in l1_mules:
    cashout_targets = random.sample(l2_mules, k=random.randint(2, 5))
    # Receive time = base + some burst offset (already done above)
    # Out time = receive time + 10–90 seconds (near-instant)
    out_offset = timedelta(
        seconds=BURST_WINDOW_SECONDS + random.randint(10, CASHOUT_DELAY_MAX)
    )
    for l2 in cashout_targets:
        # Split the received amount into sub-transfers
        amount = random.randint(80_000, 200_000)
        ref    = f"UPI{ref_counter:010d}"
        ref_counter += 1
        fraud_txns.append(
            make_txn(mule, l2, amount, BASE_TIME + out_offset, ref, True)
        )

print(f"Fraud txns : {len(fraud_txns):>6}  "
      f"(L0→L1 Fan-In + L1→L2 Fan-Out)")

# ──────────────────────────────────────────────────────────────────────────────
# BUILD CLEAN TRANSACTIONS (random graph noise)
# ──────────────────────────────────────────────────────────────────────────────

clean_txns = []
clean_pool = victims + clean   # victims also do legit txns

for _ in range(NUM_CLEAN_TXN):
    src, dst = random.sample(clean_pool, 2)
    amount   = random.randint(CLEAN_AMOUNT_MIN, CLEAN_AMOUNT_MAX)
    offset   = timedelta(
        hours=random.randint(0, 72),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59)
    )
    ref      = f"UPI{ref_counter:010d}"
    ref_counter += 1
    clean_txns.append(
        make_txn(src, dst, amount, BASE_TIME + offset, ref, False)
    )

print(f"Clean txns : {len(clean_txns):>6}")

all_txns = fraud_txns + clean_txns
random.shuffle(all_txns)

illicit_pct = len(fraud_txns) / len(all_txns) * 100
print(f"Total txns : {len(all_txns):>6}  (illicit {illicit_pct:.2f}%)")

# ──────────────────────────────────────────────────────────────────────────────
# WRITE OUTPUT FILES
# ──────────────────────────────────────────────────────────────────────────────

TXN_FIELDS = ["txn_id","upi_ref","sender_vpa","sender_id","recv_vpa","recv_id",
              "amount_inr","timestamp","sender_state","recv_state",
              "sender_bank","recv_bank","is_fraud","layer"]

with open("nolambur_transactions.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=TXN_FIELDS)
    w.writeheader()
    w.writerows(all_txns)

print("✓ nolambur_transactions.csv written")

# Node-level labels (for T-GNN node classification)
LABEL_FIELDS = ["account_id","vpa","state","bank","role","is_mule"]
mule_ids = {a["id"] for a in l1_mules + l2_mules}

with open("nolambur_labels.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
    w.writeheader()
    for acc in all_accounts:
        w.writerow({
            "account_id": acc["id"],
            "vpa":        acc["vpa"],
            "state":      acc["state"],
            "bank":       acc["bank"],
            "role":       acc["role"],
            "is_mule":    int(acc["id"] in mule_ids)
        })

print("✓ nolambur_labels.csv written")

# Quick stats for Neo4j ingestion
stats = {
    "total_accounts": len(all_accounts),
    "total_transactions": len(all_txns),
    "fraud_transactions": len(fraud_txns),
    "illicit_ratio_pct": round(illicit_pct, 4),
    "mule_accounts": len(l1_mules) + len(l2_mules),
    "victim_accounts": len(victims),
    "geo_mismatch": f"Victims: {VICTIM_STATES} → Mules: {L1_STATES + L2_STATES}"
}

with open("nolambur_stats.json", "w", encoding="utf-8") as f:
    json.dump(stats, f, indent=2)

print("✓ nolambur_stats.json written")
print("\nNext step:")
print("  python neo4j_ingest.py --csv nolambur_transactions.csv --labels nolambur_labels.csv")
