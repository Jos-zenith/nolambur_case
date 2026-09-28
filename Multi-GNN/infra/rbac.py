"""Who may do what in the risk console.

Identity is the X-Rail-Actor header, looked up in the user directory below (override
with RAIL_USERS='{"name": "role", ...}'). There is no login: this is authorisation,
not authentication. In production the header would be set by an auth proxy from a
verified session, never by the browser.

    analyst     clear, escalate, investigate, onboarding checks, replay speed / pause
    supervisor  + freeze, file 1930 reports, notify officers, and model overrides:
                clearing an alert the model scored >= 0.9, or releasing an automatic hold
    admin       + restart / reset the engine
"""

from __future__ import annotations

import json
import os

from fastapi import Header, HTTPException

ROLES = ("analyst", "supervisor", "admin")

PERMISSIONS: dict[str, set[str]] = {
    "analyst": {"clear", "escalate", "investigate", "onboarding", "control"},
    "supervisor": {"clear", "escalate", "investigate", "onboarding", "control", "freeze", "file_1930_report", "notify", "override"},
    "admin": {"clear", "escalate", "investigate", "onboarding", "control", "freeze", "file_1930_report", "notify", "override", "restart"},
}

OVERRIDE_SCORE = 0.9

_DEFAULT_USERS = {
    "priya.analyst": "analyst",
    "rahul.analyst": "analyst",
    "meera.supervisor": "supervisor",
    "ops.admin": "admin",
}


def users() -> dict[str, str]:
    raw = os.getenv("RAIL_USERS")
    if raw:
        parsed = json.loads(raw)
        return {k: v for k, v in parsed.items() if v in ROLES}
    return dict(_DEFAULT_USERS)


def role_of(actor: str) -> str | None:
    return users().get(actor)


def can(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())


def minimum_role(permission: str) -> str:
    return next(r for r in ROLES if can(r, permission))


class Principal:
    def __init__(self, actor: str, role: str):
        self.actor, self.role = actor, role

    def require(self, permission: str, what: str | None = None) -> None:
        if not can(self.role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"{what or permission.replace('_', ' ')} needs the {minimum_role(permission)} role; {self.actor} is {self.role}",
            )


def principal(x_rail_actor: str | None = Header(None)) -> Principal:
    """FastAPI dependency: the calling user, or 401."""
    if not x_rail_actor:
        raise HTTPException(status_code=401, detail="missing X-Rail-Actor header")
    role = role_of(x_rail_actor)
    if not role:
        raise HTTPException(status_code=403, detail=f"unknown user {x_rail_actor!r}")
    return Principal(x_rail_actor, role)


def describe() -> dict:
    return {
        "users": [{"actor": a, "role": r} for a, r in users().items()],
        "permissions": {r: sorted(PERMISSIONS[r]) for r in ROLES},
        "overrideScore": OVERRIDE_SCORE,
    }
