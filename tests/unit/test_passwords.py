"""Exercise real Argon2 hashing and safe rejection of unusable credentials."""

import pytest

from documentation_assistant.backend.auth.passwords import (
    hash_password,
    validate_new_password,
    verify_password,
)


def test_hashes_are_salted_and_verify_without_normalizing_passwords():
    """Equal passwords get different hashes; case and whitespace remain significant."""
    password = "A sufficiently long password"
    first = hash_password(password)
    second = hash_password(password)

    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password(password, first)
    assert verify_password(password, second)
    assert not verify_password(password.lower(), first)
    assert not verify_password(f" {password}", first)


@pytest.mark.parametrize("password", ["", "a" * 1025])
def test_hashing_rejects_empty_or_oversized_passwords(password):
    """Reject unusable input before invoking the password hashing library."""
    with pytest.raises(ValueError, match="between 1 and 1024"):
        hash_password(password)
    assert not verify_password(password, "unused-hash")


@pytest.mark.parametrize("encoded_hash", ["plaintext", "", "$argon2id$broken"])
def test_unusable_stored_hash_does_not_authenticate(encoded_hash):
    """Unsupported and malformed stored hashes must fail verification safely."""
    assert not verify_password("A sufficiently long password", encoded_hash)


@pytest.mark.parametrize("length", [0, 14, 1025])
def test_new_account_password_policy_rejects_invalid_lengths(length):
    """Ordinary account creation uses a stronger policy than public demo setup."""
    with pytest.raises(ValueError, match="15 to 1024"):
        validate_new_password("a" * length)


@pytest.mark.parametrize("length", [15, 64, 1024])
def test_new_account_password_policy_accepts_supported_lengths(length):
    """Allow passphrases without silently truncating them."""
    validate_new_password("a" * length)
