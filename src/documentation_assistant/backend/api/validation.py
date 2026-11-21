"""Sanitize validation failures for routes accepting account credentials."""

from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


class CredentialSafeRoute(APIRoute):
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
