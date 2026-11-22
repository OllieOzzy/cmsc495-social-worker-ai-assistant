"""Expose login, logout, and the current account without public registration."""

from fastapi import APIRouter, HTTPException, Request, Response

from documentation_assistant.backend.api.validation import CredentialSafeRoute
from documentation_assistant.backend.auth.dependencies import (
    BearerCredentials,
    CurrentUser,
)
from documentation_assistant.backend.auth.service import (
    IncorrectCurrentPassword,
    InvalidCredentials,
    LoginThrottled,
    change_password,
    login,
    logout,
)
from documentation_assistant.backend.db.users import PasswordChangeConflict
from documentation_assistant.backend.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserAccount,
)

router = APIRouter(
    prefix="/auth", tags=["Authentication"], route_class=CredentialSafeRoute
)


@router.post("/login", response_model=LoginResponse)
def sign_in(
    payload: LoginRequest, request: Request, response: Response
) -> LoginResponse:
    """Exchange credentials for an eight-hour session token; never cache it."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return login(
            request.app.state.database_path,
            payload.username,
            payload.password.get_secret_value(),
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        ) from exc
    except LoginThrottled as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after), "Cache-Control": "no-store"},
        ) from exc


@router.get("/me", response_model=UserAccount)
def current_account(user: CurrentUser, response: Response) -> UserAccount:
    """Return the authenticated account's current identity and role."""
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", status_code=204)
def sign_out(
    request: Request,
    user: CurrentUser,
    credentials: BearerCredentials,
) -> Response:
    """Revoke this session while leaving the account's other sessions active."""
    # CurrentUser requires credentials before this handler can be reached.
    logout(request.app.state.database_path, credentials.credentials)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/change-password", status_code=204)
def change_own_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: CurrentUser,
) -> Response:
    """Change only the signed-in account's password and revoke all its sessions."""
    headers = {"Cache-Control": "no-store"}
    try:
        change_password(
            request.app.state.database_path,
            user.user_id,
            payload.current_password.get_secret_value(),
            payload.new_password.get_secret_value(),
        )
    except IncorrectCurrentPassword as exc:
        raise HTTPException(403, str(exc), headers=headers) from exc
    except LoginThrottled as exc:
        raise HTTPException(
            429, str(exc), headers={**headers, "Retry-After": str(exc.retry_after)}
        ) from exc
    except PasswordChangeConflict as exc:
        raise HTTPException(409, str(exc), headers=headers) from exc
    except InvalidCredentials as exc:
        raise HTTPException(
            401,
            "Invalid or expired session. Please sign in.",
            headers={**headers, "WWW-Authenticate": "Bearer"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc), headers=headers) from exc
    return Response(status_code=204, headers=headers)
