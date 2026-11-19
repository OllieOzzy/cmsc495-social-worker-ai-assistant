"""API endpoints for creating, finding, reviewing, and exporting DAP reports."""

from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, Response
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
    InvalidSessionTimeRange,
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

_SESSION_EXAMPLE = {
    "notes": "The student practiced asking for help.",
    "metadata": {"start_time": "09:00", "end_time": "09:25"},
}
_SAVED_SESSION_EXAMPLE = {
    "start_time": "09:00:00",
    "end_time": "09:25:00",
    "draft_source": "handwritten",
    "total_minutes": 25,
}
ReportId = Annotated[
    UUID,
    Path(
        description="Use the report_id returned when you create or list saved reports."
    ),
]


@router.post(
    "/manual",
    response_model=StoredReportDraft,
    status_code=201,
    responses={
        201: {
            "content": {
                "application/json": {
                    "example": {
                        "report_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "sections": {"data": "", "assessment": "", "plan": ""},
                        "notes": _SESSION_EXAMPLE["notes"],
                        "metadata": _SAVED_SESSION_EXAMPLE,
                        "status": "draft",
                        "revision": 1,
                    }
                }
            }
        }
    },
)
def create_manual_report(
    payload: Annotated[
        ManualReportRequest,
        Body(
            openapi_examples={
                "session": {"summary": "Manual draft", "value": _SESSION_EXAMPLE}
            }
        ),
    ],
    request: Request,
) -> StoredReportDraft:
    """Save a manual draft with optional source notes and blank DAP sections."""
    metadata = (payload.metadata or ReportMetadata()).model_copy(
        update={"draft_source": "handwritten"}
    )
    _validate_session_times(metadata)
    return save_draft(
        request.app.state.database_path,
        payload.notes,
        DraftSections(data="", assessment="", plan=""),
        metadata,
    )


@router.post("/generate", response_model=ReportDraft)
async def generate_report(
    payload: Annotated[
        GenerateReportRequest,
        Body(
            openapi_examples={
                "session": {"summary": "AI-assisted draft", "value": _SESSION_EXAMPLE}
            }
        ),
    ],
    request: Request,
) -> ReportDraft:
    """Generate DAP sections with Ollama and save them as an unapproved draft."""
    metadata = (payload.metadata or ReportMetadata()).model_copy(
        update={"draft_source": "ai_assisted"}
    )
    _validate_session_times(metadata)
    sections = await _generate_sections(payload.notes)
    # Keep the synchronous SQLite write from blocking other async requests.
    draft = await run_in_threadpool(
        save_draft,
        request.app.state.database_path,
        payload.notes,
        sections,
        metadata,
    )
    return ReportDraft(report_id=draft.report_id, sections=sections)


def _validate_session_times(
    metadata: ReportMetadata, saved: ReportMetadata | None = None
) -> None:
    """Reject reversed session times with HTTP 422, using saved times if needed."""
    try:
        metadata.validate_time_range(saved)
    except InvalidSessionTimeRange as exc:
        raise HTTPException(422, str(exc)) from exc


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
    """Return a page of saved report summaries matching the filters, newest first."""
    return list_drafts(request.app.state.database_path, filters)


@router.get("/{report_id}", response_model=StoredReportDraft)
def read_report(report_id: ReportId, request: Request) -> StoredReportDraft:
    """Return the saved report, including its source notes and current revision."""
    draft = get_draft(request.app.state.database_path, report_id)
    if draft is None:
        raise HTTPException(404, "Report draft not found.")
    return draft


@router.get(
    "/{report_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "Downloadable PDF file for the saved report.",
            "content": {
                "application/pdf": {"schema": {"type": "string", "format": "binary"}}
            },
        },
        404: {"description": "Report draft not found."},
    },
)
def download_report(report_id: ReportId, request: Request) -> Response:
    """Download the current saved draft or approved report as a PDF."""
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
    report_id: ReportId,
    payload: Annotated[
        EditReportRequest,
        Body(
            openapi_examples={
                "session": {
                    "summary": "Update session times using the current revision",
                    "value": {"revision": 1, "metadata": _SESSION_EXAMPLE["metadata"]},
                }
            }
        ),
    ],
    request: Request,
) -> StoredReportDraft:
    """Update notes, DAP sections, or metadata on the current draft revision."""
    try:
        report = edit_draft(request.app.state.database_path, report_id, payload)
    except InvalidSessionTimeRange as exc:
        raise HTTPException(422, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report


@router.post("/{report_id}/regenerate", response_model=StoredReportDraft)
async def regenerate_report(
    report_id: ReportId,
    payload: Annotated[
        RegenerateReportRequest,
        Body(
            openapi_examples={
                "session": {
                    "summary": "Regenerate a draft using the current revision",
                    "value": {"revision": 1, **_SESSION_EXAMPLE},
                }
            }
        ),
    ],
    request: Request,
) -> StoredReportDraft:
    """Save corrected notes and regenerated DAP sections as a new revision."""
    path = request.app.state.database_path
    current = await run_in_threadpool(get_draft, path, report_id)
    if current is None:
        raise HTTPException(404, "Report draft not found.")
    if current.status == "approved":
        raise HTTPException(409, "Approved reports are read-only.")
    if current.revision != payload.revision:
        raise HTTPException(409, "Report changed. Reload the current revision.")

    # An omitted time stays as saved. Check the resulting range before inference.
    if (
        payload.metadata
        and {"start_time", "end_time"} & payload.metadata.model_fields_set
    ):
        _validate_session_times(payload.metadata, current.metadata)
    sections = await _generate_sections(payload.notes)
    edit = EditReportRequest(
        revision=payload.revision,
        notes=payload.notes,
        sections=sections,
        metadata=payload.metadata,
    )
    try:
        # Check the revision again so AI output cannot overwrite a newer edit.
        report = await run_in_threadpool(
            edit_draft, path, report_id, edit, ai_assisted=True
        )
    except InvalidSessionTimeRange as exc:
        raise HTTPException(422, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report


@router.delete("/{report_id}", status_code=204, response_class=Response)
def delete_report(
    report_id: ReportId,
    revision: Annotated[int, Query(ge=1, le=2**63 - 1)],
    request: Request,
) -> Response:
    """Permanently delete a draft when the supplied revision is current."""
    try:
        deleted = delete_draft(request.app.state.database_path, report_id, revision)
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Report draft not found.")
    return Response(status_code=204)


@router.post("/{report_id}/approve", response_model=StoredReportDraft)
def approve_report(
    report_id: ReportId, payload: ApproveReportRequest, request: Request
) -> StoredReportDraft:
    """Approve the current draft once all three DAP sections contain text."""
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


@router.post(
    "/{report_id}/reopen",
    response_model=StoredReportDraft,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "report_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "sections": {
                            "data": _SESSION_EXAMPLE["notes"],
                            "assessment": "Not documented.",
                            "plan": "Not documented.",
                        },
                        "notes": _SESSION_EXAMPLE["notes"],
                        "metadata": _SAVED_SESSION_EXAMPLE,
                        "status": "draft",
                        "revision": 4,
                    }
                }
            }
        },
        404: {"description": "No report matches the supplied ID."},
        409: {"description": "The report is already a draft or the revision is stale."},
    },
)
def reopen_report(
    report_id: ReportId,
    payload: Annotated[
        ReportRevisionRequest,
        Body(
            openapi_examples={
                "approved": {
                    "summary": "Example only. Use the current approved revision.",
                    "value": {"revision": 3},
                }
            }
        ),
    ],
    request: Request,
) -> StoredReportDraft:
    """Return an approved report to draft and clear its approval details.

    Use the report ID and current approved revision from the approval response
    or from GET /reports/{report_id}.
    """
    try:
        report = reopen_approved_report(
            request.app.state.database_path, report_id, payload.revision
        )
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if report is None:
        raise HTTPException(404, "Report draft not found.")
    return report
