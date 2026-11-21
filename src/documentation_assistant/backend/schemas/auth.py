"""Validate stored accounts and separate public identity from password hashes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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

    Hashing and verification belong to the password service added separately.
    Exclusion prevents accidental exposure when this model is serialized.
    """

    password_hash: Annotated[str, StringConstraints(min_length=1)] = Field(
        repr=False, exclude=True
    )
