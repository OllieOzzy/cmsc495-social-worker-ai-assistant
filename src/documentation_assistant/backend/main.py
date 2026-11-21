"""Build the FastAPI application and expose the Uvicorn entry point."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from documentation_assistant import OLLAMA_REQUEST_TIMEOUT_SECONDS
from documentation_assistant.backend.api.auth import router as auth_router
from documentation_assistant.backend.api.health import router as health_router
from documentation_assistant.backend.api.reports import router as reports_router
from documentation_assistant.backend.api.users import router as users_router
from documentation_assistant.backend.db.connection import initialize_database


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Prepare SQLite before serving requests and close the Ollama client on exit.

    Each application startup owns one client shared by generation and
    regeneration. Database initialization also upgrades missing columns.
    """
    initialize_database(application.state.database_path)
    # Creating the client does not require Ollama to be running. Connections
    # open on demand and are closed together when the backend shuts down.
    async with httpx.AsyncClient(
        timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS, trust_env=False
    ) as client:
        application.state.ollama_client = client
        yield


def create_app() -> FastAPI:
    """Create FastAPI with health, authentication, user management, and report routes.

    Read DAP_DB_PATH during app creation so callers can configure the database
    location. The lifespan initializes SQLite before requests are accepted.
    """
    application = FastAPI(
        title="Social Worker Documentation Assistant API",
        description=(
            "The API supports creating, reviewing, and approving DAP session notes "
            "for school social work."
        ),
        version="1.1.0",
        lifespan=lifespan,
    )
    # Resolve relative database paths against the process working directory.
    application.state.database_path = Path(
        os.getenv("DAP_DB_PATH", "data/dap.db")
    ).resolve()
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(users_router)
    application.include_router(reports_router)
    return application


# Uvicorn imports this instance when started with backend.main:app.
app = create_app()
