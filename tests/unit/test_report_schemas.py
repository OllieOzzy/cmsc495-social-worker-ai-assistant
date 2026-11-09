"""Test report request and response validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    GenerateReportRequest,
    ReportDraft,
)


def test_request_trims_notes_before_checking_maximum_length():
    """Verify surrounding whitespace does not count toward the notes limit."""
    notes = "x" * 4000
    request = GenerateReportRequest(notes=f" {notes} ")
    assert request.notes == notes


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({}, "missing"),
        ({"notes": "  "}, "string_too_short"),
        ({"notes": "x" * 4001}, "string_too_long"),
        ({"notes": "Synthetic notes.", "student_id": "SYN-01"}, "extra_forbidden"),
    ],
)
def test_request_rejects_invalid_input(payload, error_type):
    """Verify invalid payloads produce the expected validation error."""
    with pytest.raises(ValidationError) as error:
        GenerateReportRequest.model_validate(payload)

    assert error.value.errors()[0]["type"] == error_type


@pytest.mark.parametrize("section", ["data", "assessment", "plan"])
def test_dap_sections_reject_blank_text(section):
    """Verify each DAP section rejects whitespace-only content."""
    sections = dict.fromkeys(("data", "assessment", "plan"), "Not documented.")
    sections[section] = " "

    with pytest.raises(ValidationError) as error:
        DAPSections.model_validate(sections)

    assert error.value.errors()[0]["loc"] == (section,)


def test_generated_report_schema_rejects_approved_status():
    """Verify generated reports only accept draft status."""
    sections = DAPSections(
        data="Synthetic student practiced a breathing exercise.",
        assessment="Not documented.",
        plan="Not documented.",
    )

    with pytest.raises(ValidationError) as error:
        ReportDraft.model_validate(
            {"report_id": uuid4(), "status": "approved", "sections": sections}
        )

    assert error.value.errors()[0]["loc"] == ("status",)
