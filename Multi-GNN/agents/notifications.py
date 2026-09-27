"""Real-time SMS alerts to on-call officers via Twilio.

Uses Twilio's REST API directly over `requests` - no extra SDK dependency. If the
`TWILIO_*` env vars aren't set the call runs "dry": the message is written to
action_log.jsonl and reported as `delivery: "dry_run"`, so the demo works without
a Twilio account.

Env vars (all three of the first group required for real delivery):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_FROM_NUMBER        the Twilio number to send from, E.164
    OFFICER_PHONE_NUMBERS     comma-separated E.164 recipients
"""

from __future__ import annotations

import requests

from .audit import record_action
from .config import (
    OFFICER_PHONE_NUMBERS,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
)

_ENDPOINT = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
_MAX_BODY = 1500


def _configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


def send_sms(body: str, to_numbers: list[str] | None = None) -> dict:
    """Send `body` to each recipient. Returns a delivery report."""
    recipients = [n for n in (to_numbers or OFFICER_PHONE_NUMBERS) if n]
    body = body.strip()[:_MAX_BODY]

    if not recipients:
        return {
            "delivery": "no_recipients",
            "reason": "pass to_numbers or set OFFICER_PHONE_NUMBERS",
            "body": body,
        }

    if not _configured():
        record_action(
            {"action": "notify_officer", "delivery": "dry_run", "recipients": recipients,
             "body": body, "simulated": True}
        )
        return {
            "delivery": "dry_run",
            "reason": "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER not set",
            "recipients": recipients,
            "body": body,
        }

    url = _ENDPOINT.format(sid=TWILIO_ACCOUNT_SID)
    results = []
    for number in recipients:
        try:
            response = requests.post(
                url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={"From": TWILIO_FROM_NUMBER, "To": number, "Body": body},
                timeout=15,
            )
            payload = response.json() if response.content else {}
            if response.status_code >= 400:
                results.append(
                    {"to": number, "status": "failed",
                     "error": payload.get("message", response.text[:200])}
                )
            else:
                results.append(
                    {"to": number, "status": payload.get("status", "queued"),
                     "sid": payload.get("sid")}
                )
        except requests.RequestException as error:
            results.append({"to": number, "status": "failed", "error": str(error)})

    record_action({"action": "notify_officer", "delivery": "sent", "results": results, "body": body})
    return {"delivery": "sent", "results": results, "body": body}
