"""Build the FastAPI application and expose the Uvicorn entry point."""

import os
from pathlib import Path

from fastapi import FastAPI

from documentation_assistant.backend.api.health import router as health_router
from documentation_assistant.backend.api.reports import router as reports_router


def create_app() -> FastAPI:
    """Create a FastAPI instance with health and report routes.

    Read DAP_DB_PATH during app creation so callers can configure the database
    location. SQLite opens the database when a report operation needs it.
    """
    application = FastAPI(
        title="Social Worker Documentation Assistant API",
        description=(
            "The API supports creating, reviewing, and approving DAP session notes "
            "for school social work."
        ),
        version="1.0.0",
    )
    # Resolve relative database paths against the process working directory.
    application.state.database_path = Path(
        os.getenv("DAP_DB_PATH", "data/dap.db")
    ).resolve()
    application.include_router(health_router)
    application.include_router(reports_router)
    return application


# Uvicorn imports this instance when started with backend.main:app.
app = create_app()
