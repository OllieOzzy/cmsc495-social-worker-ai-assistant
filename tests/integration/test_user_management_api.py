"""Exercise admin account management with real credentials and temporary SQLite."""

from concurrent.futures import ThreadPoolExecutor
from functools import cache
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.auth.passwords import (
    hash_password,
    verify_password,
)
from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import (
    AccountStatusConflict,
    create_user,
    get_user_by_username,
    set_user_active,
)
from documentation_assistant.backend.main import create_app
from documentation_assistant.backend.schemas.reports import DraftSections

PASSWORD = "Synthetic account management password!"


@cache
def encoded_password():
    """Reuse the test hash while retaining real verification at login."""
    return hash_password(PASSWORD)


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    """Provision and sign in a real administrator and a regular user."""
    path = tmp_path / "management.db"
    monkeypatch.setenv("DAP_DB_PATH", str(path))
    with TestClient(create_app()) as client:
        identities, headers = {}, {}
        for name, role in (("admin", "admin"), ("user", "user")):
            identities[name] = create_user(
                path,
                username=name,
                display_name=name.title(),
                password_hash=encoded_password(),
                role=role,
            )
            response = client.post(
                "/auth/login", json={"username": name, "password": PASSWORD}
            )
            response.raise_for_status()
            headers[name] = {
                "Authorization": f"Bearer {response.json()['access_token']}"
            }
        yield SimpleNamespace(
            path=path, client=client, identities=identities, headers=headers
        )


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
@pytest.mark.parametrize(
    "method, route, body",
    [
        ("GET", "/users", None),
        (
            "POST",
            "/users",
            {
                "username": "new-user",
                "display_name": "New User",
                "password": PASSWORD,
                "role": "admin",
            },
        ),
        ("PATCH", "/users/{user_id}", {"is_active": False}),
    ],
)
def test_user_management_requires_an_administrator(
    accounts, viewer, status, method, route, body
):
    """Neither public signup nor regular-user account administration is allowed."""
    route = route.format(user_id=accounts.identities["user"].user_id)
    response = accounts.client.request(
        method, route, json=body, headers=accounts.headers.get(viewer, {})
    )
    assert response.status_code == status
    assert get_user_by_username(accounts.path, "new-user") is None
    assert get_user_by_username(accounts.path, "user").is_active


def test_listing_is_paginated_and_never_reads_or_returns_password_hashes(accounts):
    """Only public identity columns are returned, including inactive accounts."""
    set_user_active(accounts.path, accounts.identities["user"].user_id, is_active=False)
    first = accounts.client.get(
        "/users", params={"limit": 1}, headers=accounts.headers["admin"]
    )
    second = accounts.client.get(
        "/users", params={"limit": 1, "offset": 1}, headers=accounts.headers["admin"]
    )
    assert first.status_code == second.status_code == 200
    assert first.json()[0]["username"] == "admin"
    assert second.json()[0]["username"] == "user"
    assert second.json()[0]["is_active"] is False
    assert "password" not in first.text + second.text
    assert PASSWORD not in first.text + second.text
    assert first.headers["cache-control"] == "no-store"
    assert (
        accounts.client.get(
            "/users", params={"offset": 2}, headers=accounts.headers["admin"]
        ).json()
        == []
    )


@pytest.mark.parametrize("role", ["user", "admin"])
def test_admin_creates_normalized_account_with_argon2_hash(accounts, role):
    """Creation returns a public identity and the new credentials work immediately."""
    response = accounts.client.post(
        "/users",
        json={
            "username": " New.User ",
            "display_name": " New User ",
            "password": PASSWORD,
            "role": role,
        },
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 201
    assert response.json()["username"] == "new.user"
    assert response.json()["display_name"] == "New User"
    assert response.json()["role"] == role
    assert "password" not in response.text
    stored = get_user_by_username(accounts.path, "new.user")
    assert stored.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, stored.password_hash)
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "new.user", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_duplicate_creation_preserves_credentials_and_role(accounts):
    """Creating an existing username cannot reset its password or grant admin rights."""
    original = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        "/users",
        json={
            "username": " USER ",
            "display_name": "Changed",
            "password": "Different long password!",
            "role": "admin",
        },
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 409
    assert get_user_by_username(accounts.path, "user") == original


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "short-secret"},
        {"password": "a" * 1025},
        {"username": "bad username"},
        {"role": "superuser"},
        {"password": None},
    ],
)
def test_invalid_creation_does_not_echo_credentials_or_create_accounts(
    accounts, changes
):
    """Password policy and sanitized validation protect malformed creation requests."""
    payload = {
        "username": "new-user",
        "display_name": "New User",
        "password": PASSWORD,
        **changes,
    }
    response = accounts.client.post(
        "/users", json=payload, headers=accounts.headers["admin"]
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert "short-secret" not in response.text
    assert get_user_by_username(accounts.path, "new-user") is None


def test_deactivation_preserves_reports_and_reactivation_never_restores_old_sessions(
    accounts,
):
    """Disabled users lose every token and must log in again after reactivation."""
    identity = accounts.identities["user"]
    report = save_draft(
        accounts.path,
        "Preserved source notes.",
        DraftSections(data="", assessment="", plan=""),
        owner_id=identity.user_id,
    )
    url = f"/users/{identity.user_id}"
    # Create a second session so revocation is not limited to one device.
    second = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()["access_token"]
    disabled = accounts.client.patch(
        url, json={"is_active": False}, headers=accounts.headers["admin"]
    )
    assert disabled.status_code == 200
    assert not disabled.json()["is_active"]
    assert get_draft(accounts.path, report.report_id) == report
    for headers in (accounts.headers["user"], {"Authorization": f"Bearer {second}"}):
        assert accounts.client.get("/auth/me", headers=headers).status_code == 401
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        accounts.client.patch(
            url, json={"is_active": True}, headers=accounts.headers["admin"]
        ).status_code
        == 200
    )
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 401
    )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_admin_cannot_deactivate_own_account(accounts):
    """The current administrator cannot lock themselves out from the management UI."""
    response = accounts.client.patch(
        f"/users/{accounts.identities['admin'].user_id}",
        json={"is_active": False},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 409
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 200
    )


def test_missing_account_returns_404(accounts):
    """Status updates must not create missing accounts implicitly."""
    response = accounts.client.patch(
        f"/users/{uuid4()}",
        json={"is_active": False},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"is_active": "false"}, {"is_active": 0}, {"is_active": False, "role": "admin"}],
)
def test_status_payload_requires_a_boolean_and_cannot_change_roles(accounts, payload):
    """Activation and role changes are separate permissions and request schemas."""
    response = accounts.client.patch(
        f"/users/{accounts.identities['user'].user_id}",
        json=payload,
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 422
    assert get_user_by_username(accounts.path, "user").is_active


def test_last_admin_guard_is_atomic_and_rolls_back_failed_changes(accounts):
    """Two simultaneous deactivations cannot remove both active administrators."""
    second = create_user(
        accounts.path,
        username="second-admin",
        display_name="Second Admin",
        password_hash=encoded_password(),
        role="admin",
    )
    targets = [accounts.identities["admin"].user_id, second.user_id]

    def disable(user_id):
        """Exercise trusted storage directly to isolate the concurrent count check."""
        try:
            set_user_active(accounts.path, user_id, is_active=False)
        except AccountStatusConflict:
            return "protected"
        return "disabled"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(disable, targets))
    assert sorted(results) == ["disabled", "protected"]
    with connect(accounts.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            == 1
        )
