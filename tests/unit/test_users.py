"""Verify account SQL binding, row mapping, and error handling without SQLite I/O."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import users


@pytest.fixture
def database(monkeypatch):
    """Expose the connection inside the storage module's context manager."""
    connection = MagicMock()
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(users, "connect", connect)
    return connection


def test_create_user_binds_normalized_values_and_encoded_hash(database):
    """Keep account values bound separately from the SQL statement."""
    account = users.create_user(
        Path("unused.db"),
        username=" USER ",
        display_name=" Demo User ",
        password_hash="synthetic-encoded-hash",
    )

    sql, values = database.execute.call_args.args
    assert "INSERT INTO users" in sql
    assert "synthetic-encoded-hash" not in sql
    assert values == (
        str(account.user_id),
        "user",
        "Demo User",
        "synthetic-encoded-hash",
        "user",
        1,
        account.created_at.isoformat(),
    )


@pytest.mark.parametrize("lookup", ["username", "id"])
def test_lookup_maps_saved_account_and_inactive_flag(database, lookup):
    """Read disabled accounts without dropping the flag needed by later login checks."""
    user_id = uuid4()
    created_at = datetime.now(UTC)
    database.execute.return_value.fetchone.return_value = (
        str(user_id),
        "admin",
        "Demo Admin",
        "synthetic-encoded-hash",
        "admin",
        0,
        created_at.isoformat(),
    )
    if lookup == "username":
        account = users.get_user_by_username(Path("unused.db"), " ADMIN ")
        expected = ("admin",)
    else:
        account = users.get_user_by_id(Path("unused.db"), user_id)
        expected = (str(user_id),)

    assert account.user_id == user_id
    assert account.role == "admin"
    assert account.is_active is False
    assert account.created_at == created_at
    assert account.password_hash == "synthetic-encoded-hash"
    assert database.execute.call_args.args[1] == expected


@pytest.mark.parametrize("lookup", ["username", "id"])
def test_missing_account_returns_none(database, lookup):
    """Missing accounts must remain distinguishable from disabled accounts."""
    database.execute.return_value.fetchone.return_value = None
    if lookup == "username":
        account = users.get_user_by_username(Path("unused.db"), "missing")
    else:
        account = users.get_user_by_id(Path("unused.db"), uuid4())

    assert account is None


def test_unrelated_integrity_failure_is_not_reported_as_duplicate_username(database):
    """Keep non-uniqueness database errors visible for diagnosis."""
    failure = sqlite3.IntegrityError("CHECK constraint failed")
    failure.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_CHECK
    database.execute.side_effect = failure

    with pytest.raises(sqlite3.IntegrityError) as caught:
        users.create_user(
            Path("unused.db"),
            username="user",
            display_name="Demo User",
            password_hash="synthetic-encoded-hash",
        )
    assert caught.value is failure
