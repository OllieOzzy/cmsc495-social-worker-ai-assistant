"""Verify retained authentication failures through real SQLite and admin routes."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from documentation_assistant.backend.db import audit
from documentation_assistant.backend.db.connection import connect, initialize_database
from tests.integration.test_account_audit_api import history
from tests.integration.test_user_management_api import PASSWORD
from tests.integration.test_user_management_api import accounts as _accounts

accounts = _accounts


@pytest.mark.parametrize("username", ["user", "missing-user"])
def test_failed_and_throttled_logins_share_private_admin_history(accounts, username):
    """Known and unknown accounts return identical errors and log no credential data."""
    wrong_password = "Private rejected credential!"
    for _ in range(5):
        response = accounts.client.post(
            "/auth/login",
            json={"username": username.upper(), "password": wrong_password},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password."}
    response = accounts.client.post(
        "/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    events = history(accounts)
    failures = events[:6]
    assert [event["action"] for event in failures] == ["login_throttled"] + [
        "login_failed"
    ] * 5
    target_id = str(accounts.identities["user"].user_id) if username == "user" else None
    assert all(
        event["target_id"] == target_id
        and event["target_username"] == username
        and event["actor_id"] is None
        and event["actor_username"] is None
        and event["changes"] == {}
        and event["occurred_at"].endswith("Z")
        for event in failures
    )
    assert all(
        secret not in str(events)
        for secret in (
            wrong_password,
            PASSWORD,
            "$argon2",
            "access_token",
            "token_hash",
        )
    )
    # Existing read protection also applies to the new event types.
    for viewer, status in ((None, 401), ("user", 403)):
        assert (
            accounts.client.get(
                "/users/audit-events", headers=accounts.headers.get(viewer, {})
            ).status_code
            == status
        )


def test_password_change_failures_are_distinct_and_success_is_not_a_failure(accounts):
    """Shared throttling identifies the attempted operation without logging passwords."""
    before = history(accounts)
    assert len(before) == 2  # Successful setup logins add no failure events.
    for _ in range(5):
        response = accounts.client.post(
            "/auth/change-password",
            headers=accounts.headers["user"],
            json={"current_password": "incorrect", "new_password": PASSWORD},
        )
        assert response.status_code == 403
    response = accounts.client.post(
        "/auth/change-password",
        headers=accounts.headers["user"],
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert response.status_code == 429
    assert [event["action"] for event in history(accounts)[:6]] == [
        "password_change_throttled"
    ] + ["password_change_failed"] * 5


def test_retention_hides_expired_failures_before_paging_and_preserves_account_history(
    accounts, monkeypatch
):
    """Age and count limits affect failures only, including across quiet periods."""
    original = history(accounts)
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    with connect(accounts.path) as connection:
        connection.execute("UPDATE audit_events SET occurred_at = ?", (old,))
    audit.record_authentication_event(accounts.path, "missing-user", "login_failed")
    with connect(accounts.path) as connection:
        connection.execute(
            "UPDATE audit_events SET occurred_at = ? WHERE action = 'login_failed'",
            (old,),
        )
    # Reads hide expired failures even if no new failure has triggered cleanup.
    assert len(history(accounts, limit=1, offset=1)) == 1
    assert len(history(accounts)) == len(original)
    monkeypatch.setattr(audit, "AUTHENTICATION_EVENT_LIMIT", 2)
    for action in ("login_failed", "login_throttled", "password_change_failed"):
        audit.record_authentication_event(accounts.path, "missing-user", action)
    events = history(accounts)
    assert [event["action"] for event in events[:2]] == [
        "password_change_failed",
        "login_throttled",
    ]
    assert [event["event_id"] for event in events[2:]] == [
        event["event_id"] for event in original
    ]
    with connect(accounts.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 4
        )


def test_old_audit_schema_upgrade_preserves_rows_ids_and_sessions(accounts):
    """Upgrade the previous NOT NULL/CHECK constraints without changing stored history."""
    before = history(accounts)
    with connect(accounts.path) as connection:
        connection.execute("ALTER TABLE audit_events RENAME TO original_audit")
        connection.execute("""CREATE TABLE audit_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
            actor_id TEXT, actor_username TEXT, target_id TEXT NOT NULL,
            target_username TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('account_created', 'account_renamed',
                'account_activated', 'account_deactivated', 'role_changed',
                'password_reset', 'password_changed')), changes TEXT NOT NULL)""")
        connection.execute("INSERT INTO audit_events SELECT * FROM original_audit")
        connection.execute("DROP TABLE original_audit")
        connection.execute(
            "UPDATE sqlite_sequence SET seq = 100 WHERE name = 'audit_events'"
        )
    initialize_database(accounts.path)
    initialize_database(accounts.path)
    assert history(accounts) == before
    audit.record_authentication_event(accounts.path, "missing-user", "login_failed")
    assert history(accounts)[0]["event_id"] == 101
    assert history(accounts)[0]["target_id"] is None
    assert history(accounts)[1:] == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


def test_audit_write_failure_does_not_issue_session_or_erase_history(accounts):
    """A failed failure-log insert propagates while the throttle reservation remains."""
    before = history(accounts)
    with connect(accounts.path) as connection:
        sessions = connection.execute("SELECT * FROM user_sessions").fetchall()
        connection.execute("""CREATE TRIGGER fail_auth_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'simulated logging failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="logging failure"):
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": "incorrect"}
        )
    assert history(accounts) == before
    with connect(accounts.path) as connection:
        assert connection.execute("SELECT * FROM user_sessions").fetchall() == sessions
        assert connection.execute(
            "SELECT failures FROM login_attempts WHERE username = 'user'"
        ).fetchone() == (1,)
