"""Test report handlers with generation and storage mocked."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from documentation_assistant.backend.api import reports
from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    GenerateReportRequest,
    StoredReportDraft,
)

NOTES = "Synthetic student practiced a breathing exercise."


@pytest.fixture
def api_request(tmp_path):
    """Supply the application state that the handlers read from a request."""
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database_path=tmp_path / "test.db"))
    )


def test_generate_report_saves_valid_sections(monkeypatch, api_request):
    """Verify successful generation sends the notes and sections to storage."""
    sections = DAPSections(
        data=NOTES, assessment="Not documented.", plan="Not documented."
    )
    saved = StoredReportDraft(report_id=uuid4(), notes=NOTES, sections=sections)
    generate = AsyncMock(return_value=sections)
    store = AsyncMock(return_value=saved)
    monkeypatch.setattr(reports, "generate_dap", generate)
    monkeypatch.setattr(reports, "run_in_threadpool", store)

    result = asyncio.run(
        reports.generate_report(GenerateReportRequest(notes=NOTES), api_request)
    )

    assert result.model_dump() == {
        "report_id": saved.report_id,
        "sections": sections.model_dump(),
        "status": "draft",
    }
    generate.assert_awaited_once_with(NOTES)
    store.assert_awaited_once_with(
        reports.save_draft, api_request.app.state.database_path, NOTES, sections, None
    )


@pytest.mark.parametrize(
    ("failure", "status", "message"),
    [
        (
            httpx.ReadTimeout("timeout"),
            504,
            "Ollama timed out. Try again with shorter notes.",
        ),
        (
            httpx.ConnectError("offline"),
            503,
            "Could not reach local Ollama. Check that it is running.",
        ),
        (404, 503, "The configured Ollama model is unavailable."),
        (500, 502, "Ollama could not generate the draft."),
        (
            reports.InvalidModelResponse("invalid"),
            502,
            "Ollama returned an incomplete or invalid DAP draft.",
        ),
    ],
    ids=["timeout", "offline", "missing-model", "upstream-error", "invalid-draft"],
)
def test_generate_report_maps_upstream_failure(
    monkeypatch, api_request, failure, status, message
):
    """Verify upstream failures become API errors and skip the save."""
    # Integer cases represent HTTP response status codes from Ollama.
    if isinstance(failure, int):
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        failure = httpx.HTTPStatusError(
            "Ollama error", request=request, response=httpx.Response(failure)
        )
    store = AsyncMock()
    monkeypatch.setattr(reports, "generate_dap", AsyncMock(side_effect=failure))
    monkeypatch.setattr(reports, "run_in_threadpool", store)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            reports.generate_report(GenerateReportRequest(notes=NOTES), api_request)
        )

    assert (error.value.status_code, error.value.detail) == (status, message)
    store.assert_not_awaited()


def test_read_report_returns_saved_draft(monkeypatch, api_request):
    """Verify the handler returns the draft found by its ID."""
    draft = StoredReportDraft(
        report_id=uuid4(),
        notes=NOTES,
        sections=DAPSections(
            data=NOTES, assessment="Not documented.", plan="Not documented."
        ),
    )
    lookup = Mock(return_value=draft)
    monkeypatch.setattr(reports, "get_draft", lookup)

    assert reports.read_report(draft.report_id, api_request) is draft
    lookup.assert_called_once_with(api_request.app.state.database_path, draft.report_id)


def test_read_report_raises_404_for_missing_draft(monkeypatch, api_request):
    """Verify a missing draft produces a 404 error."""
    monkeypatch.setattr(reports, "get_draft", Mock(return_value=None))

    with pytest.raises(HTTPException) as error:
        reports.read_report(uuid4(), api_request)

    assert error.value.status_code == 404
