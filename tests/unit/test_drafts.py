"""Test draft storage with a mocked SQLite connection."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from documentation_assistant.backend.db import drafts
from documentation_assistant.backend.schemas.reports import DAPSections, ReportMetadata

METADATA_FIELD_COUNT = len(ReportMetadata.model_fields)


@pytest.fixture
def mock_connect(monkeypatch):
    """Replace the connection used by the draft functions."""
    connect = MagicMock()
    monkeypatch.setattr(drafts, "connect", connect)
    return connect


def test_save_draft_inserts_notes_and_sections(mock_connect):
    """Verify the insert matches the returned draft."""
    path = Path("unused.db")
    notes = "Synthetic student practiced a breathing exercise."
    sections = DAPSections(
        data="Breathing exercise practiced.",
        assessment="Not documented.",
        plan="Not documented.",
    )
    execute = mock_connect.return_value.__enter__.return_value.execute

    draft = drafts.save_draft(path, notes, sections)

    assert draft.notes == notes
    assert draft.sections == sections
    assert draft.status == "draft"
    mock_connect.assert_called_once_with(path)
    execute.assert_called_once()
    assert execute.call_args.args[1] == (
        str(draft.report_id),
        notes,
        sections.data,
        sections.assessment,
        sections.plan,
        *(None,) * METADATA_FIELD_COUNT,
    )


def test_list_drafts_maps_timestamps_and_legacy_rows(mock_connect):
    """Verify draft summaries include UTC timestamps when available."""
    first_id, second_id = uuid4(), uuid4()
    execute = mock_connect.return_value.__enter__.return_value.execute
    execute.return_value.fetchall.return_value = [
        (
            str(first_id),
            "2026-11-09T15:30:00Z",
            "approved",
            "Taylor Example",
            "Synthetic Student",
            None,
            None,
            None,
            None,
            "Jordan Example",
            "iep",
            *(None,) * (METADATA_FIELD_COUNT - 7),
        ),
        (str(second_id), None, "draft", None, *(None,) * METADATA_FIELD_COUNT),
    ]

    first, second = drafts.list_drafts(Path("unused.db"))

    assert (first.report_id, first.created_at) == (
        first_id,
        datetime(2026, 11, 9, 15, 30, tzinfo=UTC),
    )
    assert (second.report_id, second.created_at) == (second_id, None)
    assert first.metadata is not None
    assert first.metadata.student_name == "Synthetic Student"
    assert first.metadata.social_worker_name == "Jordan Example"
    assert first.metadata.service_basis == "iep"
    assert first.status == "approved"
    assert first.approved_by == "Taylor Example"
    assert second.metadata is None


def test_get_draft_maps_row_to_report(mock_connect):
    """Verify a database row becomes a draft with nested DAP sections."""
    path = Path("unused.db")
    report_id = uuid4()
    notes = "Synthetic student practiced a breathing exercise."
    sections = ("Breathing exercise practiced.", "Not documented.", "Check in Friday.")
    execute = mock_connect.return_value.__enter__.return_value.execute
    execute.return_value.fetchone.return_value = (
        notes,
        *sections,
        "draft",
        1,
        None,
        None,
        *(None,) * METADATA_FIELD_COUNT,
    )

    draft = drafts.get_draft(path, report_id)

    assert draft is not None
    assert draft.model_dump() == {
        "report_id": report_id,
        "status": "draft",
        "notes": notes,
        "metadata": None,
        "revision": 1,
        "approved_at": None,
        "approved_by": None,
        "sections": dict(zip(("data", "assessment", "plan"), sections, strict=True)),
    }
    mock_connect.assert_called_once_with(path)
    execute.assert_called_once()
    assert execute.call_args.args[1] == (str(report_id),)


def test_get_draft_returns_none_for_missing_row(mock_connect):
    """Verify an unmatched lookup returns None."""
    execute = mock_connect.return_value.__enter__.return_value.execute
    execute.return_value.fetchone.return_value = None

    assert drafts.get_draft(Path("unused.db"), uuid4()) is None
