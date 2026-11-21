"""Verify admin password reset, atomic revocation, and in-flight login protection."""

import sqlite3
from uuid import uuid4

import pytest

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.auth.passwords import (
    hash_password,
    verify_password,
)
from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.users import (
    get_user_by_username,
    reset_user_password,
    set_user_active,
)
from documentation_assistant.backend.schemas.reports import DraftSections
from tests.integration.test_user_management_api import PASSWORD
from tests.integration.test_user_management_api import accounts as _management_accounts

# Reuse the real login/database fixture without replacing authentication dependencies.
accounts = _management_accounts

NEW_PASSWORD = "A new synthetic reset password!"


def reset_url(accounts, name="user"):
    """Address a fixture account by its stable ID, preserving username independence."""
    return f"/users/{accounts.identities[name].user_id}/reset-password"


def test_reset_openapi_password_example_matches_policy(accounts):
    """Swagger's suggested password must satisfy the endpoint's password policy."""
    schema = accounts.client.get("/openapi.json").json()
    password_schema = schema["components"]["schemas"]["ResetPasswordRequest"][
        "properties"
    ]["password"]
    assert password_schema["minLength"] == 15
    assert password_schema["maxLength"] == 1024
    response = accounts.client.post(
        reset_url(accounts),
        json={"password": password_schema["example"]},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
def test_reset_requires_admin(accounts, viewer, status):
    """Knowing the account ID cannot authorize credential replacement."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        reset_url(accounts),
        json={"password": NEW_PASSWORD},
        headers=accounts.headers.get(viewer, {}),
    )
    assert response.status_code == status
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


def test_reset_revokes_all_sessions_and_preserves_identity_and_reports(accounts):
    """Replace only the password; keep ownership and historical approval details."""
    before = get_user_by_username(accounts.path, "user")
    report = save_draft(
        accounts.path,
        "Preserved notes.",
        DraftSections(data="Data.", assessment="Assessment.", plan="Plan."),
        owner_id=before.user_id,
    )
    accounts.client.post(
        f"/reports/{report.report_id}/approve",
        json={"revision": 1},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    approved = get_draft(accounts.path, report.report_id)
    second_token = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()["access_token"]
    response = accounts.client.post(
        reset_url(accounts),
        json={"password": NEW_PASSWORD},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "password" not in response.text
    after = get_user_by_username(accounts.path, "user")
    assert after.model_dump() == before.model_dump()
    assert after.password_hash != before.password_hash
    assert verify_password(NEW_PASSWORD, after.password_hash)
    assert not verify_password(PASSWORD, after.password_hash)
    assert get_draft(accounts.path, report.report_id) == approved
    for headers in (
        accounts.headers["user"],
        {"Authorization": f"Bearer {second_token}"},
    ):
        assert accounts.client.get("/auth/me", headers=headers).status_code == 401
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 200
    )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_reset_preserves_disabled_status(accounts):
    """Credential recovery must not reactivate an account."""
    set_user_active(accounts.path, accounts.identities["user"].user_id, is_active=False)
    response = accounts.client.post(
        reset_url(accounts),
        json={"password": NEW_PASSWORD},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert not response.json()["is_active"]
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": NEW_PASSWORD}
        ).status_code
        == 401
    )


def test_self_reset_revokes_admin_sessions(accounts):
    """The administrator must sign in again after resetting their own password."""
    response = accounts.client.post(
        reset_url(accounts, "admin"),
        json={"password": NEW_PASSWORD},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 401
    )
    logged_in = accounts.client.post(
        "/auth/login", json={"username": "admin", "password": NEW_PASSWORD}
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["role"] == "admin"


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "short-secret"},
        {"password": "a" * 1025},
        {"password": None},
        {"password": NEW_PASSWORD, "role": "admin"},
        {},
    ],
)
def test_invalid_reset_does_not_echo_password_or_change_account(accounts, payload):
    """Validation failures preserve credentials and existing sessions."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        reset_url(accounts), json=payload, headers=accounts.headers["admin"]
    )
    assert response.status_code == 422
    assert NEW_PASSWORD not in response.text
    assert "short-secret" not in response.text
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


def test_reset_missing_account_returns_404(accounts):
    """A reset must not create a missing account implicitly."""
    response = accounts.client.post(
        f"/users/{uuid4()}/reset-password",
        json={"password": NEW_PASSWORD},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 404


def test_reset_clears_failed_login_window(accounts):
    """A recovered credential can be used immediately after login throttling."""
    for _ in range(5):
        assert (
            accounts.client.post(
                "/auth/login", json={"username": "user", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 429
    )
    accounts.client.post(
        reset_url(accounts),
        json={"password": NEW_PASSWORD},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("change", ["reset", "deactivate"])
def test_inflight_login_cannot_issue_token_after_account_change(
    accounts, monkeypatch, change
):
    """Recheck credentials atomically when storing a token after expensive verification."""
    original_verify = service.verify_password
    original_hash = get_user_by_username(accounts.path, "user").password_hash
    replacement = hash_password(NEW_PASSWORD)

    def verify_then_change(password, encoded):
        """Inject the race precisely between verification and session persistence."""
        valid = original_verify(password, encoded)
        if encoded == original_hash and valid:
            if change == "reset":
                reset_user_password(
                    accounts.path,
                    accounts.identities["user"].user_id,
                    password_hash=replacement,
                )
            else:
                set_user_active(
                    accounts.path, accounts.identities["user"].user_id, is_active=False
                )
        return valid

    monkeypatch.setattr(service, "verify_password", verify_then_change)
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 401
    )
    with connect(accounts.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM user_sessions WHERE user_id = ?",
                (str(accounts.identities["user"].user_id),),
            ).fetchone()[0]
            == 0
        )


def test_reset_rolls_back_if_session_revocation_fails(accounts):
    """Password replacement and session removal must commit or roll back together."""
    before = get_user_by_username(accounts.path, "user")
    with connect(accounts.path) as connection:
        connection.execute("""CREATE TRIGGER reject_session_delete BEFORE DELETE ON user_sessions
            BEGIN SELECT RAISE(ABORT, 'simulated revocation failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="revocation failure"):
        reset_user_password(
            accounts.path, before.user_id, password_hash=hash_password(NEW_PASSWORD)
        )
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )
