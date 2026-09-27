"""The transaction -> GNN-request shim.

`bridge_api.py`'s /predict does not take a transaction - it takes a graph tensor
payload (`node_features`, `edges[].features`, `node_account_ids`). This module is
the translation layer:

* edge features are emitted in the exact order the model trained on -
  `[Timestamp, Amount Received, Received Currency, Payment Format]` (see
  `models/local_finetuned_gin_nolambur.norm.json`);
* node features are the single all-ones placeholder column the GIN uses;
* each party's real Nolambur account id is passed as `node_account_ids`, which is
  what makes the bridge splice the edge onto the real background graph instead of
  scoring it as an isolated island (see `_load_background_graph` in bridge_api.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .nolambur_data import Account, default_timestamp, encode_timestamp, parse_timestamp, resolve_account

# The Nolambur formatted data uses one currency and one payment format, both
# encoded as 0 by prepare_datasets.convert_nolambur.
_RECEIVED_CURRENCY = 0.0
_PAYMENT_FORMAT = 0.0


def _coerce_timestamp(value: str | datetime | None) -> datetime:
    if value is None or value == "":
        return default_timestamp()
    if isinstance(value, datetime):
        return value
    return parse_timestamp(value)


def _edge_features(amount_inr: float, when: datetime) -> list[float]:
    return [float(encode_timestamp(when)), float(amount_inr), _RECEIVED_CURRENCY, _PAYMENT_FORMAT]


def _brief(account: Account) -> dict[str, Any]:
    return {
        "handle": account.vpa,
        "account_id": account.account_id or None,
        "state": account.state or None,
        "dataset_role": account.role,
        "in_background_graph": account.in_graph,
    }


def transaction_to_predict_payload(
    sender: str,
    receiver: str,
    amount_inr: float,
    timestamp: str | datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a single-edge /predict payload for one transfer.

    Returns `(payload, context)` - context carries the resolved identities and
    the encoded timestamp so the caller can explain what was scored.
    """
    src = resolve_account(sender)
    dst = resolve_account(receiver)
    when = _coerce_timestamp(timestamp)

    payload = {
        "model": "gin",
        "node_features": [[1.0], [1.0]],
        "edges": [{"source": 0, "target": 1, "features": _edge_features(amount_inr, when)}],
        "node_account_ids": [src.account_id or None, dst.account_id or None],
    }
    context = {
        "sender": _brief(src),
        "receiver": _brief(dst),
        "amount_inr": float(amount_inr),
        "timestamp": when.isoformat(),
        "timestamp_encoded": encode_timestamp(when),
    }
    return payload, context


def chain_to_predict_payload(
    legs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a multi-edge /predict payload for a suspected layering chain.

    Each leg is `{"sender", "receiver", "amount_inr", "timestamp"?}`. Parties that
    resolve to the same dataset account share a node.
    """
    node_index: dict[str, int] = {}
    node_keys: list[str] = []
    accounts: dict[str, Account] = {}

    def node_for(handle: str) -> int:
        account = resolve_account(handle)
        key = account.account_id or f"ext:{account.vpa}"
        if key not in node_index:
            node_index[key] = len(node_keys)
            node_keys.append(key)
            accounts[key] = account
        return node_index[key]

    edges = []
    leg_context = []
    for leg in legs:
        src_i = node_for(leg["sender"])
        dst_i = node_for(leg["receiver"])
        when = _coerce_timestamp(leg.get("timestamp"))
        edges.append(
            {"source": src_i, "target": dst_i, "features": _edge_features(leg["amount_inr"], when)}
        )
        leg_context.append(
            {
                "sender": leg["sender"],
                "receiver": leg["receiver"],
                "amount_inr": float(leg["amount_inr"]),
                "timestamp": when.isoformat(),
            }
        )

    payload = {
        "model": "gin",
        "node_features": [[1.0] for _ in node_keys],
        "edges": edges,
        "node_account_ids": [accounts[key].account_id or None for key in node_keys],
    }
    context = {
        "nodes": [_brief(accounts[key]) for key in node_keys],
        "legs": leg_context,
    }
    return payload, context
