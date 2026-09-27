"""HTTP client for the GNN inference bridge (bridge_api.py).

Only the three routes the bridge actually exposes: /health, POST /predict,
GET /stream (an SSE replay of scored synthetic transactions).
"""

from __future__ import annotations

import json
import time

import requests

from .config import BRIDGE_URL


class BridgeUnavailable(RuntimeError):
    """The FastAPI bridge could not be reached."""


def _unreachable(error: Exception) -> BridgeUnavailable:
    return BridgeUnavailable(
        f"GNN inference bridge not reachable at {BRIDGE_URL}. "
        f"Start it from Multi-GNN/ with:  python bridge_api.py   ({error})"
    )


def health() -> dict:
    try:
        response = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        raise _unreachable(error) from error


def predict(payload: dict) -> dict:
    try:
        response = requests.post(f"{BRIDGE_URL}/predict", json=payload, timeout=90)
    except requests.RequestException as error:
        raise _unreachable(error) from error
    if response.status_code >= 400:
        raise RuntimeError(f"/predict returned {response.status_code}: {response.text[:500]}")
    return response.json()


def collect_stream(max_seconds: float = 6.0, max_events: int = 25) -> list[dict]:
    """Read the /stream SSE replay for a few seconds and return the parsed events."""
    events: list[dict] = []
    deadline = time.monotonic() + max_seconds
    try:
        with requests.get(
            f"{BRIDGE_URL}/stream",
            stream=True,
            headers={"Accept": "text/event-stream"},
            timeout=(3.05, max_seconds + 3),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    try:
                        events.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        pass
                if len(events) >= max_events or time.monotonic() >= deadline:
                    break
    except requests.RequestException as error:
        raise _unreachable(error) from error
    return events
