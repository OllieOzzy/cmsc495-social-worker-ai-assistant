"""Verify auth cleanup uses indexes and existing databases gain them safely."""

from contextlib import contextmanager

import pytest

from documentation_assistant.backend.db import sessions, users
from documentation_assistant.backend.db.connection import connect, initialize_database


@pytest.fixture
def database(tmp_path):
    """Provision synthetic storage records without expensive password verification."""
    path = tmp_path / "indexed.db"
    initialize_database(path)
    account = users.create_user(
        path,
        username="user",
        display_name="Synthetic User",
        password_hash="synthetic-encoded-hash",
    )
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO user_sessions VALUES (?, ?, ?, ?)",
            ("old-session", str(account.user_id), 1, 100),
        )
        connection.execute("INSERT INTO login_attempts VALUES ('old-user', 1, 1)")
    return path, account


@pytest.mark.parametrize(
    "operation, prefix, index",
    [
        ("revoke", "DELETE FROM user_sessions WHERE user_id", "user_sessions_user_id"),
        (
            "expire_sessions",
            "DELETE FROM user_sessions WHERE expires_at",
            "user_sessions_expires_at",
        ),
        (
            "expire_attempts",
            "DELETE FROM login_attempts WHERE window_started_at",
            "login_attempts_window_started_at",
        ),
    ],
)
def test_real_cleanup_statements_use_indexes(
    database, monkeypatch, operation, prefix, index
):
    """Explain the actual SQL emitted by storage, rather than a parallel test-only query."""
    path, account = database
    statements = []

    @contextmanager
    def traced_connect(path):
        """Capture SQL while preserving real transactions and schema constraints."""
        with connect(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(sessions, "connect", traced_connect)
    monkeypatch.setattr(users, "connect", traced_connect)
    if operation == "revoke":
        assert not users.set_user_active(
            path, account.user_id, is_active=False
        ).is_active
    elif operation == "expire_sessions":
        assert sessions.save_session(
            path,
            "new-session",
            account.user_id,
            1000,
            2000,
            verified_password_hash=account.password_hash,
            verified_username=account.username,
            verified_role=account.role,
        )
    else:
        assert sessions.reserve_login_attempt(path, "user", 1000) == 0
    sql = next(statement for statement in statements if statement.startswith(prefix))
    with connect(path) as connection:
        plan = " ".join(
            row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql)
        )
        assert "SEARCH" in plan and index in plan
        if operation == "revoke":
            assert (
                connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0]
                == 0
            )
        elif operation == "expire_sessions":
            assert connection.execute(
                "SELECT token_hash FROM user_sessions"
            ).fetchall() == [("new-session",)]
        else:
            assert connection.execute(
                "SELECT username FROM login_attempts"
            ).fetchall() == [("user",)]


def test_existing_database_gains_indexes_without_changing_records(database):
    """Simulate pre-index storage and verify repeated startup preserves its data."""
    path, _ = database
    with connect(path) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("users", "user_sessions", "login_attempts", "audit_events")
        }
        # Drop only the new indexes in this fixture's temporary database.
        connection.execute("DROP INDEX user_sessions_user_id")
        connection.execute("DROP INDEX user_sessions_expires_at")
        connection.execute("DROP INDEX login_attempts_window_started_at")
    initialize_database(path)
    initialize_database(path)
    with connect(path) as connection:
        for table, expected in before.items():
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == expected
        for name, table, column in (
            ("user_sessions_user_id", "user_sessions", "user_id"),
            ("user_sessions_expires_at", "user_sessions", "expires_at"),
            ("login_attempts_window_started_at", "login_attempts", "window_started_at"),
        ):
            indexes = [
                row[1] for row in connection.execute(f"PRAGMA index_list('{table}')")
            ]
            assert indexes.count(name) == 1
            assert [
                row[2] for row in connection.execute(f"PRAGMA index_info('{name}')")
            ] == [column]
