"""Read-only access to the Nolambur synthetic dataset.

`nolambur_transactions.csv` (edge-level, with `is_fraud`) and
`nolambur_labels.csv` (node-level, with `role` / `is_mule`) are the same files
the model trained on. These helpers resolve a VPA or account id to its dataset
identity and summarise its behaviour - the raw material the "investigator" role
works from. In production these lookups would hit a KYC/AML system instead.

The one piece that must stay in lock-step with training is `encode_timestamp`:
`prepare_datasets.convert_nolambur` encodes every edge timestamp as
`seconds_since(midnight of the first row's date) + 10`, and the checkpoint's
z-normalisation stats were fit on that scale.
"""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from datetime import datetime

from .config import LABELS_CSV, TRANSACTIONS_CSV

_TS_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M")

# prepare_datasets.convert_nolambur adds a fixed +10s to every encoded timestamp.
_TIMESTAMP_OFFSET = 10


def parse_timestamp(value: str) -> datetime:
    value = (value or "").strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp: {value!r}")


@dataclass(frozen=True)
class Account:
    """A party in a transaction, resolved against the Nolambur dataset."""

    account_id: str          # dataset uuid; "" when the handle is unknown
    vpa: str
    state: str
    bank: str
    role: str                # victim | l1_mule | l2_mule | clean | unknown
    is_mule: bool             # synthetic ground-truth label
    in_graph: bool            # transacts in the dataset -> can splice onto the background graph


@functools.lru_cache(maxsize=1)
def _data() -> dict:
    with open(TRANSACTIONS_CSV, newline="", encoding="utf-8") as handle:
        txns = list(csv.DictReader(handle))
    if not txns:
        raise RuntimeError(f"{TRANSACTIONS_CSV} is empty")

    labels_by_id: dict[str, dict] = {}
    labels_by_vpa: dict[str, dict] = {}
    with open(LABELS_CSV, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels_by_id[row["account_id"]] = row
            labels_by_vpa[row["vpa"]] = row

    vpa_to_id: dict[str, str] = {}
    id_to_vpa: dict[str, str] = {}
    for row in txns:
        vpa_to_id.setdefault(row["sender_vpa"], row["sender_id"])
        vpa_to_id.setdefault(row["recv_vpa"], row["recv_id"])
        id_to_vpa.setdefault(row["sender_id"], row["sender_vpa"])
        id_to_vpa.setdefault(row["recv_id"], row["recv_vpa"])

    first_dt = parse_timestamp(txns[0]["timestamp"])
    epoch = datetime(first_dt.year, first_dt.month, first_dt.day)
    last_dt = max(parse_timestamp(row["timestamp"]) for row in txns)

    return {
        "txns": txns,
        "labels_by_id": labels_by_id,
        "labels_by_vpa": labels_by_vpa,
        "vpa_to_id": vpa_to_id,
        "id_to_vpa": id_to_vpa,
        "epoch": epoch,
        "last_dt": last_dt,
    }


def encode_timestamp(when: datetime) -> int:
    """Encode a wall-clock time onto the same integer scale the model trained on."""
    return int((when - _data()["epoch"]).total_seconds()) + _TIMESTAMP_OFFSET


def default_timestamp() -> datetime:
    """Latest transaction time in the dataset - a sensible 'just now' for a fresh edge."""
    return _data()["last_dt"]


def resolve_account(handle: str) -> Account:
    """Resolve a VPA or account id to its dataset identity (or an 'unknown' Account)."""
    data = _data()
    handle = (handle or "").strip()

    account_id = ""
    if handle in data["labels_by_id"] or handle in data["id_to_vpa"]:
        account_id = handle
    elif handle in data["vpa_to_id"]:
        account_id = data["vpa_to_id"][handle]
    elif handle in data["labels_by_vpa"]:
        account_id = data["labels_by_vpa"][handle]["account_id"]

    if not account_id:
        return Account("", handle, "", "", "unknown", False, False)

    label = data["labels_by_id"].get(account_id)
    vpa = data["id_to_vpa"].get(account_id) or (label["vpa"] if label else handle)
    in_graph = account_id in data["id_to_vpa"]
    if label:
        return Account(account_id, vpa, label["state"], label["bank"],
                       label["role"], label["is_mule"] == "1", in_graph)
    return Account(account_id, vpa, "", "", "unknown", False, in_graph)


def _rows_for(account_id: str, field: str) -> list[dict]:
    return [row for row in _data()["txns"] if row[field] == account_id] if account_id else []


def account_profile(handle: str) -> dict:
    """Behavioural summary of an account - the 'Mule Pulse' signals, from real rows."""
    account = resolve_account(handle)
    inbound = _rows_for(account.account_id, "recv_id")
    outbound = _rows_for(account.account_id, "sender_id")

    def _amount(row: dict) -> float:
        return float(row["amount_inr"])

    def _near_5l(row: dict) -> bool:
        return 450_000 <= _amount(row) <= 560_000

    first_in = min((parse_timestamp(r["timestamp"]) for r in inbound), default=None)
    first_out = min((parse_timestamp(r["timestamp"]) for r in outbound), default=None)
    turnaround = int((first_out - first_in).total_seconds()) if first_in and first_out else None

    return {
        "vpa": account.vpa,
        "account_id": account.account_id or None,
        "known_to_dataset": bool(account.account_id),
        "in_background_graph": account.in_graph,
        "dataset_label": {
            "role": account.role,
            "is_mule": account.is_mule,
            "state": account.state or None,
            "bank": account.bank or None,
            "note": "synthetic ground-truth label; in production this would be a KYC/AML record",
        },
        "inbound_count": len(inbound),
        "outbound_count": len(outbound),
        "total_inbound_inr": round(sum(_amount(r) for r in inbound), 2),
        "total_outbound_inr": round(sum(_amount(r) for r in outbound), 2),
        "distinct_inbound_counterparties": len({r["sender_id"] for r in inbound}),
        "distinct_outbound_counterparties": len({r["recv_id"] for r in outbound}),
        "transfers_near_5L": sum(1 for r in inbound + outbound if _near_5l(r)),
        "first_inflow": first_in.isoformat() if first_in else None,
        "first_outflow": first_out.isoformat() if first_out else None,
        "seconds_first_in_to_first_out": turnaround,
        "counterparty_states": sorted(
            {r["sender_state"] for r in inbound} | {r["recv_state"] for r in outbound}
        ),
    }


def downstream_transfers(handle: str, limit: int = 20) -> list[dict]:
    """Outgoing transfers from this account, earliest first - trace the next hop."""
    account = resolve_account(handle)
    rows = sorted(_rows_for(account.account_id, "sender_id"), key=lambda r: r["timestamp"])
    return [
        {
            "to_vpa": row["recv_vpa"],
            "to_state": row["recv_state"],
            "amount_inr": float(row["amount_inr"]),
            "timestamp": row["timestamp"],
            "layer": row["layer"],
            "is_fraud_label": row["is_fraud"] == "1",
        }
        for row in rows[:limit]
    ]
