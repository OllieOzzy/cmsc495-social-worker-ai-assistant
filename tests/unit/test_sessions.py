"""Verify session identity resolution reads only public account fields once."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import sessions


@pytest.mark.parametrize("found", [False, True])
def test_session_lookup_uses_one_public_join(monkeypatch, found):
    """Bind the digest and clock while returning either public identity or no session."""
    user_id = uuid4()
    created_at = datetime.now(UTC)
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (
        (str(user_id), "admin", "Current Name", "admin", 1, created_at.isoformat())
        if found
        else None
    )
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(sessions, "connect", connect)
    path = Path("unused.db")
    account = sessions.get_session_user(path, "synthetic-digest", 123)
    connect.assert_called_once_with(path)
    connection.execute.assert_called_once()
    sql, parameters = connection.execute.call_args.args
    assert parameters == ("synthetic-digest", 123)
    assert "JOIN users" in sql
    assert "expires_at > ?" in sql and "is_active = 1" in sql
    assert "password_hash" not in sql
    if found:
        assert account.user_id == user_id
        assert account.username == "admin"
        assert account.display_name == "Current Name"
        assert account.role == "admin"
        assert account.created_at == created_at
        assert "password_hash" not in account.model_dump()
    else:
        assert account is None


@pytest.mark.parametrize(
    "found, matching_owner", [(False, True), (True, False), (True, True)]
)
def test_write_guard_checks_session_and_owner_without_exposing_digest(
    monkeypatch, found, matching_owner
):
    """Only a live session matching the supplied report owner can authorize a write."""
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (1,) if found else None
    user_id = uuid4()
    guard = sessions.SessionWriteGuard(user_id, "private-token-digest")
    assert "private-token-digest" not in repr(guard)
    monkeypatch.setattr(sessions, "time", lambda: 1000)
    owner_id = user_id if matching_owner else uuid4()
    if found and matching_owner:
        sessions.require_write_session(connection, guard, owner_id)
    else:
        with pytest.raises(sessions.InvalidWriteSession):
            sessions.require_write_session(connection, guard, owner_id)
    assert connection.execute.call_args_list[0].args == ("BEGIN IMMEDIATE",)
    assert connection.execute.call_args_list[1].args[1] == (
        guard.token_hash,
        str(user_id),
        1000,
    )
