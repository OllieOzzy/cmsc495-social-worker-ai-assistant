"""Test report request and response validation."""

from datetime import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from documentation_assistant.backend.schemas.reports import (
    DAPSections,
    GenerateReportRequest,
    InvalidSessionTimeRange,
    ReportDraft,
    ReportMetadata,
    SavedReportMetadata,
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


@pytest.mark.parametrize("field", ["start_time", "end_time"])
@pytest.mark.parametrize(
    "value", ["09:00:00Z", "09:00:00-05:00", "09:00:01", "09:00:00.000001"]
)
def test_session_times_reject_timezones_seconds_and_microseconds(field, value):
    """Require local times with minute precision for either session boundary."""
    with pytest.raises(ValidationError) as error:
        ReportMetadata.model_validate({field: value})

    assert error.value.errors()[0]["loc"] == (field,)
    assert "Use a local time in HH:MM format" in error.value.errors()[0]["msg"]


@pytest.mark.parametrize("field", ["start_time", "end_time"])
@pytest.mark.parametrize("value", [None, "00:00", "12:00", "23:59", "09:00:00"])
def test_session_times_accept_optional_local_minute_values(field, value):
    """Accept blank boundaries and round-tripped times whose seconds are zero."""
    metadata = ReportMetadata.model_validate({field: value})

    assert getattr(metadata, field) == (time.fromisoformat(value) if value else None)


@pytest.mark.parametrize("changes", [{"start_time": "09:30"}, {"end_time": "08:55"}])
def test_partial_time_edit_checks_against_saved_boundary(changes):
    """A one-field edit must not silently reverse the existing session range."""
    saved = ReportMetadata(start_time="09:00", end_time="09:25")
    edited = ReportMetadata.model_validate(changes)

    with pytest.raises(
        InvalidSessionTimeRange, match="End time must be at or after start time"
    ):
        edited.validate_time_range(saved)

    assert saved.start_time == time(9)
    assert saved.end_time == time(9, 25)


@pytest.mark.parametrize(
    "changes",
    [
        {"end_time": "09:30"},
        {"start_time": "08:55"},
        {"end_time": "09:00"},
        {"start_time": "09:25"},
        {"grade": "8"},
        {"start_time": "10:00", "end_time": None},
        {"start_time": None, "end_time": "08:00"},
        {"start_time": None, "end_time": None},
    ],
)
def test_time_edits_allow_valid_ranges_and_explicit_clearing(changes):
    """Distinguish omitted saved times from an explicit request to clear them."""
    saved = ReportMetadata(start_time="09:00", end_time="09:25")
    edited = ReportMetadata.model_validate(changes)

    edited.validate_time_range(saved)

    # Explicit nulls must remain distinguishable from omitted fields in PATCH requests.
    assert edited.model_fields_set == set(changes)
    assert saved.start_time == time(9)
    assert saved.end_time == time(9, 25)


@pytest.mark.parametrize(
    ("start", "end", "minutes"),
    [
        (None, None, None),
        ("09:00", None, None),
        (None, "09:25", None),
        ("09:00", "09:00", 0),
        ("09:00", "09:25", 25),
        ("00:00", "23:59", 1439),
        ("23:59", "00:00", None),
    ],
)
def test_saved_duration_handles_missing_equal_and_reversed_times(start, end, minutes):
    """Calculate same-day minutes without treating an overnight range as valid."""
    metadata = SavedReportMetadata(start_time=start, end_time=end)

    assert metadata.total_minutes == minutes
