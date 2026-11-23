"""Verify attribution, privacy, and transactional audit history with real accounts."""

import sqlite3
from contextlib import contextmanager
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import audit
from documentation_assistant.backend.db.audit import list_audit_events
from documentation_assistant.backend.db.connection import connect, initialize_database
from tests.integration.test_user_management_api import PASSWORD
from tests.integration.test_user_management_api import accounts as _management_accounts

accounts = _management_accounts


def history(accounts, **params):
    """Read only through the real administrator-protected route."""
    response = accounts.client.get(
        "/users/audit-events", params=params, headers=accounts.headers["admin"]
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_successful_account_actions_record_actor_target_and_only_public_changes(
    accounts,
):
    """Every management mutation records its authenticated actor and stable target ID."""
    admin = str(accounts.identities["admin"].user_id)
    created = accounts.client.post(
        "/users",
        json={
            "username": "new-user",
            "display_name": "New User",
            "password": PASSWORD,
        },
        headers=accounts.headers["admin"],
    )
    assert created.status_code == 201
    target = created.json()["user_id"]
    for method, suffix, payload in [
        ("PATCH", "/profile", {"username": "renamed-user", "display_name": "Renamed"}),
        ("PATCH", "", {"is_active": False}),
        ("PATCH", "", {"is_active": True}),
        ("PATCH", "/role", {"role": "admin"}),
        ("POST", "/reset-password", {"password": "Replacement audit test password!"}),
    ]:
        response = accounts.client.request(
            method,
            f"/users/{target}{suffix}",
            json=payload,
            headers=accounts.headers["admin"],
        )
        assert response.status_code == 200
    events = history(accounts, target_id=target)
    assert [event["action"] for event in events] == [
        "password_reset",
        "role_changed",
        "account_activated",
        "account_deactivated",
        "account_renamed",
        "account_created",
    ]
    assert all(
        event["actor_id"] == admin and event["actor_username"] == "admin"
        for event in events
    )
    assert all(event["target_id"] == target for event in events)
    assert events[0]["changes"] == {}
    assert events[1]["changes"] == {"role": {"before": "user", "after": "admin"}}
    assert events[-2]["changes"]["username"] == {
        "before": "new-user",
        "after": "renamed-user",
    }
    assert events[-1]["target_username"] == "new-user"
    assert events[-2]["target_username"] == "renamed-user"
    serialized = str(events)
    assert (
        PASSWORD not in serialized
        and "Replacement audit test password!" not in serialized
    )
    assert "$argon2" not in serialized and "access_token" not in serialized
    assert all(event["occurred_at"].endswith("Z") for event in events)


def test_self_service_password_change_is_attributed_without_credential_values(accounts):
    """The actor and target are the signed-in user, with no before/after password data."""
    user = str(accounts.identities["user"].user_id)
    response = accounts.client.post(
        "/auth/change-password",
        json={
            "current_password": PASSWORD,
            "new_password": "Private replacement audit password!",
        },
        headers=accounts.headers["user"],
    )
    assert response.status_code == 204
    event = history(accounts, target_id=user)[0]
    assert event["action"] == "password_changed"
    assert event["actor_id"] == event["target_id"] == user
    assert event["changes"] == {}


def test_local_setup_and_existing_history_survive_reinitialization(accounts):
    """CLI-style provisioning has no fabricated actor, and startup does not duplicate events."""
    before = history(accounts)
    assert len(before) == 2
    assert all(
        event["action"] == "account_created"
        and event["actor_id"] is None
        and event["actor_username"] is None
        for event in before
    )
    initialize_database(accounts.path)
    initialize_database(accounts.path)
    assert history(accounts) == before


def test_username_snapshots_survive_later_actor_rename(accounts):
    """Historical attribution remains readable after an administrator changes their login name."""
    target = str(accounts.identities["user"].user_id)
    accounts.client.patch(
        f"/users/{target}/profile",
        json={"display_name": "Edited"},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    before = history(accounts, target_id=target)[0]
    accounts.client.patch(
        f"/users/{accounts.identities['admin'].user_id}/profile",
        json={"username": "renamed-admin"},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    token = accounts.client.post(
        "/auth/login", json={"username": "renamed-admin", "password": PASSWORD}
    ).json()["access_token"]
    accounts.headers["admin"] = {"Authorization": f"Bearer {token}"}
    assert history(accounts, target_id=target)[0] == before
    assert before["actor_username"] == "admin"


def test_existing_database_gains_empty_history_without_changing_accounts(accounts):
    """An upgrade creates the new table without inventing history for older actions."""
    with connect(accounts.path) as connection:
        before = connection.execute("SELECT * FROM users ORDER BY user_id").fetchall()
        # Only this fixture's temporary database is changed to simulate the old schema.
        connection.execute("DROP TABLE audit_events")
    initialize_database(accounts.path)
    assert history(accounts) == []
    with connect(accounts.path) as connection:
        assert (
            connection.execute("SELECT * FROM users ORDER BY user_id").fetchall()
            == before
        )
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 200
    )


def test_history_survives_trusted_account_cleanup(accounts):
    """Historical IDs and names survive removal of a live account row by maintenance."""
    target = str(accounts.identities["user"].user_id)
    before = history(accounts, target_id=target)
    with connect(accounts.path) as connection:
        connection.execute("DELETE FROM users WHERE user_id = ?", (target,))
    assert history(accounts, target_id=target) == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 401
    )


def test_rejected_and_noop_changes_do_not_create_success_events(accounts):
    """Validation, conflicts, bad credentials, and unchanged fields leave history untouched."""
    before = history(accounts)
    user = str(accounts.identities["user"].user_id)
    for suffix, payload, status in [
        ("/role", {"role": "user"}, 200),
        ("", {"is_active": True}, 200),
        ("/profile", {"username": " USER ", "display_name": "User"}, 200),
        ("/profile", {"username": "admin"}, 409),
        ("/role", {"role": "owner"}, 422),
        ("/profile", {"display_name": "Spoof", "actor_id": user}, 422),
    ]:
        assert (
            accounts.client.patch(
                f"/users/{user}{suffix}",
                json=payload,
                headers=accounts.headers["admin"],
            ).status_code
            == status
        )
    assert (
        accounts.client.post(
            "/auth/change-password",
            json={"current_password": "wrong", "new_password": PASSWORD},
            headers=accounts.headers["user"],
        ).status_code
        == 403
    )
    events = history(accounts)
    assert events[0]["action"] == "password_change_failed"
    assert events[0]["changes"] == {}
    assert events[1:] == before


@pytest.mark.parametrize(
    "operation", ["create", "rename", "status", "role", "reset", "password"]
)
def test_failed_audit_insert_rolls_back_account_and_session_changes(
    accounts, operation
):
    """A successful account change cannot commit without its matching history entry."""
    with connect(accounts.path) as connection:
        before_users = connection.execute(
            "SELECT * FROM users ORDER BY user_id"
        ).fetchall()
        before_sessions = connection.execute(
            "SELECT * FROM user_sessions ORDER BY token_hash"
        ).fetchall()
        connection.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'simulated audit failure'); END""")
    before_events = history(accounts)
    target = str(accounts.identities["user"].user_id)
    method, route, payload, viewer = {
        "create": (
            "POST",
            "/users",
            {"username": "new-user", "display_name": "New", "password": PASSWORD},
            "admin",
        ),
        "rename": (
            "PATCH",
            f"/users/{target}/profile",
            {"username": "renamed-user"},
            "admin",
        ),
        "status": ("PATCH", f"/users/{target}", {"is_active": False}, "admin"),
        "role": ("PATCH", f"/users/{target}/role", {"role": "admin"}, "admin"),
        "reset": (
            "POST",
            f"/users/{target}/reset-password",
            {"password": "Replacement audit password!"},
            "admin",
        ),
        "password": (
            "POST",
            "/auth/change-password",
            {
                "current_password": PASSWORD,
                "new_password": "Replacement audit password!",
            },
            "user",
        ),
    }[operation]
    with pytest.raises(sqlite3.IntegrityError, match="audit failure"):
        accounts.client.request(
            method, route, json=payload, headers=accounts.headers[viewer]
        )
    with connect(accounts.path) as connection:
        assert (
            connection.execute("SELECT * FROM users ORDER BY user_id").fetchall()
            == before_users
        )
        assert (
            connection.execute(
                "SELECT * FROM user_sessions ORDER BY token_hash"
            ).fetchall()
            == before_sessions
        )
    assert history(accounts) == before_events


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
def test_history_requires_an_administrator(accounts, viewer, status):
    """Regular users cannot read account history even when filtering to themselves."""
    assert (
        accounts.client.get(
            "/users/audit-events",
            params={"target_id": str(accounts.identities["user"].user_id)},
            headers=accounts.headers.get(viewer, {}),
        ).status_code
        == status
    )


@pytest.mark.parametrize("scope", ["all", "user", "missing"])
def test_audit_query_plan_and_pagination_match_requested_scope(
    accounts, monkeypatch, scope
):
    """Filter interleaved real events before paging and use the target index without sorting."""
    for index in range(6):
        target = accounts.identities["user" if index % 2 else "admin"].user_id
        accounts.client.patch(
            f"/users/{target}/profile",
            json={"display_name": f"Updated {index}"},
            headers=accounts.headers["admin"],
        ).raise_for_status()
    all_events = history(accounts)
    target_id = (
        None
        if scope == "all"
        else (accounts.identities["user"].user_id if scope == "user" else uuid4())
    )
    expected = [
        event
        for event in all_events
        if target_id is None or event["target_id"] == str(target_id)
    ]
    statements = []

    @contextmanager
    def traced_connect(path):
        """Capture the SQL used by the real API handler without replacing its results."""
        with connect(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(audit, "connect", traced_connect)
    params = {"limit": 2, "offset": 1}
    if target_id is not None:
        params["target_id"] = str(target_id)
    assert history(accounts, **params) == expected[1:3]
    sql = next(
        statement for statement in statements if statement.lstrip().startswith("SELECT")
    )
    with connect(accounts.path) as connection:
        plan = " ".join(
            row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql)
        )
    assert "TEMP B-TREE" not in plan
    if target_id is not None:
        assert "SEARCH" in plan and "audit_events_target_id" in plan


def test_history_is_bounded_ordered_filterable_and_read_only(accounts):
    """Stable event IDs order pages; mutation routes are deliberately absent."""
    events = history(accounts)
    assert [event["event_id"] for event in events] == sorted(
        (event["event_id"] for event in events), reverse=True
    )
    assert history(accounts, limit=1, offset=1) == [events[1]]
    assert history(accounts, offset=2) == []
    for params in ({"limit": 101}, {"offset": -1}, {"target_id": "bad-id"}):
        assert (
            accounts.client.get(
                "/users/audit-events", params=params, headers=accounts.headers["admin"]
            ).status_code
            == 422
        )
    for method, status in (("POST", 405), ("PATCH", 422), ("DELETE", 405)):
        assert (
            accounts.client.request(
                method, "/users/audit-events", headers=accounts.headers["admin"]
            ).status_code
            == status
        )
    assert (
        list_audit_events(
            accounts.path, target_id=accounts.identities["admin"].user_id
        )[0].target_username
        == "admin"
    )
