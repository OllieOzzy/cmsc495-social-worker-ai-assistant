"""Exercise role authorization, session revocation, and concurrent admin protection."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import (
    AccountStatusConflict,
    create_user,
    get_user_by_id,
    set_user_active,
    set_user_role,
)
from documentation_assistant.backend.schemas.reports import DraftSections
from tests.integration.test_user_management_api import PASSWORD, encoded_password
from tests.integration.test_user_management_api import accounts as _management_accounts

accounts = _management_accounts


def change_role(accounts, name, role, *, headers=None):
    """Submit a role change through the real administrator dependency."""
    return accounts.client.patch(
        f"/users/{accounts.identities[name].user_id}/role",
        json={"role": role},
        headers=accounts.headers["admin"] if headers is None else headers,
    )


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
def test_only_admins_change_roles(accounts, viewer, status):
    """Ordinary accounts cannot promote themselves or other users."""
    response = change_role(
        accounts, "user", "admin", headers=accounts.headers.get(viewer, {})
    )
    assert response.status_code == status
    assert (
        get_user_by_id(accounts.path, accounts.identities["user"].user_id).role
        == "user"
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"role": "owner"}, {"role": None}, {"role": "admin", "is_active": True}],
)
def test_invalid_role_requests_are_rejected(accounts, payload):
    """A role edit cannot also alter activation or accept unknown permissions."""
    response = accounts.client.patch(
        f"/users/{accounts.identities['user'].user_id}/role",
        json=payload,
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 422


def test_promotion_and_demotion_revoke_all_sessions_and_preserve_identity(accounts):
    """Fresh login reflects permissions; existing tokens cannot survive either change."""
    before = accounts.identities["user"]
    report = save_draft(
        accounts.path,
        "Preserved notes.",
        DraftSections(
            data="Observed facts.", assessment="Assessment.", plan="Next session."
        ),
        owner_id=before.user_id,
    )
    approved = accounts.client.post(
        f"/reports/{report.report_id}/approve",
        json={"revision": report.revision},
        headers=accounts.headers["admin"],
    )
    assert approved.status_code == 200
    snapshot = get_draft(accounts.path, report.report_id)
    extra = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()
    response = change_role(accounts, "user", "admin")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {**before.model_dump(mode="json"), "role": "admin"}
    assert (
        get_user_by_id(accounts.path, before.user_id).password_hash
        == before.password_hash
    )
    for headers in (
        accounts.headers["user"],
        {"Authorization": f"Bearer {extra['access_token']}"},
    ):
        assert accounts.client.get("/auth/me", headers=headers).status_code == 401
    login = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()
    promoted = {"Authorization": f"Bearer {login['access_token']}"}
    assert accounts.client.get("/users", headers=promoted).status_code == 200
    assert change_role(accounts, "user", "user").status_code == 200
    assert accounts.client.get("/auth/me", headers=promoted).status_code == 401
    fresh = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()
    assert fresh["user"]["role"] == "user"
    assert get_draft(accounts.path, report.report_id) == snapshot
    assert (
        accounts.client.get(
            "/users", headers={"Authorization": f"Bearer {fresh['access_token']}"}
        ).status_code
        == 403
    )


def test_noop_preserves_sessions_and_missing_account_is_not_found(accounts):
    """Saving the current role does not unexpectedly sign someone out."""
    assert change_role(accounts, "user", "user").status_code == 200
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )
    assert (
        accounts.client.patch(
            f"/users/{uuid4()}/role",
            json={"role": "admin"},
            headers=accounts.headers["admin"],
        ).status_code
        == 404
    )


def test_last_active_admin_cannot_be_demoted_even_with_inactive_admin(accounts):
    """An inactive administrator cannot provide recovery access."""
    set_user_active(accounts.path, accounts.identities["user"].user_id, is_active=False)
    assert change_role(accounts, "user", "admin").status_code == 200
    assert not get_user_by_id(
        accounts.path, accounts.identities["user"].user_id
    ).is_active
    response = change_role(accounts, "admin", "user")
    assert response.status_code == 409
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 200
    )


def test_self_demotion_requires_another_active_admin(accounts):
    """An admin may step down once another active administrator exists."""
    assert change_role(accounts, "user", "admin").status_code == 200
    assert change_role(accounts, "admin", "user").status_code == 200
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 401
    )


def test_login_verified_before_role_change_cannot_issue_session(accounts, monkeypatch):
    """Recheck the verified role under the same write lock as session creation."""
    original = service.verify_password

    def verify_then_promote(password, encoded):
        valid = original(password, encoded)
        set_user_role(accounts.path, accounts.identities["user"].user_id, role="admin")
        return valid

    monkeypatch.setattr(service, "verify_password", verify_then_promote)
    response = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    )
    assert response.status_code == 401
    with connect(accounts.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM user_sessions WHERE user_id = ?",
                (str(accounts.identities["user"].user_id),),
            ).fetchone()[0]
            == 0
        )


def test_concurrent_demotion_and_deactivation_keep_one_active_admin(accounts):
    """Both operations share SQLite's write lock when protecting the final admin."""
    other = create_user(
        accounts.path,
        username="second-admin",
        display_name="Second",
        password_hash=encoded_password(),
        role="admin",
    )

    def change(operation):
        try:
            if operation == "demote":
                set_user_role(
                    accounts.path, accounts.identities["admin"].user_id, role="user"
                )
            else:
                set_user_active(accounts.path, other.user_id, is_active=False)
            return "changed"
        except AccountStatusConflict:
            return "protected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ("demote", "deactivate"))) == [
            "changed",
            "protected",
        ]
    with connect(accounts.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            == 1
        )


def test_role_change_rolls_back_if_revocation_fails(accounts):
    """Permission updates and token revocation must succeed together."""
    with connect(accounts.path) as connection:
        connection.execute("""CREATE TRIGGER fail_role_revoke BEFORE DELETE ON user_sessions
            BEGIN SELECT RAISE(ABORT, 'simulated revocation failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="revocation failure"):
        set_user_role(accounts.path, accounts.identities["user"].user_id, role="admin")
    assert (
        get_user_by_id(accounts.path, accounts.identities["user"].user_id).role
        == "user"
    )
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )
