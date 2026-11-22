"""Verify account identity validation and protection of serialized credentials."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from documentation_assistant.backend.schemas.auth import StoredUserAccount, UserAccount


@pytest.fixture
def account_fields():
    """Provide synthetic identity fields without password material."""
    return {
        "user_id": uuid4(),
        "username": "user",
        "display_name": "Demo User",
        "created_at": datetime.now(UTC),
    }


@pytest.mark.parametrize("role", ["user", "admin"])
def test_account_accepts_supported_roles_and_normalizes_names(account_fields, role):
    """Usernames are case-insensitive; display names keep their entered spelling."""
    account = UserAccount(
        **{**account_fields, "username": " User.Name ", "display_name": " Demo User "},
        role=role,
    )

    assert account.username == "user.name"
    assert account.display_name == "Demo User"
    assert account.role == role
    assert account.is_active is True


def test_new_account_defaults_to_regular_user(account_fields):
    """Account creation must not grant administrative privileges by default."""
    assert UserAccount(**account_fields).role == "user"


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "ab"},
        {"username": "a" * 65},
        {"username": "two users"},
        {"username": "-user"},
        {"username": "usér"},
        {"display_name": " "},
        {"display_name": "a" * 201},
        {"role": "superuser"},
        {"role": "ADMIN"},
        {"password": "not-a-public-account-field"},
    ],
)
def test_account_rejects_invalid_identity_and_roles(account_fields, changes):
    """Reject unsupported roles and malformed account fields before storage."""
    with pytest.raises(ValidationError):
        UserAccount(**{**account_fields, **changes})


def test_stored_hash_is_available_for_verification_but_not_serialized(account_fields):
    """Internal hash access must not leak through repr, JSON, or model dumps."""
    account = StoredUserAccount(
        **account_fields, password_hash="synthetic-encoded-hash"
    )

    assert account.password_hash == "synthetic-encoded-hash"
    assert "synthetic-encoded-hash" not in repr(account)
    assert "password_hash" not in account.model_dump()
    assert "synthetic-encoded-hash" not in account.model_dump_json()


def test_stored_account_requires_a_nonempty_hash(account_fields):
    """A missing hash cannot become a usable stored account."""
    with pytest.raises(ValidationError):
        StoredUserAccount(**account_fields, password_hash="")
