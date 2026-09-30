"""infra/ablation.py: the base-rate arithmetic and the test-day amount shuffle.

    cd Multi-GNN && python -m pytest tests -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from infra import ablation


def test_base_rate_matches_measured_precision_at_1x():
    t = ablation.base_rate_table(tp=45, fn=12, fp=2, negatives=16244, unit="payment")
    one = t["rows"][0]
    assert one["rarer"] == 1
    assert one["precision"] == pytest.approx(45 / 47)


def test_base_rate_precision_falls_and_range_brackets_point():
    t = ablation.base_rate_table(tp=20, fn=6, fp=9, negatives=5245, unit="account")
    rows = t["rows"]
    assert [r["precision"] for r in rows] == sorted((r["precision"] for r in rows), reverse=True)
    for r in rows:
        assert r["precisionLow"] <= r["precision"] <= r["precisionHigh"]
    lo, hi = t["falsePositiveRateCi"]
    assert lo < 9 / 5245 < hi


def test_payment_table_adds_reported_upi_anchor():
    factor = ablation.reported_factor(57 / (57 + 16244))
    t = ablation.base_rate_table(tp=45, fn=12, fp=2, negatives=16244, unit="payment (model alone)", anchor=factor)
    anchors = [r for r in t["rows"] if r["anchor"]]
    assert len(anchors) == 1
    assert anchors[0]["prevalence"] == pytest.approx(ablation.REPORTED_UPI["incidents"] / ablation.REPORTED_UPI["transactions"])
    assert not any(r["anchor"] for r in ablation.base_rate_table(tp=20, fn=6, fp=9, negatives=5245, unit="account")["rows"])


def test_permute_touches_only_test_day_amounts():
    day = 86400.0
    epoch = np.array([0, day * 3, day * 8 + 5, day * 8 + 60, day * 9 + 7, day * 9.5])
    feats = np.column_stack([np.arange(6.0), np.arange(6.0) * 10, np.zeros(6)]).astype(np.float32)
    out = ablation.permute_test_amounts(feats, ["HourOfDay", "LogAmount", "Payment Format"], pd.DataFrame(), epoch)
    np.testing.assert_array_equal(out[:, 0], feats[:, 0])
    np.testing.assert_array_equal(out[:2, 1], feats[:2, 1])
    assert sorted(out[2:, 1]) == sorted(feats[2:, 1])
