"""API endpoints for generating, finding, reviewing, and exporting DAP reports."""

from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from documentation_assistant.backend.db import (
    ReviewConflict,
    approve_draft,
    delete_draft,
    edit_draft,
    get_draft,
    list_drafts,
    reopen_approved_report,
    save_draft,
)
from documentation_assistant.backend.export.pdf import render_report_pdf
from documentation_assistant.backend.llm.ollama import (
    InvalidModelResponse,
    generate_dap,
)
from documentation_assistant.backend.schemas.reports import (
    ApproveReportRequest,
    DAPSections,
    DraftSections,
    EditReportRequest,
    GenerateReportRequest,
    ManualReportRequest,
    RegenerateReportRequest,
    ReportDraft,
    ReportFilters,
    ReportMetadata,
    ReportRevisionRequest,
    ReportSummary,
    StoredReportDraft,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post("/manual", response_model=StoredReportDraft, status_code=201)
def create_manual_report(
    payload: ManualReportRequest, request: Request
) -> StoredReportDraft:
    """Start a manual draft with optional notes and empty DAP sections."""
    metadata = (payload.metadata or ReportMetadata()).model_copy(
        update={"draft_source": "handwritten"}
    )
    return save_draft(
        request.app.state.database_path,
        payload.notes,
        DraftSections(data="", assessment="", plan=""),
        metadata,
    )


@router.post("/generate", response_model=ReportDraft)
async def generate_report(
    payload: GenerateReportRequest, request: Request
) -> ReportDraft:
    """Generate and save an unapproved DAP draft from synthetic session notes."""
    sections = await _generate_sections(payload.notes)
    # Run the synchronous SQLite write off the event loop.
    metadata = (payload.metadata or ReportMetadata()).model_copy(
        update={"draft_source": "ai_assisted"}
    )
    draft = await run_in_threadpool(
        save_draft,
        request.app.state.database_path,
        payload.notes,
        sections,
        metadata,
    )
    return ReportDraft(report_id=draft.report_id, sections=sections)


async def _generate_sections(notes: str) -> DAPSections:
    """Generate validated DAP sections and translate Ollama failures to API errors."""
    try:
        return await generate_dap(notes)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            504, "Ollama timed out. Try again with shorter notes."
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            503, "Could not reach local Ollama. Check that it is running."
        ) from exc
    except httpx.HTTPStatusError as exc:
        # An Ollama 404 indicates the configured model is unavailable.
        if exc.response.status_code == 404:
            raise HTTPException(
                503, "The configured Ollama model is unavailable."
            ) from exc
        raise HTTPException(502, "Ollama could not generate the draft.") from exc
    except InvalidModelResponse as exc:
        raise HTTPException(
            502, "Ollama returned an incomplete or invalid DAP draft."
        ) from exc


@router.get("", response_model=list[ReportSummary])
def list_reports(
    request: Request, filters: Annotated[ReportFilters, Query()]
) -> list[ReportSummary]:
    """Return saved report summaries matching the filters, newest first."""
    return list_drafts(request.app.state.database_path, filters)


@router.get("/{report_id}", response_model=StoredReportDraft)
def read_report(report_id: UUID, request: Request) -> StoredReportDraft:
    """Retrieve the original notes and generated sections for review."""
    draft = get_draft(request.app.state.database_path, report_id)
    if draft is None:
        raise HTTPException(404, "Report draft not found.")
    return draft


@router.get(
    "/{report_id}/download",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}}
            }
        },
        404: {"description": "Report draft not found."},
    },
)
def download_report(report_id: UUID, request: Request) -> Response:
    """Download the current saved report as a PDF."""
    report = read_report(report_id, request)
    suffix = "-draft" if report.status == "draft" else ""
    filename = f"dap-{report.report_id}{suffix}.pdf"
    return Response(
        content=render_report_pdf(report),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.patch("/{report_id}", response_model=StoredReportDraft)
def edit_report(
    report_id: UUID, payload: EditReportRequest, request: Request
) -> StoredReportDraft:
    """Save corrected notes, sections, or report details while keeping draft status."""
    try:
        report = edit_draft(request.app.state.database_path, report_id, payload)
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report


@router.post("/{report_id}/regenerate", response_model=StoredReportDraft)
async def regenerate_report(
    report_id: UUID, payload: RegenerateReportRequest, request: Request
) -> StoredReportDraft:
    """Replace the notes and AI-generated sections on the same draft revision."""
    path = request.app.state.database_path
    current = await run_in_threadpool(get_draft, path, report_id)
    if current is None:
        raise HTTPException(404, "Report draft not found.")
    if current.status == "approved":
        raise HTTPException(409, "Approved reports are read-only.")
    if current.revision != payload.revision:
        raise HTTPException(409, "Report changed. Reload the current revision.")

    sections = await _generate_sections(payload.notes)
    edit = EditReportRequest(
        revision=payload.revision,
        notes=payload.notes,
        sections=sections,
        metadata=payload.metadata,
    )
    try:
        # Recheck the revision during the write in case it changed during inference.
        report = await run_in_threadpool(
            edit_draft, path, report_id, edit, ai_assisted=True
        )
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report


@router.delete("/{report_id}", status_code=204, response_class=Response)
def delete_report(
    report_id: UUID,
    revision: Annotated[int, Query(ge=1, le=2**63 - 1)],
    request: Request,
) -> Response:
    """Permanently delete the saved draft revision the user confirmed."""
    try:
        deleted = delete_draft(request.app.state.database_path, report_id, revision)
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Report draft not found.")
    return Response(status_code=204)


@router.post("/{report_id}/approve", response_model=StoredReportDraft)
def approve_report(
    report_id: UUID, payload: ApproveReportRequest, request: Request
) -> StoredReportDraft:
    """Explicitly approve the reviewed revision and make it read-only."""
    try:
        report = approve_draft(
            request.app.state.database_path,
            report_id,
            payload.revision,
            payload.approved_by,
        )
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report


@router.post("/{report_id}/reopen", response_model=StoredReportDraft)
def reopen_report(
    report_id: UUID, payload: ReportRevisionRequest, request: Request
) -> StoredReportDraft:
    """Reopen an approved report for corrections."""
    try:
        report = reopen_approved_report(
            request.app.state.database_path, report_id, payload.revision
        )
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report
