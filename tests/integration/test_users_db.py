"""Exercise account constraints and persistence in the same SQLite file as reports."""

import sqlite3
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import (
    DuplicateUsername,
    create_user,
    get_draft,
    get_user_by_id,
    get_user_by_username,
    save_draft,
)
from documentation_assistant.backend.db.connection import connect, initialize_database
from documentation_assistant.backend.schemas.reports import DraftSections


@pytest.fixture
def database_path(tmp_path):
    """Create both report and account tables without touching the user's database."""
    path = tmp_path / "data" / "dap.db"
    initialize_database(path)
    return path


@pytest.mark.parametrize("role", ["user", "admin"])
def test_created_account_is_persisted_and_can_be_retrieved(database_path, role):
    """Round-trip account identity and its encoded hash through separate connections."""
    account = create_user(
        database_path,
        username=" Demo.User ",
        display_name="Demo User",
        password_hash="synthetic-encoded-hash",
        role=role,
    )

    assert get_user_by_username(database_path, "DEMO.USER") == account
    assert get_user_by_id(database_path, account.user_id) == account
    assert account.username == "demo.user"
    assert account.is_active is True


@pytest.mark.parametrize("duplicate", ["user", "USER", " user "])
def test_duplicate_username_does_not_replace_existing_account(database_path, duplicate):
    """Case and surrounding whitespace cannot create a second copy of a username."""
    account = create_user(
        database_path,
        username="user",
        display_name="Original User",
        password_hash="original-encoded-hash",
    )

    with pytest.raises(DuplicateUsername, match="Username already exists"):
        create_user(
            database_path,
            username=duplicate,
            display_name="Replacement",
            password_hash="replacement-encoded-hash",
            role="admin",
        )

    assert get_user_by_id(database_path, account.user_id) == account
    with connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_initialization_preserves_existing_reports_and_users(database_path):
    """Repeated startup must not reset accounts or alter saved report contents."""
    report = save_draft(
        database_path,
        "Synthetic source notes.",
        DraftSections(data="", assessment="", plan=""),
    )
    account = create_user(
        database_path,
        username="user",
        display_name="Demo User",
        password_hash="synthetic-encoded-hash",
    )

    initialize_database(database_path)

    assert get_draft(database_path, report.report_id) == report
    assert get_user_by_id(database_path, account.user_id) == account


def test_account_table_is_added_to_an_existing_report_database(tmp_path):
    """Adding account storage must preserve reports created before authentication."""
    path = tmp_path / "existing.db"
    initialize_database(path)
    report = save_draft(
        path, "Existing notes.", DraftSections(data="", assessment="", plan="")
    )
    with connect(path) as connection:
        # Reproduce the prior schema, which had report storage but no users table.
        connection.execute("DROP TABLE users")

    initialize_database(path)

    assert get_draft(path, report.report_id) == report
    with connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("column", "value"),
    [("role", "superuser"), ("is_active", 2), ("password_hash", " ")],
)
def test_sqlite_rejects_invalid_account_values(database_path, column, value):
    """Database constraints also protect writes that bypass the Pydantic model."""
    account = create_user(
        database_path,
        username="user",
        display_name="Demo User",
        password_hash="synthetic-encoded-hash",
    )
    with pytest.raises(sqlite3.IntegrityError), connect(database_path) as connection:
        # Column names come only from this fixed test parameter list.
        connection.execute(f"UPDATE users SET {column} = ?", (value,))

    assert get_user_by_id(database_path, account.user_id) == account
    assert get_user_by_id(database_path, uuid4()) is None
