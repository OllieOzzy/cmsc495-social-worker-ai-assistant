"""Configure the FastAPI backend and expose it to Uvicorn."""

import os
from pathlib import Path

from fastapi import FastAPI

from documentation_assistant.backend.api.health import router as health_router
from documentation_assistant.backend.api.reports import router as reports_router


def create_app() -> FastAPI:
    """Build the API with its documentation, database path, and routes."""
    application = FastAPI(
        title="Social Worker Documentation Assistant API",
        description=(
            "The API supports a school social work documentation workflow, from "
            "session notes through an approved PDF based on the school DAP template."
        ),
        version="0.1.0",
    )
    # Resolve relative paths against the directory used to start the backend.
    application.state.database_path = Path(
        os.getenv("DAP_DB_PATH", "data/dap.db")
    ).resolve()
    application.include_router(health_router)
    application.include_router(reports_router)
    return application


app = create_app()
