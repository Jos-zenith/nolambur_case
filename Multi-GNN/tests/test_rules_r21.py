"""Rules r2.1 (RAIL_RULES=r2.1) and model-only friction (RAIL_MODEL_FRICTION=1).

Hand-built streams, as in test_rules_and_ladder.py. Each case runs under r2.0 and r2.1, so the
test states what the patch changes, and what it still lets through.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.test_rules_and_ladder import T0, Stream, detectors


@pytest.fixture
def rules(monkeypatch):
    def use(version: str, friction: bool = False) -> None:
        monkeypatch.setenv("RAIL_RULES", version)
        monkeypatch.setenv("RAIL_MODEL_FRICTION", "1" if friction else "0")
    return use


def half_size_mule() -> Stream:
    """A new account takes ₹60,000 from two victims and sends 90% on to three accounts in an hour."""
    s = Stream()
    s.pay("v1", "mule", 32_000, T0, fraud=1)
    s.pay("v2", "mule", 28_000, T0 + timedelta(minutes=12), fraud=1)
    for i in range(3):
        s.pay("mule", f"l2_{i}", 18_000, T0 + timedelta(minutes=30 + 5 * i), fraud=1)
    return s


def test_half_size_pass_through_needs_r21(rules):
    rules("r2.0")
    assert "pass_through" not in detectors(half_size_mule().engine(), "mule")  # under the ₹1 lakh floor
    rules("r2.1")
    assert "pass_through" in detectors(half_size_mule().engine(), "mule")  # over the ₹25,000 cold-start floor


def test_r21_still_misses_a_ring_under_its_floor(rules):
    """₹20,000 through a new account is under r2.1's ₹25,000 floor: the stated limit."""
    rules("r2.1")
    s = Stream()
    s.pay("v1", "mule", 20_000, T0, fraud=1)
    for i in range(2):
        s.pay("mule", f"l2_{i}", 9_000, T0 + timedelta(minutes=20 + 5 * i), fraud=1)
    assert "pass_through" not in detectors(s.engine(), "mule")


def test_many_small_new_payers_fire_fan_in_under_r21_only(rules):
    """Six victims, ₹3,000 each: no amount rule can see it; counting people can."""
    def stream() -> Stream:
        s = Stream()
        for i in range(6):
            s.pay(f"victim{i}", "mule", 3_000, T0 + timedelta(minutes=40 * i), fraud=1)
        return s
    rules("r2.0")
    assert detectors(stream().engine(), "mule") == set()
    rules("r2.1")
    assert "fan_in_new_payers" in detectors(stream().engine(), "mule")


def test_four_new_payers_is_ordinary(rules):
    rules("r2.1")
    s = Stream()
    for i in range(4):
        s.pay(f"friend{i}", "person", 3_000, T0 + timedelta(minutes=40 * i))
    assert "fan_in_new_payers" not in detectors(s.engine(), "person")


def test_fan_in_ignores_merchant_payments(rules):
    rules("r2.1")
    s = Stream()
    for i in range(8):
        s.pay(f"shopper{i}", "shop", 500, T0 + timedelta(minutes=10 * i), channel="P2M")
    assert detectors(s.engine(), "shop") == set()


def test_friction_delays_a_confident_model_only_lead(rules):
    """A model-only alert at 0.97 gets settlement delayed (level 1) with friction, nothing without."""
    def stream() -> Stream:
        s = Stream()
        s.pay("v1", "mule", 12_000, T0, fraud=1, score=0.97)
        s.pay("mule", "l2", 10_000, T0 + timedelta(minutes=5), fraud=1)
        return s
    rules("r2.1")
    eng = stream().engine(auto_hold=True, threshold=0.86)
    assert eng.held.get("mule") is None
    rules("r2.1", friction=True)
    eng = stream().engine(auto_hold=True, threshold=0.86)
    assert eng.held["mule"]["level"] == 1
    out = next(r for r in eng.replayed if r.from_id == "mule")
    assert out.delayed and not out.blocked


def test_hop_rule_can_be_switched_off(monkeypatch):
    """RAIL_HOP_FROM_FLAGGED=0: the next hop after a flagged mule is no longer alerted."""
    def stream() -> Stream:
        s = Stream()
        for i in range(5):
            s.pay(f"victim{i}", "mule", 99_999, T0 + timedelta(minutes=35 * i), fraud=1)
        s.pay("mule", "next", 90_000, T0 + timedelta(hours=4), fraud=1)
        return s
    monkeypatch.setenv("RAIL_RULES", "r2.1")
    assert "hop_from_flagged" in detectors(stream().engine(), "next")
    monkeypatch.setenv("RAIL_HOP_FROM_FLAGGED", "0")
    assert "hop_from_flagged" not in detectors(stream().engine(), "next")


def test_r22_hop_skips_shops_and_small_shares(monkeypatch):
    """r2.2: the next hop is alerted for an individual whose inflow is mostly flagged money, not for
    a shop the mule pays, and not for a person getting a small share from it."""
    def stream() -> Stream:
        s = Stream()
        for i in range(5):
            s.pay(f"victim{i}", "mule", 99_999, T0 + timedelta(minutes=35 * i), fraud=1)
        s.pay("mule", "next", 90_000, T0 + timedelta(hours=4), fraud=1)
        s.pay("mule", "shop", 9_000, T0 + timedelta(hours=4, minutes=5), channel="P2M")
        for i in range(6):  # a busy person: ₹60,000 from friends, then ₹7,000 from the mule
            s.pay(f"friend{i}", "busy", 10_000, T0 + timedelta(hours=1, minutes=10 * i))
        s.pay("mule", "busy", 7_000, T0 + timedelta(hours=4, minutes=10))
        s.kinds["shop"] = "merchant"
        return s
    monkeypatch.setenv("RAIL_RULES", "r2.1")
    eng = stream().engine()
    assert {"next", "shop", "busy"} <= {a.account_id for a in eng.alerts.values() if a.detector == "hop_from_flagged"}
    monkeypatch.setenv("RAIL_RULES", "r2.2")
    eng = stream().engine()
    assert {a.account_id for a in eng.alerts.values() if a.detector == "hop_from_flagged"} == {"next"}
