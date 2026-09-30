"""infra/p2m.py: the aggregator-view detectors and the settlement hold, on hand-built fixtures.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from infra import p2m

START = datetime(2024, 3, 11)
PARAMS = {"rules": "p1.0", "catP99": {"kirana": 1_600, "subscription": 1_200}, "d1Count": 3, "d2States": 6, "d3Requests": 14, "d3FailShare": 0.69}


def world(tmp_path: Path, merchants: list[dict], payments: list[dict], collects: list[dict]) -> p2m.Data:
    base = {"vpa": "m@ybl", "state": "Tamil Nadu", "chain": "", "is_fraud": 0, "scenario": "", "campaign": "", "onboarded_at": (START - timedelta(days=200)).isoformat()}
    pd.DataFrame([{**base, **m} for m in merchants]).to_csv(tmp_path / "merchants.csv", index=False)
    cols = ["txn_id", "payer_id", "payer_vpa", "payer_state", "merchant_id", "amount_inr", "timestamp", "initiation", "is_fraud", "campaign"]
    pd.DataFrame(payments, columns=cols).to_csv(tmp_path / "payments.csv", index=False)
    ccols = ["request_id", "merchant_id", "payer_id", "payer_state", "amount_inr", "requested_at", "resolved_at", "outcome", "known_payer", "is_fraud", "campaign"]
    pd.DataFrame(collects, columns=ccols).to_csv(tmp_path / "collects.csv", index=False)
    (tmp_path / "stats.json").write_text(json.dumps({"start": START.isoformat(), "days": 3}), encoding="utf-8")
    return p2m.Data(tmp_path)


def pay(i: int, merchant: str, amount: float, at: datetime, state: str = "Delhi", payer: str | None = None) -> dict:
    return {"txn_id": f"T{i}", "payer_id": payer or f"p{i}", "payer_vpa": "x@ybl", "payer_state": state, "merchant_id": merchant, "amount_inr": amount,
            "timestamp": at.isoformat(), "initiation": "intent", "is_fraud": 0, "campaign": ""}


def run(data: p2m.Data) -> p2m.Engine:
    p2m._CAT_P99.clear()
    p2m._CAT_P99.update(PARAMS["catP99"])
    return p2m.Engine(data, PARAMS).run()


def test_big_tickets_from_new_payers_fire_d1_and_hold_settlement(tmp_path):
    t = START + timedelta(hours=10)
    data = world(tmp_path, [{"merchant_id": "shop", "category": "kirana", "legal_entity": "E1", "settlement_account": "SA1"}],
                 [pay(i, "shop", 40_000, t + timedelta(minutes=20 * i)) for i in range(3)], [])
    eng = run(data)
    assert [a["detector"] for a in eng.alerts] == ["D1"]
    assert eng.held_rows == {0, 1, 2}  # the next morning's batch is held
    # nobody confirms, so the 24 h hold lifts and the money settles in the following batch
    day2_batch = (START + timedelta(days=2, hours=p2m.BATCH_HOUR)).timestamp()
    assert set(eng.settled_at.values()) == {day2_batch}


def test_two_big_tickets_are_not_enough(tmp_path):
    t = START + timedelta(hours=10)
    data = world(tmp_path, [{"merchant_id": "shop", "category": "kirana", "legal_entity": "E1", "settlement_account": "SA1"}],
                 [pay(i, "shop", 40_000, t + timedelta(minutes=20 * i)) for i in range(2)], [])
    eng = run(data)
    assert eng.alerts == [] and set(eng.settled_at) == {0, 1}


def test_failing_collects_to_strangers_fire_d3_but_billers_customers_do_not(tmp_path):
    t = START + timedelta(hours=9)

    def req(i: int, merchant: str, outcome: str, known: int) -> dict:
        at = t + timedelta(minutes=5 * i)
        return {"request_id": f"R{merchant}{i}", "merchant_id": merchant, "payer_id": f"q{i}", "payer_state": "Delhi", "amount_inr": 5_000,
                "requested_at": at.isoformat(), "resolved_at": (at + timedelta(minutes=30)).isoformat(), "outcome": outcome, "known_payer": known,
                "is_fraud": 0, "campaign": ""}
    collects = [req(i, "scam", "declined" if i % 10 else "approved", 0) for i in range(20)]
    collects += [req(i, "biller", "declined", 1) for i in range(20)]
    data = world(tmp_path, [{"merchant_id": "scam", "category": "subscription", "legal_entity": "E1", "settlement_account": "SA1"},
                            {"merchant_id": "biller", "category": "subscription", "legal_entity": "E2", "settlement_account": "SA2"}], [], collects)
    eng = run(data)
    assert {(a["merchant"], a["detector"]) for a in eng.alerts} == {("scam", "D3")}


def test_shared_settlement_across_entities_is_a_review_not_a_hold(tmp_path):
    t = START + timedelta(hours=10)
    data = world(tmp_path, [{"merchant_id": "a", "category": "kirana", "legal_entity": "E1", "settlement_account": "SA1"},
                            {"merchant_id": "b", "category": "kirana", "legal_entity": "E2", "settlement_account": "SA1"},
                            {"merchant_id": "chain", "category": "kirana", "legal_entity": "E3", "settlement_account": "SA3"},
                            {"merchant_id": "chain2", "category": "kirana", "legal_entity": "E3", "settlement_account": "SA3"}],
                 [pay(0, "a", 300, t)], [])
    eng = run(data)
    assert {(a["merchant"], a["detector"]) for a in eng.alerts} == {("a", "D4"), ("b", "D4")}
    assert eng.hold_until == {} and 0 in eng.settled_at
