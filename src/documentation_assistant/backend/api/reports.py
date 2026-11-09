"""Draft generation endpoints."""

from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from documentation_assistant.backend.db import get_draft, save_draft
from documentation_assistant.backend.llm.ollama import (
    InvalidModelResponse,
    generate_dap,
)
from documentation_assistant.backend.schemas.reports import (
    GenerateReportRequest,
    ReportDraft,
    StoredReportDraft,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post("/generate", response_model=ReportDraft)
async def generate_report(
    payload: GenerateReportRequest, request: Request
) -> ReportDraft:
    """Generate a DAP draft from synthetic session notes for human review."""
    try:
        sections = await generate_dap(payload.notes)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            504, "Ollama timed out. Try again with shorter notes."
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            503, "Could not reach local Ollama. Check that it is running."
        ) from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                503, "The configured Ollama model is unavailable."
            ) from exc
        raise HTTPException(502, "Ollama could not generate the draft.") from exc
    except InvalidModelResponse as exc:
        raise HTTPException(
            502, "Ollama returned an incomplete or invalid DAP draft."
        ) from exc
    return await run_in_threadpool(
        save_draft, request.app.state.database_path, payload.notes, sections
    )


@router.get("/{report_id}", response_model=StoredReportDraft)
def read_report(report_id: UUID, request: Request) -> StoredReportDraft:
    """Retrieve the original notes and generated sections for review."""
    draft = get_draft(request.app.state.database_path, report_id)
    if draft is None:
        raise HTTPException(404, "Report draft not found.")
    return draft
