"""Hash and verify passwords with Argon2id without normalizing their contents."""

from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError

_PASSWORD_HASH = PasswordHash.recommended()
_MAX_PASSWORD_LENGTH = 1024


def hash_password(password: str) -> str:
    """Return a salted Argon2id hash; callers apply new-account password policy."""
    if not 1 <= len(password) <= _MAX_PASSWORD_LENGTH:
        raise ValueError("Password must contain between 1 and 1024 characters.")
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Reject mismatches and unusable stored hashes without exposing their contents."""
    if not 1 <= len(password) <= _MAX_PASSWORD_LENGTH:
        return False
    try:
        return _PASSWORD_HASH.verify(password, encoded_hash)
    except (UnknownHashError, HashVerificationError):
        return False


def validate_new_password(password: str) -> None:
    """Apply the normal account policy; explicit demo setup uses its public password."""
    if not 15 <= len(password) <= _MAX_PASSWORD_LENGTH:
        raise ValueError("New account passwords must contain 15 to 1024 characters.")
