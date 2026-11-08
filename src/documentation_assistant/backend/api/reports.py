"""Draft generation endpoints."""

import httpx
from fastapi import APIRouter, HTTPException

from documentation_assistant.backend.llm.ollama import (
    InvalidModelResponse,
    generate_dap,
)
from documentation_assistant.backend.schemas.reports import (
    GenerateReportRequest,
    ReportDraft,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post("/generate", response_model=ReportDraft)
async def generate_report(request: GenerateReportRequest) -> ReportDraft:
    """Generate a DAP draft from synthetic session notes for human review."""
    try:
        sections = await generate_dap(request.notes)
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
    return ReportDraft(sections=sections)
