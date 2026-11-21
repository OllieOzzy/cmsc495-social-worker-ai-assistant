"""Resolve bearer sessions for authenticated API endpoints."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from documentation_assistant.backend.auth.service import (
    InvalidCredentials,
    authenticate_session,
)
from documentation_assistant.backend.schemas.auth import UserAccount

bearer = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def get_current_user(request: Request, credentials: BearerCredentials) -> UserAccount:
    """Require an active, unexpired session; return only public account fields."""
    try:
        if credentials is None:
            raise InvalidCredentials("Authentication required.")
        return authenticate_session(
            request.app.state.database_path, credentials.credentials
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please sign in.",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        ) from exc


CurrentUser = Annotated[UserAccount, Depends(get_current_user)]
