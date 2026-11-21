"""Check authentication decisions without running Argon2 or SQLite operations."""

from unittest.mock import Mock

import pytest

from documentation_assistant.backend.auth import service


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
