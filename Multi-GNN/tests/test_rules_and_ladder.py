"""Rules r2.0 against an adversary, and the graded-action ladder.

Every stream here is built by hand in the test (fixtures, not data). The adversary knows
the rules: it splits money under the ₹1 lakh UPI cap, waits past short windows, and stays
just under thresholds. Each test says what is caught and what is not.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import rail_engine as re_
from rail_engine import Dataset, RailEngine

T0 = datetime(2024, 3, 11, 9, 0, 0)


class Stream:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.scores: list[float] = []
        self.roles: dict[str, str] = {}

    def pay(self, src: str, dst: str, amount: float, at: datetime, *, fraud: int = 0, score: float = 0.01, channel: str = "P2P", src_state: str = "Tamil Nadu", dst_state: str = "Rajasthan") -> None:
        self.rows.append({
            "txn_id": f"T{len(self.rows):06d}", "sender_vpa": f"{src}@ybl", "sender_id": src, "recv_vpa": f"{dst}@ybl", "recv_id": dst,
            "amount_inr": amount, "timestamp": at.isoformat(), "sender_state": src_state, "recv_state": dst_state,
            "is_fraud": fraud, "layer": "L0→L1" if fraud else "clean", "channel": channel,
        })
        self.scores.append(score)
        self.roles.setdefault(src, "clean")
        self.roles.setdefault(dst, "clean")

    def engine(self, *, auto_hold: bool = False, threshold: float = 0.9) -> RailEngine:
        raw = pd.DataFrame(self.rows)
        labels = pd.DataFrame([{"account_id": a, "role": r, "bank": "SBI"} for a, r in self.roles.items()])
        data = Dataset(raw, np.array(self.scores), labels, {"version": "test"})
        eng = RailEngine(data, record_actions=False, auto_hold=auto_hold, model_threshold=threshold)
        eng.run_to_end()
        return eng


def detectors(eng: RailEngine, account: str) -> set[str]:
    return {a.detector for a in eng.alerts.values() if a.account_id == account}


def test_five_lakh_split_under_the_cap_is_caught():
    """₹5L as five ₹99,999 transfers from new payers. The v1 rule (one transfer >= ₹4.5L) cannot fire
    on any UPI P2P transfer, so without aggregation this would pass untouched."""
    s = Stream()
    for i in range(5):
        s.pay(f"victim{i}", "mule", 99_999, T0 + timedelta(minutes=35 * i), fraud=1)
    assert max(r["amount_inr"] for r in s.rows) < 450_000
    eng = s.engine()
    assert {"inflow_new_payers", "structuring"} <= detectors(eng, "mule")


def test_forwarding_after_75_minutes_escapes_1h_but_not_6h():
    s = Stream()
    s.pay("v1", "mule", 90_000, T0, fraud=1)
    s.pay("v2", "mule", 80_000, T0 + timedelta(minutes=10), fraud=1)
    for i in range(4):  # 90% out, starting 75 minutes after the first inflow
        s.pay("mule", f"l2_{i}", 38_000, T0 + timedelta(minutes=75 + 5 * i), fraud=1)
    eng = s.engine()
    alert = next(a for a in eng.alerts.values() if a.detector == "pass_through")
    assert alert.account_id == "mule" and "6 hours" in alert.title


def test_slow_drip_under_the_daily_bar_is_caught_by_the_72h_window():
    """₹1.45L a day from two new payers stays under the 24 h bar (₹1.5L); by day 3 the 72 h total
    (₹4.35L) passes its bar (₹3L). Amounts avoid the near-cap band so structuring stays quiet."""
    s = Stream()
    for day in range(3):  # 26 h apart, so no 24 h window ever holds more than one day's ₹1.45L
        s.pay(f"a{day}", "drip", 72_500, T0 + timedelta(hours=26 * day))
        s.pay(f"b{day}", "drip", 72_500, T0 + timedelta(hours=26 * day + 2))
    eng = s.engine()
    alert = next(a for a in eng.alerts.values() if a.detector == "inflow_new_payers")
    assert alert.account_id == "drip"
    assert "72 hours" in alert.reason
    assert alert.created_t >= (T0 + timedelta(hours=52)).timestamp()  # nothing on days 0-1: a known gap


def test_just_under_every_bar_is_not_caught():
    """The boundary, stated rather than hidden: ₹1.45L once, from two new payers, half of it
    forwarded. No rule fires; only the model or a later hop can catch this."""
    s = Stream()
    s.pay("x", "quiet", 72_500, T0)
    s.pay("y", "quiet", 72_500, T0 + timedelta(hours=1))
    s.pay("quiet", "z1", 36_000, T0 + timedelta(hours=3))
    s.pay("quiet", "z2", 36_000, T0 + timedelta(hours=4))
    assert detectors(s.engine(), "quiet") == set()


def test_busy_account_baseline_raises_its_own_bar():
    """₹60k a day from new payers for a week sets a ₹1.8L bar (3x). A ₹1.6L day then stays quiet,
    while the same ₹1.6L into a fresh account alerts."""
    s = Stream()
    for day in range(7):
        for k in range(3):
            s.pay(f"cust{day}_{k}", "busy", 20_000, T0 + timedelta(days=day, hours=k))
    for k in range(4):
        s.pay(f"new{k}", "busy", 40_000, T0 + timedelta(days=7, hours=k))
        s.pay(f"other{k}", "fresh", 40_000, T0 + timedelta(days=7, hours=k))
    eng = s.engine()
    assert "inflow_new_payers" not in detectors(eng, "busy")
    assert "inflow_new_payers" in detectors(eng, "fresh")


def test_established_forwarder_alerts_only_at_abnormal_scale():
    """A shop forwards 80% of its takings every day. Days 0-4 (₹90k, under the ₹1L floor) season
    its baseline; on days 5-6 it takes ₹1.2L, over the floor but under 3x its usual day, and stays
    quiet. A new shop with no history would alert: that is deliberate, not a bug."""
    s = Stream()
    for day in range(7):
        amount = 45_000 if day < 5 else 60_000
        s.pay(f"c{day}", "shop", amount, T0 + timedelta(days=day, hours=1))
        s.pay(f"d{day}", "shop", amount, T0 + timedelta(days=day, hours=2))
        s.pay("shop", "supplierA", amount * 0.8, T0 + timedelta(days=day, hours=5))
        s.pay("shop", "supplierB", amount * 0.8, T0 + timedelta(days=day, hours=6))
    eng = s.engine()
    assert "pass_through" not in detectors(eng, "shop")
    for k in range(5):  # then ₹4.5L in and 90% out within the hour: 3.75x its usual day
        s.pay(f"e{k}", "shop", 90_000, T0 + timedelta(days=7, minutes=5 * k), fraud=1)
    for k in range(5):
        s.pay("shop", f"out{k}", 81_000, T0 + timedelta(days=7, minutes=30 + 3 * k), fraud=1)
    assert "pass_through" in detectors(s.engine(), "shop")


# ---------------------------------------------------------------------- the ladder


def mule_stream(score: float, amount: float = 70_000) -> Stream:
    """Enough for a critical inflow alert; then the mule tries to move money on, every 10 minutes.
    At ₹99,999 a transfer the structuring rule fires too: two detectors corroborate."""
    s = Stream()
    for i in range(3):
        s.pay(f"victim{i}", "mule", amount, T0 + timedelta(minutes=10 * i), fraud=1, score=score)
    for k in range(12):
        s.pay("mule", f"out{k}", 15_000, T0 + timedelta(minutes=40 + 10 * k), fraud=1, score=score)
    s.pay("late_victim", "mule", 20_000, T0 + timedelta(minutes=100), fraud=1, score=score)
    return s


def test_router_levels():
    critical_low_model = mule_stream(score=0.1).engine(auto_hold=True)
    assert critical_low_model.restriction_log[0]["level"] == 2  # critical, one detector, model below threshold
    model_one_detector = mule_stream(score=0.99).engine(auto_hold=True)
    assert max(e["level"] for e in model_one_detector.restriction_log) == 2  # the hold stops the forwarding that would corroborate
    corroborated = mule_stream(score=0.99, amount=99_999).engine(auto_hold=True)
    assert max(e["level"] for e in corroborated.restriction_log) == 3  # critical + model + two detectors


def test_hold_outbound_blocks_out_but_not_in():
    eng = mule_stream(score=0.1).engine(auto_hold=True)
    out = [r for r in eng.replayed if r.from_id == "mule"]
    late_in = next(r for r in eng.replayed if r.from_id == "late_victim")
    assert all(r.blocked for r in out)
    assert not late_in.blocked  # level 2 still lets money in (and keeps the evidence coming)


def test_full_hold_blocks_both_directions():
    eng = mule_stream(score=0.99, amount=99_999).engine(auto_hold=True)
    late_in = next(r for r in eng.replayed if r.from_id == "late_victim")
    assert late_in.blocked


def test_delay_then_escalation_recovers_the_delayed_money():
    """A high alert (two new payers, ₹1.6L) with a low model score delays settlement; the delayed
    transfers are cancelled when a third payer makes the alert critical and the hold escalates."""
    s = Stream()
    s.pay("v1", "m", 80_000, T0, fraud=1, score=0.1)
    s.pay("v2", "m", 80_000, T0 + timedelta(minutes=5), fraud=1, score=0.1)  # high: 2 payers, ₹1.6L
    s.pay("m", "o1", 30_000, T0 + timedelta(minutes=10), fraud=1, score=0.1)  # delayed
    s.pay("v3", "m", 60_000, T0 + timedelta(minutes=20), fraud=1, score=0.1)  # critical: 3 payers
    s.pay("m", "o2", 30_000, T0 + timedelta(minutes=25), fraud=1, score=0.1)  # blocked
    eng = s.engine(auto_hold=True)
    levels = [e["level"] for e in eng.restriction_log]
    assert levels[:2] == [1, 2]
    o1 = next(r for r in eng.replayed if r.to_id == "o1")
    assert o1.delayed and o1.blocked
    assert eng.recovered_fraud == 30_000


def test_restriction_expires_and_the_alert_returns_to_the_queue():
    s = Stream()
    s.pay("v1", "m", 80_000, T0, score=0.1)
    s.pay("v2", "m", 80_000, T0 + timedelta(minutes=5), score=0.1)  # level 1, one hour
    s.pay("m", "o1", 30_000, T0 + timedelta(minutes=10), score=0.1)
    s.pay("q", "r", 100, T0 + timedelta(hours=3))  # the clock moves on
    eng = s.engine(auto_hold=True)
    assert eng.held == {}
    assert eng.restriction_log[0]["how"] == "restriction_expired"
    assert eng.released_delayed == 30_000
    assert any(e["action"] == "restriction_expired" for e in eng.audit)


def test_prior_clear_steps_the_level_down():
    """A supervisor released this account once; the next critical alert on it holds one level lower."""
    import dataclasses

    eng = mule_stream(score=0.1).engine(auto_hold=True)
    held = next(a for a in eng.alerts.values() if a.status == "held")
    eng.act(held.id, "clear", "Verified with the account holder.", "meera.supervisor", "supervisor")
    assert "mule" not in eng.held
    later = dataclasses.replace(held, id="ALR-LATER", detector="pass_through", status="open", severity="critical")
    eng.alerts[later.id] = later
    eng.alerts_by_account["mule"].append(later)
    level, why = eng._route(later)
    assert level == 1 and "stepped down" in why


def test_appeal_deadline_lifts_the_restriction():
    s = mule_stream(score=0.1)
    eng = s.engine(auto_hold=True)
    alert_id = next(a.id for a in eng.alerts.values() if a.account_id == "mule" and a.status == "held")
    out = eng.appeal(alert_id, "These were payments from my relatives.", "priya.analyst", "analyst")
    assert "error" not in out
    eng.sim_t += re_.APPEAL_SLA_SECONDS + 1
    eng._expire()
    assert "mule" not in eng.held
    assert any(e["action"] == "appeal_sla_release" for e in eng.audit)


def test_appeal_release_clears_and_uphold_keeps():
    eng = mule_stream(score=0.1).engine(auto_hold=True)
    alert_id = next(a.id for a in eng.alerts.values() if a.account_id == "mule" and a.status == "held")
    eng.appeal(alert_id, "statement", "priya.analyst", "analyst")
    eng.decide_appeal(alert_id, "uphold", "Evidence stands.", "meera.supervisor", "supervisor")
    assert "mule" in eng.held and eng.held["mule"]["appeal"]["status"] == "upheld"
    eng.held["mule"]["appeal"] = None
    eng.appeal(alert_id, "second statement", "priya.analyst", "analyst")
    eng.decide_appeal(alert_id, "release", "Documents check out.", "meera.supervisor", "supervisor")
    assert "mule" not in eng.held and eng.alerts[alert_id].status == "cleared"


def test_appeal_needs_a_restriction():
    s = Stream()
    s.pay("a", "b", 100, T0)
    eng = s.engine(auto_hold=True)
    assert eng.appeal("ALR-9999", "x", "priya.analyst", "analyst")["status"] == 404
