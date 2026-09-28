"""Append-only action log shared by the side-effecting tools, mirrored into infra.store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import ACTION_LOG


def record_action(record: dict) -> dict:
    """Write one JSON line to action_log.jsonl and return it (with a timestamp)."""
    stamped = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}
    with open(ACTION_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(stamped) + "\n")
    return stamped
