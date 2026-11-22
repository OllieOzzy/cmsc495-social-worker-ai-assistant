"""Persist hashed session tokens and bounded login attempts in SQLite."""

from pathlib import Path
from uuid import UUID

from documentation_assistant.backend.db.connection import connect

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_WINDOW_SECONDS = 300


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
) -> bool:
    """Save a session only if its verified credential and account are still current.

    Serialize with password resets and deactivation. An in-flight login must
    not create a valid token after its password or login name has changed.
    """
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        account = connection.execute(
            "SELECT password_hash, is_active, username FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if account != (verified_password_hash, 1, verified_username):
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


def get_session_user_id(path: Path, token_hash: str, now: int) -> UUID | None:
    """Return an active account ID only while the stored session is unexpired."""
    with connect(path) as connection:
        row = connection.execute(
            """SELECT s.user_id FROM user_sessions AS s
               JOIN users AS u ON u.user_id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1""",
            (token_hash, now),
        ).fetchone()
    return UUID(row[0]) if row else None


def delete_session(path: Path, token_hash: str) -> None:
    """Revoke exactly one session without affecting other signed-in devices."""
    with connect(path) as connection:
        connection.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,)
        )
