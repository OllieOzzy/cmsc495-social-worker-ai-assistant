"""Verify sidebar labels, filters, and navigation with isolated UI mocks."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import sidebar


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {
                "student_name": "Alex Example",
                "student_id": "SYN-001",
                "date_of_service": "2026-11-18",
            },
            "Alex Example · 2026-11-18 · 12345678 · Draft",
        ),
        ({"student_name": "", "student_id": "SYN-001"}, "SYN-001 · 12345678 · Draft"),
        ({}, "Untitled report · 12345678 · Draft"),
        (None, "Untitled report · 12345678 · Draft"),
    ],
)
def test_report_label_uses_available_student_details(metadata, expected):
    """Prefer student name, then ID, then a fallback for incomplete metadata."""
    report = {
        "report_id": "12345678-abcd-1234-abcd-123456789abc",
        "status": "draft",
        "metadata": metadata,
    }

    assert sidebar.report_label(report) == expected


def test_report_label_handles_missing_metadata_and_approved_status():
    """Reports without metadata still have a short ID and readable status."""
    report = {"report_id": "12345678-abcd-1234-abcd-123456789abc", "status": "approved"}

    assert sidebar.report_label(report) == "Untitled report · 12345678 · Approved"


@pytest.fixture
def ui(monkeypatch):
    """Provide empty form inputs and a separate session state for each test."""
    streamlit = MagicMock()
    streamlit.session_state = {}
    streamlit.text_input.return_value = ""
    streamlit.selectbox.return_value = ""
    streamlit.form_submit_button.return_value = False
    streamlit.button.return_value = False
    monkeypatch.setattr(sidebar, "st", streamlit)
    monkeypatch.setattr(sidebar, "date_input", Mock(return_value=None))
    return streamlit


def test_clear_filters_preserves_unrelated_session_state(ui):
    """Clear all search values while preserving the currently opened report."""
    ui.session_state.update(
        {f"filter_{field}": "old value" for field in sidebar.FILTER_FIELDS}
    )
    ui.session_state.update(
        filter_status="draft",
        filter_date_from="2026-11-01",
        filter_date_to="2026-11-18",
        active_report_filters={"status": "draft"},
        report={"report_id": "example"},
    )

    sidebar.clear_report_filters()
    sidebar.clear_report_filters()

    assert ui.session_state == {"report": {"report_id": "example"}}


def test_unsubmitted_filter_edits_keep_last_applied_filters(ui):
    """Typing into the form must not apply the search before submission."""
    ui.session_state["active_report_filters"] = {"status": "approved"}
    ui.text_input.return_value = "Changed search"

    assert sidebar.report_filters() == {"status": "approved"}


def test_initial_filters_are_empty(ui):
    """Load report history without filters before the first search."""
    assert sidebar.report_filters() == {}


def test_applied_filters_trim_text_and_omit_empty_values(ui, monkeypatch):
    """Send trimmed search terms and optional dates in the API's expected format."""
    ui.text_input.side_effect = [" Alex ", " ", " Example School ", "", "", " Taylor "]
    ui.selectbox.return_value = "draft"
    ui.form_submit_button.side_effect = [True, False]
    monkeypatch.setattr(
        sidebar, "date_input", Mock(side_effect=["2026-11-01", "2026-11-18"])
    )
    expected = {
        "student_name": "Alex",
        "school": "Example School",
        "approved_by": "Taylor",
        "status": "draft",
        "date_from": "2026-11-01",
        "date_to": "2026-11-18",
    }

    assert sidebar.report_filters() == expected
    assert ui.session_state["active_report_filters"] == expected
    ui.error.assert_not_called()


def test_applying_blank_filters_clears_previous_search(ui):
    """Submitting a blank form restores unfiltered history."""
    ui.session_state["active_report_filters"] = {"student_name": "Alex"}
    ui.form_submit_button.side_effect = [True, False]

    assert sidebar.report_filters() == {}
    assert ui.session_state["active_report_filters"] == {}


@pytest.mark.parametrize(
    ("date_from", "date_to"),
    [("2026-11-18", "2026-11-18"), ("2026-11-18", None), (None, "2026-11-18")],
)
def test_filter_dates_allow_same_day_and_open_ranges(
    ui, monkeypatch, date_from, date_to
):
    """Support a single service date or a search with only one date bound."""
    ui.form_submit_button.side_effect = [True, False]
    monkeypatch.setattr(sidebar, "date_input", Mock(side_effect=[date_from, date_to]))
    expected = {
        field: value
        for field, value in (("date_from", date_from), ("date_to", date_to))
        if value
    }

    assert sidebar.report_filters() == expected
    ui.error.assert_not_called()


def test_reversed_date_range_keeps_previous_filters(ui, monkeypatch):
    """Reject reversed dates without discarding the last valid search."""
    ui.session_state["active_report_filters"] = {"status": "draft"}
    ui.form_submit_button.side_effect = [True, False]
    monkeypatch.setattr(
        sidebar, "date_input", Mock(side_effect=["2026-11-18", "2026-11-01"])
    )

    assert sidebar.report_filters() == {"status": "draft"}
    ui.error.assert_called_once_with("Choose a start date on or before the end date.")


def test_offline_sidebar_skips_history_request(ui, monkeypatch):
    """Avoid issuing report queries when the service check has failed."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=False))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={}))
    request = Mock()
    monkeypatch.setattr(sidebar, "request_api", request)

    sidebar.show_sidebar()

    assert ui.session_state["history_waiting_for_backend"] is True
    request.assert_not_called()


@pytest.mark.parametrize(
    ("filters", "message"),
    [({}, "No saved reports yet."), ({"status": "draft"}, "No matching reports.")],
)
def test_empty_history_shows_contextual_message(ui, monkeypatch, filters, message):
    """Distinguish empty report storage from an empty search result."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value=filters))
    request = Mock(return_value=[])
    monkeypatch.setattr(sidebar, "request_api", request)

    sidebar.show_sidebar()

    request.assert_called_once_with("GET", "/reports", params=filters)
    assert ui.session_state["history_waiting_for_backend"] is False
    ui.caption.assert_called_once_with(message)


def test_open_report_uses_selected_id(ui, monkeypatch):
    """Open the selected report instead of using its display label."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={}))
    monkeypatch.setattr(
        sidebar,
        "request_api",
        Mock(
            return_value=[
                {"report_id": "first-report", "status": "draft"},
                {"report_id": "second-report", "status": "approved"},
            ]
        ),
    )
    ui.selectbox.return_value = "second-report"
    ui.form_submit_button.return_value = True
    open_report = Mock()
    monkeypatch.setattr(sidebar, "open_report", open_report)

    sidebar.show_sidebar()

    open_report.assert_called_once_with("second-report")
