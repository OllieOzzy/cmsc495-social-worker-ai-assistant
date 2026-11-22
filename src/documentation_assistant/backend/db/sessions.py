"""Persist hashed session tokens and bounded login attempts in SQLite."""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from uuid import UUID

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.auth import UserAccount

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_WINDOW_SECONDS = 300


class InvalidWriteSession(ValueError):
    """A request's session no longer authorizes its pending report write."""


@dataclass(frozen=True)
class SessionWriteGuard:
    """Carry a request's account and token digest, never the raw bearer token."""

    user_id: UUID
    token_hash: str = field(repr=False)


def require_write_session(
    connection: sqlite3.Connection,
    guard: SessionWriteGuard,
    owner_id: UUID | None,
) -> None:
    """Lock and revalidate the live session in the report's write transaction.

    Read the clock after acquiring the writer lock. Session revocation and
    account changes cannot commit between this check and the report write.
    The guard must belong to the owner supplied by the authenticated route.
    """
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        """SELECT 1 FROM user_sessions AS s JOIN users AS u ON u.user_id = s.user_id
           WHERE s.token_hash = ? AND s.user_id = ?
             AND s.expires_at > ? AND u.is_active = 1""",
        (guard.token_hash, str(guard.user_id), int(time())),
    ).fetchone()
    if row is None or owner_id != guard.user_id:
        raise InvalidWriteSession("Invalid or expired session. Please sign in.")


def reserve_login_attempt(path: Path, username: str, now: int) -> int:
    """Count an attempt atomically; return seconds to wait if already limited.

    Reserve before password verification so concurrent requests cannot all
    bypass the counter. Successful authentication clears this username's row.
    """
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM login_attempts WHERE window_started_at <= ?",
            (now - LOGIN_WINDOW_SECONDS,),
        )
        row = connection.execute(
            "SELECT failures, window_started_at FROM login_attempts WHERE username = ?",
            (username,),
        ).fetchone()
        if row is not None and row[0] >= LOGIN_ATTEMPT_LIMIT:
            return max(1, row[1] + LOGIN_WINDOW_SECONDS - now)
        connection.execute(
            """INSERT INTO login_attempts (username, failures, window_started_at)
               VALUES (?, 1, ?)
               ON CONFLICT(username) DO UPDATE SET failures = failures + 1""",
            (username, now),
        )
    return 0


def save_session(
    path: Path,
    token_hash: str,
    user_id: UUID,
    now: int,
    expires_at: int,
    *,
    verified_password_hash: str,
    verified_username: str,
    verified_role: str,
) -> bool:
    """Save a session only if its verified credential and account are still current.

    Serialize with password resets and deactivation. An in-flight login must
    not create a valid token after its password, login name, or role has changed.
    """
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        account = connection.execute(
            "SELECT password_hash, is_active, username, role FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if account != (verified_password_hash, 1, verified_username, verified_role):
            return False
        connection.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            """INSERT INTO user_sessions (token_hash, user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (token_hash, str(user_id), now, expires_at),
        )
        connection.execute(
            """DELETE FROM login_attempts WHERE username =
               (SELECT username FROM users WHERE user_id = ?)""",
            (str(user_id),),
        )
    return True


def get_session_user(path: Path, token_hash: str, now: int) -> UserAccount | None:
    """Resolve a live session and current public identity in one database read.

    Read role and activation from the joined account on every request. Select
    only public account fields; session verification does not need password
    hashes or a second account lookup. Expiry remains an absolute deadline.
    """
    with connect(path) as connection:
        row = connection.execute(
            """SELECT u.user_id, u.username, u.display_name, u.role,
                      u.is_active, u.created_at
               FROM user_sessions AS s
               JOIN users AS u ON u.user_id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1""",
            (token_hash, now),
        ).fetchone()
    if row is None:
        return None
    return UserAccount(
        user_id=row[0],
        username=row[1],
        display_name=row[2],
        role=row[3],
        is_active=row[4],
        created_at=row[5],
    )


def delete_session(path: Path, token_hash: str) -> None:
    """Revoke exactly one session without affecting other signed-in devices."""
    with connect(path) as connection:
        connection.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,)
        )
