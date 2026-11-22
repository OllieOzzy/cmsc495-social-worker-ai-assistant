"""Administer account identity, activation, and password recovery without public signup."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from documentation_assistant.backend.api.validation import CredentialSafeRoute
from documentation_assistant.backend.auth.dependencies import AdminUser
from documentation_assistant.backend.auth.passwords import (
    hash_password,
    validate_new_password,
)
from documentation_assistant.backend.db.users import (
    AccountStatusConflict,
    DuplicateUsername,
    create_user,
    list_users,
    rename_user,
    reset_user_password,
    set_user_active,
    set_user_role,
)
from documentation_assistant.backend.schemas.auth import (
    CreateUserRequest,
    ResetPasswordRequest,
    UserAccount,
    UserProfileRequest,
    UserRoleRequest,
    UserStatusRequest,
)

router = APIRouter(
    prefix="/users", tags=["User management"], route_class=CredentialSafeRoute
)


@router.get("", response_model=list[UserAccount])
def read_users(
    request: Request,
    response: Response,
    admin: AdminUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    search: Annotated[str, Query(max_length=200)] = "",
) -> list[UserAccount]:
    """List public account identities, including inactive accounts, for admins."""
    response.headers["Cache-Control"] = "no-store"
    return list_users(
        request.app.state.database_path, limit=limit, offset=offset, search=search
    )


@router.post("", response_model=UserAccount, status_code=201)
def add_user(
    payload: CreateUserRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> UserAccount:
    """Create a salted account using the same password policy as the CLI."""
    response.headers["Cache-Control"] = "no-store"
    password = payload.password.get_secret_value()
    try:
        validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(
            422, str(exc), headers={"Cache-Control": "no-store"}
        ) from exc
    try:
        account = create_user(
            request.app.state.database_path,
            username=payload.username,
            display_name=payload.display_name,
            password_hash=hash_password(password),
            role=payload.role,
        )
    except DuplicateUsername as exc:
        raise HTTPException(409, str(exc)) from exc
    return UserAccount.model_validate(account.model_dump())


@router.patch("/{user_id}", response_model=UserAccount)
def change_user_status(
    user_id: UUID,
    payload: UserStatusRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> UserAccount:
    """Activate or deactivate an account, preserving reports and approval records."""
    response.headers["Cache-Control"] = "no-store"
    if user_id == admin.user_id and not payload.is_active:
        raise HTTPException(409, "You cannot deactivate your own account.")
    try:
        account = set_user_active(
            request.app.state.database_path, user_id, is_active=payload.is_active
        )
    except AccountStatusConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if account is None:
        raise HTTPException(404, "Account not found.")
    return account


@router.post("/{user_id}/reset-password", response_model=UserAccount)
def reset_account_password(
    user_id: UUID,
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> UserAccount:
    """Reset an account password and invalidate every existing session, including self."""
    response.headers["Cache-Control"] = "no-store"
    password = payload.password.get_secret_value()
    try:
        validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(
            422, str(exc), headers={"Cache-Control": "no-store"}
        ) from exc
    account = reset_user_password(
        request.app.state.database_path,
        user_id,
        password_hash=hash_password(password),
    )
    if account is None:
        raise HTTPException(404, "Account not found.")
    return account


@router.patch("/{user_id}/role", response_model=UserAccount)
def change_account_role(
    user_id: UUID,
    payload: UserRoleRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> UserAccount:
    """Change a role and sign out its sessions, protecting the last active admin."""
    response.headers["Cache-Control"] = "no-store"
    try:
        account = set_user_role(
            request.app.state.database_path, user_id, role=payload.role
        )
    except AccountStatusConflict as exc:
        raise HTTPException(
            409, str(exc), headers={"Cache-Control": "no-store"}
        ) from exc
    if account is None:
        raise HTTPException(
            404, "Account not found.", headers={"Cache-Control": "no-store"}
        )
    return account


@router.patch("/{user_id}/profile", response_model=UserAccount)
def rename_account(
    user_id: UUID,
    payload: UserProfileRequest,
    request: Request,
    response: Response,
    admin: AdminUser,
) -> UserAccount:
    """Let administrators update names without transferring account identity."""
    response.headers["Cache-Control"] = "no-store"
    try:
        account = rename_user(
            request.app.state.database_path,
            user_id,
            username=payload.username,
            display_name=payload.display_name,
        )
    except DuplicateUsername as exc:
        raise HTTPException(409, str(exc)) from exc
    if account is None:
        raise HTTPException(404, "Account not found.")
    return account
