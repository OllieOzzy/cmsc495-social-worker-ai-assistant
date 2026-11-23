"""Describe account audit records using an explicit allowlist of public fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

AuthenticationAction = Literal[
    "login_failed",
    "login_throttled",
    "password_change_failed",
    "password_change_throttled",
]
AuditAction = (
    AuthenticationAction
    | Literal[
        "account_created",
        "account_renamed",
        "account_activated",
        "account_deactivated",
        "role_changed",
        "password_reset",
        "password_changed",
    ]
)
PublicAccountField = Literal["username", "display_name", "role", "is_active"]


class AuditChange(BaseModel):
    """Record public values before and after a successful change."""

    model_config = ConfigDict(extra="forbid", strict=True)
    before: str | bool | None
    after: str | bool | None


class AuditEvent(BaseModel):
    """Expose an account action or authentication attempt without secret values.

    Authentication targets reflect the submitted username, which may not exist.
    An unknown target has no account ID; an attempt does not identify its sender.
    """

    model_config = ConfigDict(extra="forbid")
    event_id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_username: str | None
    target_id: UUID | None
    target_username: str
    action: AuditAction
    changes: dict[PublicAccountField, AuditChange]
