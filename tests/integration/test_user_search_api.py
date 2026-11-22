"""Verify admin account search against real SQLite before pagination."""

import pytest

from documentation_assistant.backend.db.users import create_user, set_user_active
from tests.integration.test_user_management_api import accounts as _management_accounts
from tests.integration.test_user_management_api import encoded_password

accounts = _management_accounts


@pytest.fixture
def searchable_accounts(accounts):
    """Include names, Unicode, and literal wildcard characters in synthetic identities."""
    for username, display in (
        ("alpha", "Taylor Rivera"),
        ("beta", "Taylor Straße"),
        ("gamma", "100%_complete"),
    ):
        identity = create_user(
            accounts.path,
            username=username,
            display_name=display,
            password_hash=encoded_password(),
        )
        if username == "beta":
            set_user_active(accounts.path, identity.user_id, is_active=False)
    return accounts


@pytest.mark.parametrize(
    "query, expected",
    [
        (" ALP ", ["alpha"]),
        ("tAyLoR", ["alpha", "beta"]),
        ("STRASSE", ["beta"]),
        ("%_", ["gamma"]),
        ("' OR 1=1 --", []),
        ("missing", []),
        ("   ", ["admin", "alpha", "beta", "gamma", "user"]),
    ],
)
def test_literal_name_search_returns_only_public_matching_accounts(
    searchable_accounts, query, expected
):
    """Names match case-insensitively, including inactive users, without wildcard expansion."""
    response = searchable_accounts.client.get(
        "/users", params={"search": query}, headers=searchable_accounts.headers["admin"]
    )
    assert response.status_code == 200
    assert [account["username"] for account in response.json()] == expected
    assert "password" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_filtering_precedes_pagination(searchable_accounts):
    """Offsets apply to matching users rather than the unfiltered account list."""
    response = searchable_accounts.client.get(
        "/users",
        params={"search": "Taylor", "limit": 1, "offset": 1},
        headers=searchable_accounts.headers["admin"],
    )
    assert [account["username"] for account in response.json()] == ["beta"]
    assert response.json()[0]["is_active"] is False


@pytest.mark.parametrize("viewer, status", [(None, 401), ("user", 403)])
def test_search_requires_admin(accounts, viewer, status):
    """Providing a query does not bypass account-directory authorization."""
    assert (
        accounts.client.get(
            "/users",
            params={"search": "admin"},
            headers=accounts.headers.get(viewer, {}),
        ).status_code
        == status
    )


def test_search_length_is_bounded(accounts):
    """Reject oversized search text through the HTTP validation layer."""
    assert (
        accounts.client.get(
            "/users", params={"search": "x" * 201}, headers=accounts.headers["admin"]
        ).status_code
        == 422
    )
