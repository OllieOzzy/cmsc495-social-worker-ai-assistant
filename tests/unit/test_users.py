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


def test_list_users_maps_public_rows_without_selecting_password_hashes(database):
    """The management list must not load or serialize credential material."""
    user_id = uuid4()
    database.execute.return_value.fetchall.return_value = [
        (str(user_id), "user", "User", "user", 0, datetime.now(UTC).isoformat())
    ]
    result = users.list_users(Path("unused.db"), limit=10, offset=20)
    assert result[0].user_id == user_id
    assert result[0].is_active is False
    assert "password_hash" not in result[0].model_dump()
    sql, parameters = database.execute.call_args.args
    assert "password_hash" not in sql
    assert parameters == ("", "", 10, 20)


def test_account_search_is_bound_and_casefolded(database):
    """Keep search text out of SQL, including quotes and literal wildcards."""
    database.execute.return_value.fetchall.return_value = []
    users.list_users(Path("unused.db"), search="  STRAẞE_%'  ")
    sql, parameters = database.execute.call_args.args
    assert "STRAẞE" not in sql
    assert parameters == ("strasse_%'", "strasse_%'", 25, 0)


def test_storage_rejects_oversized_account_search(database):
    """Bound search length for internal callers as well as HTTP clients."""
    with pytest.raises(ValueError, match="200 characters"):
        users.list_users(Path("unused.db"), search="x" * 201)
    database.execute.assert_not_called()


@pytest.mark.parametrize("limit, offset", [(0, 0), (101, 0), (25, -1)])
def test_list_users_rejects_unbounded_storage_queries(database, limit, offset):
    """Even internal callers must supply a bounded account page."""
    with pytest.raises(ValueError, match="page bounds"):
        users.list_users(Path("unused.db"), limit=limit, offset=offset)
    database.execute.assert_not_called()
