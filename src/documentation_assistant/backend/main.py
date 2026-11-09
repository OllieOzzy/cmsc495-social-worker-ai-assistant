"""Application entry point for Uvicorn."""

import os
from pathlib import Path

from fastapi import FastAPI

from documentation_assistant.backend.api.health import router as health_router
from documentation_assistant.backend.api.reports import router as reports_router


def create_app() -> FastAPI:
    """Build an application with its registered API routes."""
    application = FastAPI(
        title="Social Worker Documentation Assistant API",
        description="Local backend for the prototype using synthetic data.",
        version="0.1.0",
    )
    application.state.database_path = Path(
        os.getenv("DAP_DB_PATH", "data/dap.db")
    ).resolve()
    application.include_router(health_router)
    application.include_router(reports_router)
    return application


app = create_app()
