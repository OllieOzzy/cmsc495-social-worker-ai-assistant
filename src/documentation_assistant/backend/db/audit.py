"""Append account events in the caller's transaction and read bounded history."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.audit import (
    AuditAction,
    AuditChange,
    AuditEvent,
    PublicAccountField,
)
from documentation_assistant.backend.schemas.auth import UserAccount

_CHANGES = TypeAdapter(dict[PublicAccountField, AuditChange])


def record_account_event(
    connection: sqlite3.Connection,
    *,
    actor_id: UUID | None,
    target: UserAccount,
    action: AuditAction,
    changes: dict[PublicAccountField, AuditChange] | None = None,
) -> None:
    """Append only allowed public changes without opening or committing a transaction.

    Storage callers supply the authenticated actor ID, never a request-body ID.
    Local CLI and trusted maintenance operations have no authenticated actor.
    Username snapshots preserve attribution after later renames. Password actions
    carry no old or new credential values, hashes, or token metadata.
    Historical IDs deliberately do not reference live rows with foreign keys,
    so trusted account cleanup cannot erase history or block session cleanup.
    """
    safe_changes = _CHANGES.validate_python(changes or {})
    actor = (
        connection.execute(
            "SELECT username FROM users WHERE user_id = ?", (str(actor_id),)
        ).fetchone()
        if actor_id is not None
        else None
    )
    connection.execute(
        """INSERT INTO audit_events
           (occurred_at, actor_id, actor_username, target_id, target_username, action, changes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(UTC).isoformat(),
            str(actor_id) if actor_id else None,
            actor[0] if actor else None,
            str(target.user_id),
            target.username,
            action,
            _CHANGES.dump_json(safe_changes).decode(),
        ),
    )


def list_audit_events(
    path: Path,
    *,
    limit: int = 25,
    offset: int = 0,
    target_id: UUID | None = None,
) -> list[AuditEvent]:
    """Read newest events first, optionally scoped to a stable target account ID."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid audit page bounds.")
    with connect(path) as connection:
        rows = connection.execute(
            """SELECT event_id, occurred_at, actor_id, actor_username,
                      target_id, target_username, action, changes
               FROM audit_events WHERE (? IS NULL OR target_id = ?)
               ORDER BY event_id DESC LIMIT ? OFFSET ?""",
            (
                str(target_id) if target_id else None,
                str(target_id) if target_id else None,
                limit,
                offset,
            ),
        ).fetchall()
    return [
        AuditEvent(
            event_id=row[0],
            occurred_at=row[1],
            actor_id=row[2],
            actor_username=row[3],
            target_id=row[4],
            target_username=row[5],
            action=row[6],
            changes=json.loads(row[7]),
        )
        for row in rows
    ]
