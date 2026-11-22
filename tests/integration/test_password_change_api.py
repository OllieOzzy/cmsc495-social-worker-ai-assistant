"""Exercise current-password verification and atomic self-service credential changes."""

import pytest

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.auth.passwords import (
    hash_password,
    verify_password,
)
from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.db.users import (
    create_user,
    get_user_by_username,
    reset_user_password,
    set_user_active,
)
from documentation_assistant.backend.schemas.reports import DraftSections
from tests.integration.test_user_management_api import PASSWORD
from tests.integration.test_user_management_api import accounts as _management_accounts

accounts = _management_accounts
NEW_PASSWORD = "A new self-service test password!"
URL = "/auth/change-password"


def test_change_requires_a_live_session(accounts):
    """Current credentials alone do not authorize an unauthenticated change."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        URL, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 401
    assert get_user_by_username(accounts.path, "user") == before


@pytest.mark.parametrize("name", ["user", "admin"])
def test_change_preserves_identity_reports_and_revokes_every_session(accounts, name):
    """Regular users and admins change only their own credentials and must sign in again."""
    before = get_user_by_username(accounts.path, name)
    report = save_draft(
        accounts.path,
        "Preserved notes.",
        DraftSections(data="", assessment="", plan=""),
        owner_id=before.user_id,
    )
    second = accounts.client.post(
        "/auth/login", json={"username": name, "password": PASSWORD}
    ).json()["access_token"]
    response = accounts.client.post(
        URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=accounts.headers[name],
    )
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    after = get_user_by_username(accounts.path, name)
    assert after.model_dump() == before.model_dump()
    assert verify_password(NEW_PASSWORD, after.password_hash)
    assert not verify_password(PASSWORD, after.password_hash)
    assert get_draft(accounts.path, report.report_id) == report
    for headers in (accounts.headers[name], {"Authorization": f"Bearer {second}"}):
        assert accounts.client.get("/auth/me", headers=headers).status_code == 401
    other = "admin" if name == "user" else "user"
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers[other]).status_code
        == 200
    )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": name, "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        accounts.client.post(
            "/auth/login", json={"username": name, "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_wrong_current_password_preserves_session_and_account(accounts):
    """A rejected verification lets the signed-in user correct the input."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        URL,
        json={
            "current_password": "Incorrect private value",
            "new_password": NEW_PASSWORD,
        },
        headers=accounts.headers["user"],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Current password is incorrect."}
    assert "Incorrect private value" not in response.text
    assert NEW_PASSWORD not in response.text
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"new_password": "short-secret"},
        {"new_password": "a" * 1025},
        {"current_password": None},
        {"new_password": None},
        {"user_id": "another-user"},
    ],
)
def test_invalid_payload_cannot_leak_passwords_or_target_another_user(
    accounts, changes
):
    """The session selects the account; rejected bodies never echo secret values."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.post(
        URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD, **changes},
        headers=accounts.headers["user"],
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert NEW_PASSWORD not in response.text
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


def test_current_password_guesses_share_the_login_throttle(accounts, monkeypatch):
    """A live token cannot enable unlimited guesses of the current password."""
    clock = [int(service.time())]
    monkeypatch.setattr(service, "time", lambda: clock[0])
    for _ in range(5):
        assert (
            accounts.client.post(
                URL,
                json={"current_password": "wrong", "new_password": NEW_PASSWORD},
                headers=accounts.headers["user"],
            ).status_code
            == 403
        )
    limited = accounts.client.post(
        URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=accounts.headers["user"],
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "300"
    clock[0] += 300
    assert (
        accounts.client.post(
            URL,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=accounts.headers["user"],
        ).status_code
        == 204
    )


def test_demo_password_can_be_verified_before_setting_a_stronger_password(accounts):
    """The new-password policy must not reject a shorter existing demo credential."""
    create_user(
        accounts.path,
        username="demo-user",
        display_name="Demo User",
        password_hash=hash_password("password1234"),
    )
    signed_in = accounts.client.post(
        "/auth/login", json={"username": "demo-user", "password": "password1234"}
    ).json()
    response = accounts.client.post(
        URL,
        json={"current_password": "password1234", "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {signed_in['access_token']}"},
    )
    assert response.status_code == 204
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "demo-user", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("change", ["reset", "deactivate"])
def test_stale_change_cannot_overwrite_an_intervening_account_change(
    accounts, monkeypatch, change
):
    """An admin reset or deactivation between verification and save must win."""
    original_verify = service.verify_password
    admin_replacement = hash_password("Administrator replacement password!")

    def verify_then_update(password, encoded):
        """Place the competing write immediately after current-password verification."""
        valid = original_verify(password, encoded)
        if valid:
            if change == "reset":
                reset_user_password(
                    accounts.path,
                    accounts.identities["user"].user_id,
                    password_hash=admin_replacement,
                )
            else:
                set_user_active(
                    accounts.path, accounts.identities["user"].user_id, is_active=False
                )
        return valid

    monkeypatch.setattr(service, "verify_password", verify_then_update)
    response = accounts.client.post(
        URL,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=accounts.headers["user"],
    )
    assert response.status_code == 409
    after = get_user_by_username(accounts.path, "user")
    assert not verify_password(NEW_PASSWORD, after.password_hash)
    if change == "reset":
        assert after.password_hash == admin_replacement
    else:
        assert not after.is_active


def test_change_rechecks_activation_before_password_verification(accounts, monkeypatch):
    """A disabled account discovered after session authentication must fail closed."""
    original_lookup = service.get_user_by_id

    def read_disabled(path, user_id):
        """Simulate activation changing between the dependency and service lookup."""
        account = original_lookup(path, user_id)
        return account.model_copy(update={"is_active": False})

    # Dependency resolution also uses get_user_by_id, so replace just the
    # change service's public call to exercise the post-authentication branch.
    with pytest.raises(service.InvalidCredentials):
        monkeypatch.setattr(service, "get_user_by_id", read_disabled)
        service.change_password(
            accounts.path, accounts.identities["user"].user_id, PASSWORD, NEW_PASSWORD
        )
