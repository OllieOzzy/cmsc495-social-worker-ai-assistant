"""Verify identity renaming, session revocation, and preserved report attribution."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader

from documentation_assistant.backend.auth import service
from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.db.connection import connect
from documentation_assistant.backend.db.sessions import reserve_login_attempt
from documentation_assistant.backend.db.users import (
    create_user,
    get_user_by_id,
    get_user_by_username,
    rename_user,
    set_user_active,
)
from documentation_assistant.backend.schemas.reports import DraftSections
from tests.integration.test_user_management_api import PASSWORD, encoded_password
from tests.integration.test_user_management_api import accounts as _management_accounts

accounts = _management_accounts
SECTIONS = DraftSections(
    data="Synthetic data.", assessment="Synthetic assessment.", plan="Follow up."
)


def profile_url(accounts, name="user"):
    """Select the account by stable ID rather than its editable username."""
    return f"/users/{accounts.identities[name].user_id}/profile"


def test_rename_clears_old_and_new_username_login_windows(accounts):
    """A newly assigned login name must not inherit earlier failed attempts."""
    now = int(service.time())
    for username in ("user", "renamed-user"):
        for _ in range(5):
            assert reserve_login_attempt(accounts.path, username, now) == 0
    accounts.client.patch(
        profile_url(accounts),
        json={"username": "renamed-user"},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "renamed-user", "password": PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
def test_profile_changes_require_admin(accounts, viewer, status):
    """A regular user cannot rename themselves or escalate role through this endpoint."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.patch(
        profile_url(accounts),
        json={"username": "renamed-user"},
        headers=accounts.headers.get(viewer, {}),
    )
    assert response.status_code == status
    assert get_user_by_username(accounts.path, "user") == before


def test_username_change_preserves_identity_and_reports_and_revokes_all_sessions(
    accounts,
):
    """The same account signs in under its new name without inheriting or losing reports."""
    original = get_user_by_username(accounts.path, "user")
    report = save_draft(
        accounts.path, "Preserved notes.", SECTIONS, owner_id=original.user_id
    )
    second = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()["access_token"]
    response = accounts.client.patch(
        profile_url(accounts),
        json={"username": " Renamed.User ", "display_name": " Updated User "},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "password_hash" not in response.text
    renamed = get_user_by_username(accounts.path, "renamed.user")
    assert renamed.user_id == original.user_id
    assert renamed.password_hash == original.password_hash
    assert renamed.role == original.role
    assert renamed.created_at == original.created_at
    assert renamed.display_name == "Updated User"
    assert get_user_by_username(accounts.path, "user") is None
    assert get_draft(accounts.path, report.report_id) == report
    for headers in (accounts.headers["user"], {"Authorization": f"Bearer {second}"}):
        assert accounts.client.get("/auth/me", headers=headers).status_code == 401
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        ).status_code
        == 401
    )
    logged_in = accounts.client.post(
        "/auth/login", json={"username": "renamed.user", "password": PASSWORD}
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]
    assert (
        accounts.client.get(
            f"/reports/{report.report_id}", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )


def test_display_only_change_keeps_sessions_and_password(accounts):
    """Cosmetic name edits take effect on the next identity lookup without logout."""
    original = get_user_by_username(accounts.path, "user")
    response = accounts.client.patch(
        profile_url(accounts),
        json={"display_name": "New Display Name"},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    identity = accounts.client.get("/auth/me", headers=accounts.headers["user"])
    assert identity.status_code == 200
    assert identity.json()["display_name"] == "New Display Name"
    assert (
        get_user_by_username(accounts.path, "user").password_hash
        == original.password_hash
    )


def test_historical_approvals_keep_saved_names_and_new_approvals_use_new_display(
    accounts,
):
    """Reviewer names are historical snapshots; approval IDs remain stable."""
    report = save_draft(
        accounts.path,
        "Old report.",
        SECTIONS,
        owner_id=accounts.identities["user"].user_id,
    )
    approved = accounts.client.post(
        f"/reports/{report.report_id}/approve",
        json={"revision": 1},
        headers=accounts.headers["admin"],
    ).json()
    assert approved["approved_by"] == "Admin"
    accounts.client.patch(
        profile_url(accounts, "admin"),
        json={"display_name": "Renamed Reviewer"},
        headers=accounts.headers["admin"],
    ).raise_for_status()
    assert (
        accounts.client.get(
            f"/reports/{report.report_id}", headers=accounts.headers["admin"]
        ).json()
        == approved
    )
    with connect(accounts.path) as connection:
        assert connection.execute(
            "SELECT approved_by_id FROM report_drafts WHERE report_id = ?",
            (str(report.report_id),),
        ).fetchone()[0] == str(accounts.identities["admin"].user_id)
    pdf = accounts.client.get(
        f"/reports/{report.report_id}/download", headers=accounts.headers["admin"]
    )
    text = PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert "Admin" in text
    assert "Renamed Reviewer" not in text
    newer = save_draft(
        accounts.path,
        "New report.",
        SECTIONS,
        owner_id=accounts.identities["user"].user_id,
    )
    response = accounts.client.post(
        f"/reports/{newer.report_id}/approve",
        json={"revision": 1},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert response.json()["approved_by"] == "Renamed Reviewer"


def test_duplicate_username_rolls_back_all_names_and_keeps_sessions(accounts):
    """A conflicting rename cannot partially change display name or revoke tokens."""
    before = get_user_by_username(accounts.path, "user")
    response = accounts.client.patch(
        profile_url(accounts),
        json={"username": " ADMIN ", "display_name": "Should not change"},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 409
    assert get_user_by_username(accounts.path, "user") == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": None},
        {"display_name": None},
        {"username": "ab"},
        {"username": "bad name"},
        {"display_name": " "},
        {"role": "admin"},
        {"username": "renamed", "is_active": False},
    ],
)
def test_profile_validation_blocks_invalid_or_unrelated_changes(accounts, payload):
    """Renaming cannot change roles, credentials, or activation as a side effect."""
    before = get_user_by_username(accounts.path, "user")
    assert (
        accounts.client.patch(
            profile_url(accounts), json=payload, headers=accounts.headers["admin"]
        ).status_code
        == 422
    )
    assert get_user_by_username(accounts.path, "user") == before


def test_normalized_noop_keeps_tokens_and_missing_account_returns_404(accounts):
    """Case and surrounding whitespace alone do not count as a new username."""
    response = accounts.client.patch(
        profile_url(accounts),
        json={"username": " USER ", "display_name": " User "},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )
    assert (
        accounts.client.patch(
            f"/users/{uuid4()}/profile",
            json={"display_name": "Missing"},
            headers=accounts.headers["admin"],
        ).status_code
        == 404
    )


def test_self_username_change_requires_new_login_and_keeps_admin_role(accounts):
    """An administrator can rename their own account without losing its identity."""
    response = accounts.client.patch(
        profile_url(accounts, "admin"),
        json={"username": "renamed-admin"},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == str(accounts.identities["admin"].user_id)
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["admin"]).status_code
        == 401
    )
    signed_in = accounts.client.post(
        "/auth/login", json={"username": "renamed-admin", "password": PASSWORD}
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["role"] == "admin"


def test_inactive_account_rename_does_not_reactivate(accounts):
    """Admin identity edits do not undo an account's disabled status."""
    set_user_active(accounts.path, accounts.identities["user"].user_id, is_active=False)
    response = accounts.client.patch(
        profile_url(accounts),
        json={"username": "renamed-user"},
        headers=accounts.headers["admin"],
    )
    assert response.status_code == 200
    assert not response.json()["is_active"]
    assert (
        accounts.client.post(
            "/auth/login", json={"username": "renamed-user", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_reused_old_username_does_not_inherit_former_owners_reports(accounts):
    """Ownership follows user IDs, even if an old username is assigned to someone else."""
    report = save_draft(
        accounts.path,
        "Original owner's notes.",
        SECTIONS,
        owner_id=accounts.identities["user"].user_id,
    )
    rename_user(
        accounts.path, accounts.identities["user"].user_id, username="renamed-user"
    )
    replacement = create_user(
        accounts.path,
        username="user",
        display_name="Different person",
        password_hash=encoded_password(),
    )
    assert replacement.user_id != accounts.identities["user"].user_id
    token = accounts.client.post(
        "/auth/login", json={"username": "user", "password": PASSWORD}
    ).json()["access_token"]
    assert (
        accounts.client.get(
            f"/reports/{report.report_id}", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "operation, status", [("login", 401), ("change-password", 409)]
)
def test_inflight_old_username_cannot_survive_rename(
    accounts, monkeypatch, operation, status
):
    """A rename during credential verification must prevent stale auth writes."""
    original_verify = service.verify_password
    changed = False

    def verify_then_rename(password, encoded):
        """Inject the rename immediately after the password was verified."""
        nonlocal changed
        valid = original_verify(password, encoded)
        if valid and not changed:
            changed = True
            rename_user(
                accounts.path,
                accounts.identities["user"].user_id,
                username="renamed-user",
            )
        return valid

    monkeypatch.setattr(service, "verify_password", verify_then_rename)
    if operation == "login":
        response = accounts.client.post(
            "/auth/login", json={"username": "user", "password": PASSWORD}
        )
    else:
        response = accounts.client.post(
            "/auth/change-password",
            json={
                "current_password": PASSWORD,
                "new_password": "Must not overwrite the credential!",
            },
            headers=accounts.headers["user"],
        )
    assert response.status_code == status
    assert (
        get_user_by_username(accounts.path, "renamed-user").password_hash
        == encoded_password()
    )
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 401
    )


def test_password_change_rejects_a_username_renamed_before_service_lookup(accounts):
    """Do not use a pre-rename session identity to begin another sensitive action."""
    rename_user(
        accounts.path, accounts.identities["user"].user_id, username="renamed-user"
    )
    with pytest.raises(service.InvalidCredentials):
        service.change_password(
            accounts.path,
            accounts.identities["user"].user_id,
            PASSWORD,
            "Another long replacement password!",
            authenticated_username="user",
        )


def test_rename_rolls_back_when_revocation_fails(accounts):
    """Names and token revocation must commit or fail together."""
    before = get_user_by_username(accounts.path, "user")
    with connect(accounts.path) as connection:
        connection.execute("""CREATE TRIGGER fail_rename_revoke BEFORE DELETE ON user_sessions
            BEGIN SELECT RAISE(ABORT, 'simulated revocation failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="revocation failure"):
        rename_user(
            accounts.path,
            before.user_id,
            username="renamed-user",
            display_name="Changed",
        )
    assert get_user_by_id(accounts.path, before.user_id) == before
    assert (
        accounts.client.get("/auth/me", headers=accounts.headers["user"]).status_code
        == 200
    )


def test_concurrent_claims_for_one_username_have_one_winner(accounts):
    """The unique constraint prevents two accounts from claiming the same name."""
    other = create_user(
        accounts.path,
        username="other-user",
        display_name="Other",
        password_hash=encoded_password(),
    )

    def claim(user_id):
        """Send independent admin requests against the same real SQLite file."""
        return accounts.client.patch(
            f"/users/{user_id}/profile",
            json={"username": "shared-name"},
            headers=accounts.headers["admin"],
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(claim, [other.user_id, accounts.identities["user"].user_id])
        )
    assert sorted(results) == [200, 409]
