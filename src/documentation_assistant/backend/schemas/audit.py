"""Describe account audit records using an explicit allowlist of public fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

AuditAction = Literal[
    "account_created",
    "account_renamed",
    "account_activated",
    "account_deactivated",
    "role_changed",
    "password_reset",
    "password_changed",
]
PublicAccountField = Literal["username", "display_name", "role", "is_active"]


class AuditChange(BaseModel):
    """Record public values before and after a successful change."""

    model_config = ConfigDict(extra="forbid", strict=True)
    before: str | bool | None
    after: str | bool | None


class AuditEvent(BaseModel):
    """Expose a committed account action, excluding credentials and session data."""

    model_config = ConfigDict(extra="forbid")
    event_id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_username: str | None
    target_id: UUID
    target_username: str
    action: AuditAction
    changes: dict[PublicAccountField, AuditChange]
