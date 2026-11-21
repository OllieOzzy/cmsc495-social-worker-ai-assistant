"""Authenticate accounts and issue revocable, expiring opaque bearer tokens."""

import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path
from time import time

from documentation_assistant.backend.auth.passwords import (
    hash_password,
    verify_password,
)
from documentation_assistant.backend.db.sessions import (
    delete_session,
    get_session_user_id,
    reserve_login_attempt,
    save_session,
)
from documentation_assistant.backend.db.users import (
    get_user_by_id,
    get_user_by_username,
)
from documentation_assistant.backend.schemas.auth import LoginResponse, UserAccount

SESSION_LIFETIME_SECONDS = 8 * 60 * 60
# Unknown usernames still perform a real password verification. Never use this
# random, process-local value as an account credential.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class InvalidCredentials(ValueError):
    """Credentials or a session cannot authenticate an active account."""


class LoginThrottled(ValueError):
    """The username has exhausted its current login-attempt window."""

    def __init__(self, retry_after: int):
        super().__init__("Too many login attempts. Try again later.")
        self.retry_after = retry_after


def token_digest(token: str) -> str:
    """Hash a high-entropy token before using it in storage or lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def login(path: Path, username: str, password: str) -> LoginResponse:
    """Verify credentials, applying the same throttle to known and unknown users."""
    username = username.strip().lower()
    now = int(time())
    if retry_after := reserve_login_attempt(path, username, now):
        raise LoginThrottled(retry_after)
    account = get_user_by_username(path, username)
    valid = verify_password(password, account.password_hash if account else _DUMMY_HASH)
    if not valid or account is None or not account.is_active:
        raise InvalidCredentials("Invalid username or password.")
    token = secrets.token_urlsafe(32)
    # Start the lifetime after password verification has completed.
    now = int(time())
    expires_at = now + SESSION_LIFETIME_SECONDS
    save_session(path, token_digest(token), account.user_id, now, expires_at)
    return LoginResponse(
        access_token=token,
        expires_at=datetime.fromtimestamp(expires_at, UTC),
        user=UserAccount.model_validate(account.model_dump()),
    )


def authenticate_session(path: Path, token: str) -> UserAccount:
    """Resolve a live token and reread current account status and role each time."""
    if len(token) != 43:
        raise InvalidCredentials("Invalid or expired session.")
    user_id = get_session_user_id(path, token_digest(token), int(time()))
    account = get_user_by_id(path, user_id) if user_id is not None else None
    if account is None or not account.is_active:
        raise InvalidCredentials("Invalid or expired session.")
    return UserAccount.model_validate(account.model_dump())


def logout(path: Path, token: str) -> None:
    """Revoke the supplied session so its token cannot be reused."""
    delete_session(path, token_digest(token))
