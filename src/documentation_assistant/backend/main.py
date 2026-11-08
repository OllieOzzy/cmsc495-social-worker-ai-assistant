"""Application entry point for Uvicorn."""

from fastapi import FastAPI

from documentation_assistant.backend.api.health import router as health_router


def create_app() -> FastAPI:
    """Build an application with its registered API routes."""
    application = FastAPI(
        title="Social Worker Documentation Assistant API",
        description="Local backend for the prototype using synthetic data.",
        version="0.1.0",
    )
    application.include_router(health_router)
    return application


app = create_app()
