"""Break-even: what precision (and how many catches) make the alert queue worth running.

    python -m infra.breakeven        -> reports/breakeven.json

Per alert an analyst reviews:
    value = p * B  -  C  -  (1 - p) * h * F
      p  precision: share of alerted accounts that are mules
      B  money a confirmed mule alert saves = money through a mule x share a hold stops
      C  analyst cost of one review
      h  share of alerts the router restricts automatically (only those burden an innocent customer)
      F  cost of wrongly restricting one genuine account
Break-even precision p* = (C + h F) / (B + h F). With a fixed yearly cost K and a daily review budget A,
the queue as a whole breaks even at p** = (K / (365 A) + C + h F) / (B + h F).

Every input carries low / central / high and a source, or is labelled an assumption. Ranges are
wide on purpose: a Monte Carlo over triangular distributions gives the spread of p*.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "reports" / "breakeven.json"

SRC = {
    "upi_fy25": "https://madhyamamonline.com/india/upi-linked-frauds-amount-to-rs-805-crore-far-fy26-govt-1477281",
    "upi_volume": "https://www.medianama.com/2025/05/223-upi-84-india-fy25-retail-payment-volume-rbi/",
    "cyber_2024": "https://www.indiatvnews.com/technology/news/indians-lost-over-rs-22-845-crore-to-cyber-fraud-in-2024-incidents-skyrocket-by-206-government-2025-07-22-1000037",
    "registry": "https://the420.in/cybercrime-suspect-registry-8031-crore-saved-mha-i4c-fraud-block/",
    "salary": "https://in.indeed.com/career/fraud-analyst/salaries",
    "rbi_tat": "https://www.medianama.com/2019/09/223-rbi-penalties-failed-transaction/",
    "alert_minutes": "https://www.fluxforce.ai/blog/fraud-alert-fatigue",
    "evidence": "reports/README.md",
}

# Reported facts (no range: they are the anchors the ranges are built from)
FACTS = {
    "upiFraudIncidentsFY25": {"value": 12.64e5, "source": SRC["upi_fy25"], "note": "Lok Sabha, 15 Dec 2025"},
    "upiFraudAmountFY25Rs": {"value": 981e7, "source": SRC["upi_fy25"], "note": "Rs 981 crore"},
    "upiTransactionsFY25": {"value": 185.9e9, "source": SRC["upi_volume"], "note": "RBI Annual Report 2024-25"},
    "cyberFraudLoss2024Rs": {"value": 22845.73e7, "source": SRC["cyber_2024"], "note": "NCRP + CFCFRMS, Lok Sabha, 22 Jul 2025"},
    "cyberFraudIncidents2024": {"value": 3637288, "source": SRC["cyber_2024"]},
    "layer1MuleAccountsShared": {"value": 24.67e5, "source": SRC["registry"], "note": "I4C Suspect Registry, Sep 2024 to Dec 2025 (about 15 months)"},
    "fraudAnalystSalaryRs": {"value": 502768, "source": SRC["salary"], "note": "Indeed India average, 34 salaries, updated 20 Sep 2026"},
    "rbiFailedTxnCompensationRsPerDay": {"value": 100, "source": SRC["rbi_tat"], "note": "RBI TAT circular, 20 Sep 2019: Rs 100 a day past the reversal deadline"},
}


def _per_mule() -> float:
    # a year's reported cyber-fraud loss, spread over the Layer-1 mule accounts registered in ~15 months
    return FACTS["cyberFraudLoss2024Rs"]["value"] * 15 / 12 / FACTS["layer1MuleAccountsShared"]["value"]


PARAMS = {
    "moneyPerMuleRs": {
        "low": 30_000, "central": round(_per_mule(), -2), "high": 2.3e5,
        "basis": "Central = 2024 cyber-fraud loss x 15/12 / 24.67 lakh Layer-1 mule accounts. Low allows for mules the registry "
                 "missed and losses that never touch a mule; high for losses spread over fewer active mules.",
        "sources": [SRC["cyber_2024"], SRC["registry"]],
    },
    "shareStoppedByHold": {
        "low": 0.05, "central": 0.15, "high": 0.30,
        "basis": "Synthetic replays: holds stop 11-19% of test-day fraud money (reports/README.md 2, 3.3). No real-traffic figure. Assumption around it.",
        "sources": [SRC["evidence"]],
    },
    "analystCostPerMinuteRs": {
        "low": 502768 * 1.2 / (230 * 7 * 60), "central": 502768 * 1.4 / (220 * 6.5 * 60), "high": 502768 * 2.0 / (210 * 6 * 60),
        "basis": "Indeed average salary, loaded x1.2-2.0 (assumption: benefits, tools, supervision, office), over 210-230 days of 6-7 productive hours.",
        "sources": [SRC["salary"]],
    },
    "minutesPerAlert": {
        "low": 5, "central": 15, "high": 30,
        "basis": "Vendor-reported range of 5-30 minutes per alert (weak source; no primary study found). Assumption.",
        "sources": [SRC["alert_minutes"]],
    },
    "shareOfAlertsRestricted": {
        "low": 0.05, "central": 0.15, "high": 0.50,
        "basis": "Router restricts only corroborated alerts: 4 of 29 alerted accounts on the test days, 27 of 181 over the full replay (~15%).",
        "sources": [SRC["evidence"]],
    },
    "costPerWrongRestrictionRs": {
        "low": 200, "central": 600, "high": 3000,
        "basis": "Rs 100 a day, the RBI failed-transaction compensation rate, as the regulator's own price of a held payment, for a 1-3 day hold; "
                 "plus handling the appeal (about 10 analyst minutes) and lost goodwill or churn (assumption: Rs 0-2,000, small because UPI P2P "
                 "and small-merchant payments carry no MDR).",
        "sources": [SRC["rbi_tat"]],
    },
    "fixedCostPerYearRs": {
        "low": 5e5, "central": 15e5, "high": 40e5,
        "basis": "Assumption: hosting, data pipeline, model upkeep share of an engineer. Analyst time is counted per alert, not here.",
        "sources": [],
    },
    "alertsPerDay": {
        "low": 50, "central": 50, "high": 50,
        "basis": "The pilot's review budget: 2 analysts x 25 accounts a day.",
        "sources": [],
    },
}


def per_alert(p, B, C, h, F):
    return p * B - C - (1 - p) * h * F


def breakeven(B, C, h, F, K=0.0, A=50.0):
    return (K / (365 * A) + C + h * F) / (B + h * F)


def scenario(which: str) -> dict:
    v = {k: PARAMS[k][which] for k in PARAMS}
    if which != "central":  # pessimistic = everything against the queue; optimistic = everything for it
        bad = which == "low"
        pick = lambda k, good_high: PARAMS[k]["low" if (good_high == bad) else "high"]
        v = {"moneyPerMuleRs": pick("moneyPerMuleRs", True), "shareStoppedByHold": pick("shareStoppedByHold", True),
             "analystCostPerMinuteRs": pick("analystCostPerMinuteRs", False), "minutesPerAlert": pick("minutesPerAlert", False),
             "shareOfAlertsRestricted": pick("shareOfAlertsRestricted", False), "costPerWrongRestrictionRs": pick("costPerWrongRestrictionRs", False),
             "fixedCostPerYearRs": pick("fixedCostPerYearRs", False), "alertsPerDay": 50}
    B = v["moneyPerMuleRs"] * v["shareStoppedByHold"]
    C = v["analystCostPerMinuteRs"] * v["minutesPerAlert"]
    h, F, K, A = v["shareOfAlertsRestricted"], v["costPerWrongRestrictionRs"], v["fixedCostPerYearRs"], v["alertsPerDay"]
    p1 = breakeven(B, C, h, F)
    p2 = breakeven(B, C, h, F, K, A)
    return {"inputs": {k: round(x, 2) for k, x in v.items()}, "savedPerConfirmedMuleRs": round(B), "reviewCostRs": round(C, 1),
            "breakevenPrecisionPerAlert": round(p1, 5), "breakevenPrecisionWithFixedCost": round(p2, 5),
            "mulesCaughtPerYearAtBreakeven": round(365 * A * p2, 1)}


def monte_carlo(n: int = 200_000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    draw = lambda k: rng.triangular(PARAMS[k]["low"], PARAMS[k]["central"], PARAMS[k]["high"], n) if PARAMS[k]["low"] < PARAMS[k]["high"] else np.full(n, PARAMS[k]["central"])
    B = draw("moneyPerMuleRs") * draw("shareStoppedByHold")
    C = draw("analystCostPerMinuteRs") * draw("minutesPerAlert")
    h, F, K, A = draw("shareOfAlertsRestricted"), draw("costPerWrongRestrictionRs"), draw("fixedCostPerYearRs"), draw("alertsPerDay")
    p_star = breakeven(B, C, h, F, K, A)
    q = lambda a: {f"p{int(x * 100)}": round(float(np.quantile(a, x)), 5) for x in (0.1, 0.25, 0.5, 0.75, 0.9)}
    # chance the queue (with its fixed cost) is worth running at a given precision
    at = {}
    for p in (0.002, 0.004, 0.011, 0.02, 0.04, 0.10, 0.20):
        yearly = 365 * A * per_alert(p, B, C, h, F) - K
        at[f"{p:.3f}"] = {"chanceWorthIt": round(float((yearly > 0).mean()), 3), "medianNetPerYearRs": round(float(np.median(yearly)))}
    return {"draws": n, "breakevenPrecision": q(p_star), "atPrecision": at}


def main() -> None:
    fr = FACTS
    result = {
        "facts": fr,
        "derived": {
            "upiFraudRatePerTransaction": fr["upiFraudIncidentsFY25"]["value"] / fr["upiTransactionsFY25"]["value"],
            "avgUpiLossPerIncidentRs": round(fr["upiFraudAmountFY25Rs"]["value"] / fr["upiFraudIncidentsFY25"]["value"]),
            "avgCyberLossPerIncidentRs": round(fr["cyberFraudLoss2024Rs"]["value"] / fr["cyberFraudIncidents2024"]["value"]),
            "moneyPerLayer1MuleRs": round(_per_mule()),
        },
        "params": PARAMS,
        "scenarios": {k: scenario(k) for k in ("low", "central", "high")},
        "monteCarlo": monte_carlo(),
        "achievable": {
            "accountQueueAtReportedRate": {"precision": 0.004, "range": [0.002, 0.011], "source": "reports/README.md 3.2 (arithmetic from synthetic false-alert rate)"},
            "modelPerPaymentAtReportedRate": {"precision": 0.04, "range": [0.01, 0.29], "source": "reports/README.md 3.2"},
            "syntheticTestAccountQueue": {"precision": [0.58, 0.78], "source": "reports/README.md 2-3.4 (fraud 500x more common than real)"},
        },
        "note": "scenarios 'low' = every input against the queue (pessimistic), 'high' = every input for it (optimistic).",
    }
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"derived": result["derived"], "scenarios": {k: {x: v[x] for x in ("savedPerConfirmedMuleRs", "reviewCostRs", "breakevenPrecisionPerAlert", "breakevenPrecisionWithFixedCost", "mulesCaughtPerYearAtBreakeven")} for k, v in result["scenarios"].items()}, "monteCarlo": result["monteCarlo"]}, indent=1))


if __name__ == "__main__":
    main()
