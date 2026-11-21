"""Create and retrieve accounts in the application's existing SQLite database."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.auth import StoredUserAccount, UserRole


class DuplicateUsername(ValueError):
    """An account already uses the normalized username."""


def create_user(
    path: Path,
    *,
    username: str,
    display_name: str,
    password_hash: str,
    role: UserRole = "user",
) -> StoredUserAccount:
    """Save an account with an already encoded hash and return it after commit.

    Call initialize_database before account operations. The caller must hash
    the password first; this storage function never accepts a password field.
    """
    account = StoredUserAccount(
        user_id=uuid4(),
        username=username,
        display_name=display_name,
        password_hash=password_hash,
        role=role,
        created_at=datetime.now(UTC),
    )
    try:
        with connect(path) as connection:
            connection.execute(
                """
                INSERT INTO users
                    (user_id, username, display_name, password_hash, role,
                     is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(account.user_id),
                    account.username,
                    account.display_name,
                    account.password_hash,
                    account.role,
                    int(account.is_active),
                    account.created_at.isoformat(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        # Translate only a uniqueness violation, not unrelated storage failures.
        if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
            raise DuplicateUsername("Username already exists.") from exc
        raise
    return account


def get_user_by_username(path: Path, username: str) -> StoredUserAccount | None:
    """Find an account using the same normalization as account creation."""
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT user_id, username, display_name, password_hash, role,
                   is_active, created_at
            FROM users WHERE username = ?
            """,
            (username.strip().lower(),),
        ).fetchone()
    return _read_user(row)


def get_user_by_id(path: Path, user_id: UUID) -> StoredUserAccount | None:
    """Find an account by its stable ID, or return None when it is missing."""
    with connect(path) as connection:
        row = connection.execute(
            """
            SELECT user_id, username, display_name, password_hash, role,
                   is_active, created_at
            FROM users WHERE user_id = ?
            """,
            (str(user_id),),
        ).fetchone()
    return _read_user(row)


def _read_user(row: tuple | None) -> StoredUserAccount | None:
    """Convert SQLite's integer flag and stored identity into a validated account."""
    if row is None:
        return None
    user_id, username, display_name, password_hash, role, is_active, created_at = row
    return StoredUserAccount(
        user_id=user_id,
        username=username,
        display_name=display_name,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
        created_at=created_at,
    )
