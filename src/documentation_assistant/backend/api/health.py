"""Expose the API liveness check."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Define the JSON response for a successful liveness check."""

    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Confirm FastAPI is responding without contacting SQLite or Ollama."""
    return HealthResponse()
