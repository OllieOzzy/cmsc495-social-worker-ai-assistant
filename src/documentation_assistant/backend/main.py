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
            "session notes through an approved PDF based on the school DAP template. "
            "Use synthetic student data only.\n\n"
            "**Available now**\n\n"
            "- Submit brief session notes and use local Ollama to generate a draft "
            "with Data, Assessment, and Plan sections. The model is instructed to "
            "use only information supported by the notes and mark missing details "
            "as `Not documented.`.\n"
            "- Save the source notes and draft in local SQLite and retrieve both "
            "by report ID for side-by-side review.\n\n"
            "**Planned workflow**\n\n"
            "- Upload a session note file and review the extracted text before "
            "generating a draft.\n"
            "- Find saved reports, edit the draft, and explicitly approve it after "
            "checking it against the source notes.\n"
            "- Download the approved report as a PDF using the school DAP template."
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
