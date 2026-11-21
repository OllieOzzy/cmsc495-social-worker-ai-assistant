"""Validate stored accounts and separate public identity from password hashes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

UserRole = Literal["user", "admin"]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$",
    ),
]
_AccountText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class UserAccount(BaseModel):
    """Expose account identity and role without credential material."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    username: Username
    display_name: _AccountText
    role: UserRole = "user"
    is_active: bool = True
    created_at: datetime


class StoredUserAccount(UserAccount):
    """Keep the encoded password hash internal to account and login operations.

    Hashing and verification belong to the password service.
    Exclusion prevents accidental exposure when this model is serialized.
    """

    password_hash: Annotated[str, StringConstraints(min_length=1)] = Field(
        repr=False, exclude=True
    )


class LoginRequest(BaseModel):
    """Accept credentials without exposing the password in the model's repr."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    # Check password length during authentication, avoiding validation errors
    # that would echo a rejected password into FastAPI's error response.
    password: SecretStr = Field(repr=False)


class LoginResponse(BaseModel):
    """Return a bearer token once, with its expiry and public account identity."""

    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserAccount


class CreateUserRequest(BaseModel):
    """Accept administrator-provided account details without exposing passwords."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    display_name: _AccountText
    password: SecretStr = Field(repr=False)
    role: UserRole = "user"


class UserStatusRequest(BaseModel):
    """Change activation only; roles and credentials are separate operations."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool = Field(strict=True)
