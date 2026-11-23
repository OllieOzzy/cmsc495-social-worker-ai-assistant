"""Persist account actions and bounded authentication failures in shared history."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
from uuid import UUID

from pydantic import TypeAdapter

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.audit import (
    AuditAction,
    AuditChange,
    AuditEvent,
    AuthenticationAction,
    PublicAccountField,
)
from documentation_assistant.backend.schemas.auth import UserAccount, Username

_CHANGES = TypeAdapter(dict[PublicAccountField, AuditChange])
_AUTH_ACTION = TypeAdapter(AuthenticationAction)
_USERNAME = TypeAdapter(Username)
_AUTH_ACTIONS = get_args(AuthenticationAction)
AUTHENTICATION_RETENTION_DAYS = 30
AUTHENTICATION_EVENT_LIMIT = 10_000


def _authentication_cutoff(now: datetime) -> str:
    """Use the same UTC ISO format as stored audit timestamps."""
    return (now - timedelta(days=AUTHENTICATION_RETENTION_DAYS)).isoformat()


def record_authentication_event(
    path: Path, username: str, action: AuthenticationAction
) -> None:
    """Append a failure and prune only authentication history in one transaction.

    Store the submitted username and its current target ID if it exists, never
    claim the account owner made the attempt. No arbitrary messages, request
    bodies, passwords, or tokens are accepted. Retain at most 10,000 failure
    events from the last 30 days; successful account actions are preserved.
    Logging errors propagate without issuing a session or bypassing checks.
    """
    username = _USERNAME.validate_python(username)
    action = _AUTH_ACTION.validate_python(action)
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        now = datetime.now(UTC)
        connection.execute(
            """INSERT INTO audit_events
               (occurred_at, actor_id, actor_username, target_id, target_username, action, changes)
               VALUES (?, NULL, NULL,
                       (SELECT user_id FROM users WHERE username = ?), ?, ?, '{}')""",
            (now.isoformat(), username, username, action),
        )
        connection.execute(
            """DELETE FROM audit_events
               WHERE action IN (?, ?, ?, ?) AND occurred_at <= ?""",
            (*_AUTH_ACTIONS, _authentication_cutoff(now)),
        )
        connection.execute(
            """DELETE FROM audit_events WHERE event_id IN (
                   SELECT event_id FROM audit_events
                   WHERE action IN (?, ?, ?, ?)
                   ORDER BY event_id DESC LIMIT -1 OFFSET ?
               )""",
            (*_AUTH_ACTIONS, AUTHENTICATION_EVENT_LIMIT),
        )


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
    """Read newest events first, hiding expired authentication events before paging.

    Expired failures are removed on the next authentication event. Hide them
    during quiet periods too, while keeping successful account history visible.
    """
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid audit page bounds.")
    # A direct predicate lets SQLite use the target/event index. The optional
    # ``? IS NULL OR ...`` form forces a scan even when a target is supplied.
    if target_id is None:
        query = """SELECT event_id, occurred_at, actor_id, actor_username,
                          target_id, target_username, action, changes
                   FROM audit_events
                   WHERE action NOT IN (?, ?, ?, ?) OR occurred_at > ?
                   ORDER BY event_id DESC LIMIT ? OFFSET ?"""
        parameters = (
            *_AUTH_ACTIONS,
            _authentication_cutoff(datetime.now(UTC)),
            limit,
            offset,
        )
    else:
        query = """SELECT event_id, occurred_at, actor_id, actor_username,
                          target_id, target_username, action, changes
                   FROM audit_events WHERE target_id = ?
                     AND (action NOT IN (?, ?, ?, ?) OR occurred_at > ?)
                   ORDER BY event_id DESC LIMIT ? OFFSET ?"""
        parameters = (
            str(target_id),
            *_AUTH_ACTIONS,
            _authentication_cutoff(datetime.now(UTC)),
            limit,
            offset,
        )
    with connect(path) as connection:
        rows = connection.execute(query, parameters).fetchall()
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
