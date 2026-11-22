"""Manage account identity and activation in the existing SQLite database."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.schemas.auth import (
    StoredUserAccount,
    UserAccount,
    UserRole,
)


class DuplicateUsername(ValueError):
    """An account already uses the normalized username."""


class AccountStatusConflict(ValueError):
    """An account change would remove the last active administrator."""


class PasswordChangeConflict(ValueError):
    """The verified password or activation changed before the new password was saved."""


def list_users(
    path: Path, *, limit: int = 25, offset: int = 0, search: str = ""
) -> list[UserAccount]:
    """Search public names before pagination without reading password hashes.

    Use literal substring matching, so SQL wildcard characters are ordinary
    search text. Case folding supports display names beyond ASCII usernames.
    """
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid account page bounds.")
    if len(search) > 200:
        raise ValueError("Account search must contain at most 200 characters.")
    search = search.strip().casefold()
    with connect(path) as connection:
        connection.create_function("casefold", 1, str.casefold, deterministic=True)
        rows = connection.execute(
            """SELECT user_id, username, display_name, role, is_active, created_at
               FROM users
               WHERE instr(casefold(username), ?) > 0
                  OR instr(casefold(display_name), ?) > 0
               ORDER BY username LIMIT ? OFFSET ?""",
            (search, search, limit, offset),
        ).fetchall()
    return [_read_public_user(row) for row in rows]


def set_user_active(
    path: Path, user_id: UUID, *, is_active: bool
) -> UserAccount | None:
    """Change activation atomically and revoke sessions when disabling an account.

    Hold the write lock while counting administrators so concurrent requests
    cannot disable the last two at once. Reports and approval history remain.
    Reactivation never restores old sessions; the user must sign in again.
    """
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT user_id, username, display_name, role, is_active, created_at
               FROM users WHERE user_id = ?""",
            (str(user_id),),
        ).fetchone()
        if row is None:
            return None
        account = _read_public_user(row)
        if not is_active and account.is_active and account.role == "admin":
            count = connection.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if count <= 1:
                raise AccountStatusConflict(
                    "The last active administrator cannot be deactivated."
                )
        connection.execute(
            "UPDATE users SET is_active = ? WHERE user_id = ?",
            (int(is_active), str(user_id)),
        )
        if not is_active:
            connection.execute(
                "DELETE FROM user_sessions WHERE user_id = ?", (str(user_id),)
            )
    return account.model_copy(update={"is_active": is_active})


def set_user_role(path: Path, user_id: UUID, *, role: UserRole) -> UserAccount | None:
    """Change permissions and revoke sessions, preserving identity and reports.

    Serialize with activation changes so simultaneous demotions and
    deactivations cannot remove every active administrator. A no-op preserves
    sessions, and promoting an inactive account does not reactivate it.
    """
    if role not in ("user", "admin"):
        raise ValueError("Invalid account role.")
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT user_id, username, display_name, role, is_active, created_at
               FROM users WHERE user_id = ?""",
            (str(user_id),),
        ).fetchone()
        if row is None:
            return None
        account = _read_public_user(row)
        if account.role == role:
            return account
        if account.role == "admin" and account.is_active:
            count = connection.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if count <= 1:
                raise AccountStatusConflict(
                    "The last active administrator cannot be demoted."
                )
        connection.execute(
            "UPDATE users SET role = ? WHERE user_id = ?", (role, str(user_id))
        )
        connection.execute(
            "DELETE FROM user_sessions WHERE user_id = ?", (str(user_id),)
        )
    return account.model_copy(update={"role": role})


def _read_public_user(row: tuple) -> UserAccount:
    """Map identity-only columns without constructing a password-bearing model."""
    user_id, username, display_name, role, is_active, created_at = row
    return UserAccount(
        user_id=user_id,
        username=username,
        display_name=display_name,
        role=role,
        is_active=is_active,
        created_at=created_at,
    )


def reset_user_password(
    path: Path,
    user_id: UUID,
    *,
    password_hash: str,
    verified_password_hash: str | None = None,
    verified_username: str | None = None,
) -> UserAccount | None:
    """Replace an encoded password and revoke all sessions in one transaction.

    The caller validates and hashes the password before entering storage.
    Reset also clears the username's login-attempt window for immediate use
    of the new credential. Identity, role, activation, and reports are preserved.
    Self-service changes supply their verified hash and username so an
    intervening reset, rename, or deactivation cannot be overwritten.
    """
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT user_id, username, display_name, role, is_active, created_at
               FROM users WHERE user_id = ?""",
            (str(user_id),),
        ).fetchone()
        if row is None:
            return None
        account = _read_public_user(row)
        if verified_password_hash is not None:
            current = connection.execute(
                "SELECT password_hash, is_active, username FROM users WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            expected_username = (
                verified_username if verified_username is not None else account.username
            )
            if current != (verified_password_hash, 1, expected_username):
                raise PasswordChangeConflict(
                    "Account changed. Please sign in again before changing your password."
                )
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (password_hash, str(user_id)),
        )
        connection.execute(
            "DELETE FROM user_sessions WHERE user_id = ?", (str(user_id),)
        )
        connection.execute(
            "DELETE FROM login_attempts WHERE username = ?", (account.username,)
        )
    return account


def rename_user(
    path: Path,
    user_id: UUID,
    *,
    username: str | None = None,
    display_name: str | None = None,
) -> UserAccount | None:
    """Rename identity, preserving reports and historical approval snapshots.

    A changed username revokes sessions and clears both login-attempt windows
    atomically. Display-only changes preserve sessions. Uniqueness conflicts
    roll back the whole operation without changing names or revoking tokens.
    """
    try:
        with connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT user_id, username, display_name, role, is_active, created_at
                   FROM users WHERE user_id = ?""",
                (str(user_id),),
            ).fetchone()
            if row is None:
                return None
            current = _read_public_user(row)
            updated = UserAccount.model_validate(
                {
                    **current.model_dump(),
                    "username": username if username is not None else current.username,
                    "display_name": display_name
                    if display_name is not None
                    else current.display_name,
                }
            )
            connection.execute(
                "UPDATE users SET username = ?, display_name = ? WHERE user_id = ?",
                (updated.username, updated.display_name, str(user_id)),
            )
            if updated.username != current.username:
                connection.execute(
                    "DELETE FROM user_sessions WHERE user_id = ?", (str(user_id),)
                )
                connection.execute(
                    "DELETE FROM login_attempts WHERE username IN (?, ?)",
                    (current.username, updated.username),
                )
        return updated
    except sqlite3.IntegrityError as exc:
        if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
            raise DuplicateUsername("Username already exists.") from exc
        raise


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
