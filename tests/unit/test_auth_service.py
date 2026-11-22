"""Check authentication decisions without running Argon2 or SQLite operations."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.schemas.auth import UserAccount


def test_unknown_account_still_verifies_against_dummy_hash(monkeypatch, tmp_path):
    """Missing usernames must not skip the expensive password verification step."""
    monkeypatch.setattr(service, "reserve_login_attempt", Mock(return_value=0))
    monkeypatch.setattr(service, "get_user_by_username", Mock(return_value=None))
    verify = Mock(return_value=False)
    monkeypatch.setattr(service, "verify_password", verify)
    with pytest.raises(service.InvalidCredentials):
        service.login(tmp_path / "unused.db", " Unknown ", "password")
    verify.assert_called_once_with("password", service._DUMMY_HASH)


def test_throttle_prevents_password_work_and_session_creation(monkeypatch, tmp_path):
    """Do not verify credentials or issue tokens while the username is limited."""
    monkeypatch.setattr(service, "reserve_login_attempt", Mock(return_value=42))
    lookup = Mock()
    save = Mock()
    monkeypatch.setattr(service, "get_user_by_username", lookup)
    monkeypatch.setattr(service, "save_session", save)
    with pytest.raises(service.LoginThrottled) as error:
        service.login(tmp_path / "unused.db", "user", "password")
    assert error.value.retry_after == 42
    lookup.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize("token", ["", "short", "a" * 42, "a" * 44])
def test_invalid_session_token_length_skips_database(monkeypatch, tmp_path, token):
    """Malformed tokens cannot trigger a session or account read."""
    lookup = Mock()
    monkeypatch.setattr(service, "get_session_user", lookup)
    with pytest.raises(service.InvalidCredentials):
        service.authenticate_session(tmp_path / "unused.db", token)
    lookup.assert_not_called()


@pytest.mark.parametrize("found", [False, True])
def test_session_authentication_uses_joined_public_identity(
    monkeypatch, tmp_path, found
):
    """Reuse the storage result without a second password-bearing account lookup."""
    account = (
        UserAccount(
            user_id=uuid4(),
            username="user",
            display_name="Current Name",
            created_at=datetime.now(UTC),
        )
        if found
        else None
    )
    lookup = Mock(return_value=account)
    separate_account_read = Mock()
    monkeypatch.setattr(service, "get_session_user", lookup)
    monkeypatch.setattr(service, "get_user_by_id", separate_account_read)
    monkeypatch.setattr(service, "time", lambda: 123)
    path = tmp_path / "unused.db"
    token = "a" * 43
    if found:
        assert service.authenticate_session(path, token) is account
    else:
        with pytest.raises(service.InvalidCredentials):
            service.authenticate_session(path, token)
    lookup.assert_called_once_with(path, service.token_digest(token), 123)
    separate_account_read.assert_not_called()
