"""Expose login, logout, and the current account without public registration."""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from documentation_assistant.backend.auth.dependencies import (
    BearerCredentials,
    CurrentUser,
)
from documentation_assistant.backend.auth.service import (
    InvalidCredentials,
    LoginThrottled,
    login,
    logout,
)
from documentation_assistant.backend.schemas.auth import (
    LoginRequest,
    LoginResponse,
    UserAccount,
)


class _CredentialSafeRoute(APIRoute):
    """Keep rejected request bodies out of credential-validation responses."""

    def get_route_handler(self):
        """Wrap validation so missing fields cannot echo the submitted password."""
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid authentication request.",
                    headers={"Cache-Control": "no-store"},
                ) from exc

        return handle


router = APIRouter(
    prefix="/auth", tags=["Authentication"], route_class=_CredentialSafeRoute
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
