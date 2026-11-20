"""Verify sidebar labels, filters, and navigation with isolated UI mocks."""

from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant.frontend import sidebar

# Test the status handler independently of Streamlit's fragment scheduler.
_show_service_status = sidebar.show_service_status.__wrapped__


class RerunRequested(Exception):
    """Stop the render after Streamlit requests a full rerun."""


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
        history_offset=25,
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
    ui.session_state["history_offset"] = 25
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
    assert "history_offset" not in ui.session_state
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

    request.assert_called_once_with(
        "GET", "/reports", params={**filters, "limit": 26, "offset": 0}
    )
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


@pytest.mark.parametrize("reachable", [False, True])
def test_status_button_color_reflects_reachability(ui, reachable):
    """Scope each button's status styling to its widget key."""
    sidebar.tint_status_button("check_backend", reachable)

    style = ui.html.call_args.args[0]
    assert ".st-key-check_backend button" in style
    assert ("#22a366" if reachable else "#df5353") in style


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        ({"status": "ok"}, True),
        ({"status": "error"}, False),
        ({}, False),
        (None, False),
        ([], False),
    ],
)
def test_status_checks_backend_response_without_requiring_a_click(
    ui, monkeypatch, health, expected
):
    """Only the expected health response marks the backend as reachable."""
    request = Mock(return_value=health)
    ollama = Mock(return_value=True)
    monkeypatch.setattr(sidebar, "request_api", request)
    monkeypatch.setattr(sidebar, "ollama_is_reachable", ollama)

    assert _show_service_status() is expected

    request.assert_called_once_with("GET", "/health", timeout=3)
    ollama.assert_called_once_with()
    styles = [call.args[0] for call in ui.html.call_args_list]
    assert len(styles) == 2
    assert ("#22a366" if expected else "#df5353") in styles[0]
    assert "#22a366" in styles[1]
    ui.success.assert_not_called()


def test_manual_backend_check_reports_success_when_history_is_loaded(ui, monkeypatch):
    """A manual check confirms availability without rerunning loaded history."""
    ui.button.side_effect = [True, False]
    ui.session_state["history_waiting_for_backend"] = False
    monkeypatch.setattr(sidebar, "request_api", Mock(return_value={"status": "ok"}))
    monkeypatch.setattr(sidebar, "ollama_is_reachable", Mock(return_value=True))

    assert _show_service_status() is True

    ui.success.assert_called_once_with("FastAPI is reachable.")
    ui.rerun.assert_not_called()


def test_backend_recheck_requests_rerun_for_waiting_history(ui, monkeypatch):
    """Once the backend returns, a manual check reloads the report sidebar."""
    ui.button.side_effect = [True, False]
    ui.session_state["history_waiting_for_backend"] = True
    ui.rerun.side_effect = RerunRequested
    monkeypatch.setattr(sidebar, "request_api", Mock(return_value={"status": "ok"}))
    monkeypatch.setattr(sidebar, "ollama_is_reachable", Mock(return_value=True))

    with pytest.raises(RerunRequested):
        _show_service_status()

    ui.rerun.assert_called_once_with()


@pytest.mark.parametrize("reachable", [False, True])
def test_manual_ai_check_shows_service_result(ui, monkeypatch, reachable):
    """Distinguish a reachable Ollama instance from an unavailable AI service."""
    ui.button.side_effect = [False, True]
    monkeypatch.setattr(sidebar, "request_api", Mock(return_value={"status": "ok"}))
    monkeypatch.setattr(sidebar, "ollama_is_reachable", Mock(return_value=reachable))

    assert _show_service_status() is True

    if reachable:
        ui.success.assert_called_once_with("Ollama is reachable.")
        ui.error.assert_not_called()
    else:
        ui.error.assert_called_once_with(
            "Could not reach local Ollama. Check that it is running."
        )
        ui.success.assert_not_called()
    assert ("#22a366" if reachable else "#df5353") in ui.html.call_args_list[1].args[0]


@pytest.mark.parametrize("reachable", [False, True])
def test_status_reruns_reuse_session_results(ui, monkeypatch, reachable):
    """Frequent page reruns reuse both results, including an offline backend."""
    now = Mock(return_value=100)
    # Advance the clock explicitly so expiration tests never sleep in real time.
    monkeypatch.setattr(sidebar, "monotonic", now)
    request = Mock(return_value={"status": "ok"} if reachable else None)
    ollama = Mock(return_value=reachable)
    monkeypatch.setattr(sidebar, "request_api", request)
    monkeypatch.setattr(sidebar, "ollama_is_reachable", ollama)

    assert _show_service_status() is reachable
    now.return_value = 159
    assert _show_service_status() is reachable

    request.assert_called_once_with("GET", "/health", timeout=3)
    ollama.assert_called_once_with()
    if not reachable:
        ui.error.assert_called_once_with(
            "Could not reach the report server. Check that FastAPI is running."
        )


def test_status_refreshes_at_sixty_seconds(ui, monkeypatch):
    """An expired result triggers new requests and updates both button colors."""
    now = Mock(return_value=100)
    monkeypatch.setattr(sidebar, "monotonic", now)
    request = Mock(side_effect=[None, {"status": "ok"}])
    ollama = Mock(side_effect=[False, True])
    monkeypatch.setattr(sidebar, "request_api", request)
    monkeypatch.setattr(sidebar, "ollama_is_reachable", ollama)

    assert _show_service_status() is False
    now.return_value = 160
    assert _show_service_status() is True

    assert request.call_count == 2
    assert ollama.call_count == 2
    assert all("#22a366" in call.args[0] for call in ui.html.call_args_list[-2:])


@pytest.mark.parametrize("service", ["backend", "ollama"])
def test_manual_status_check_bypasses_only_its_own_cache(ui, monkeypatch, service):
    """Manual retry refreshes the selected service even before its result expires."""
    monkeypatch.setattr(sidebar, "monotonic", Mock(return_value=100))
    request = Mock(return_value={"status": "ok"})
    ollama = Mock(return_value=True)
    monkeypatch.setattr(sidebar, "request_api", request)
    monkeypatch.setattr(sidebar, "ollama_is_reachable", ollama)
    _show_service_status()
    request.reset_mock()
    ollama.reset_mock()
    ui.button.side_effect = [service == "backend", service == "ollama"]

    assert _show_service_status() is True

    assert request.call_count == (1 if service == "backend" else 0)
    assert ollama.call_count == (1 if service == "ollama" else 0)


def test_new_report_resets_selection_and_reruns(ui, monkeypatch):
    """Starting a new report resets entry state before reloading the page."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    reset = Mock()
    monkeypatch.setattr(sidebar, "reset_report_entry", reset)
    request = Mock()
    monkeypatch.setattr(sidebar, "request_api", request)
    ui.button.return_value = True
    ui.rerun.side_effect = RerunRequested

    with pytest.raises(RerunRequested):
        sidebar.show_sidebar()

    reset.assert_called_once_with()
    ui.rerun.assert_called_once_with()
    request.assert_not_called()


def test_failed_history_fetch_does_not_show_empty_history_message(ui, monkeypatch):
    """A failed query must not tell the user there are no saved reports."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={}))
    monkeypatch.setattr(sidebar, "request_api", Mock(return_value=None))
    open_report = Mock()
    monkeypatch.setattr(sidebar, "open_report", open_report)

    sidebar.show_sidebar()

    ui.caption.assert_not_called()
    ui.selectbox.assert_not_called()
    open_report.assert_not_called()


def test_history_selection_waits_for_open_button(ui, monkeypatch):
    """Listing saved reports must not automatically open the selected item."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={}))
    monkeypatch.setattr(
        sidebar,
        "request_api",
        Mock(return_value=[{"report_id": "example-report", "status": "draft"}]),
    )
    open_report = Mock()
    monkeypatch.setattr(sidebar, "open_report", open_report)

    sidebar.show_sidebar()

    open_report.assert_not_called()
    options = ui.selectbox.call_args.kwargs
    assert options["options"] == ["example-report"]
    assert (
        options["format_func"]("example-report") == "Untitled report · example- · Draft"
    )


@pytest.mark.parametrize(
    ("offset", "previous", "expected_offset"), [(0, False, 25), (25, True, 0)]
)
def test_history_page_navigation(ui, monkeypatch, offset, previous, expected_offset):
    """Show only 25 reports and request the adjacent page when clicked."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={"grade": "8"}))
    request = Mock(
        return_value=[
            {"report_id": str(index), "status": "draft"} for index in range(26)
        ]
    )
    monkeypatch.setattr(sidebar, "request_api", request)
    ui.session_state["history_offset"] = offset
    ui.button.side_effect = [False, previous, not previous]
    ui.rerun.side_effect = RerunRequested

    with pytest.raises(RerunRequested):
        sidebar.show_sidebar()

    assert len(ui.selectbox.call_args.kwargs["options"]) == 25
    assert ui.session_state["history_offset"] == expected_offset
    request.assert_called_once_with(
        "GET", "/reports", params={"grade": "8", "limit": 26, "offset": offset}
    )


def test_empty_last_history_page_returns_to_previous_page(ui, monkeypatch):
    """Deleting the last item on a page must not strand the user on an empty page."""
    monkeypatch.setattr(sidebar, "show_service_status", Mock(return_value=True))
    monkeypatch.setattr(sidebar, "report_filters", Mock(return_value={}))
    monkeypatch.setattr(sidebar, "request_api", Mock(return_value=[]))
    ui.session_state["history_offset"] = 25
    ui.rerun.side_effect = RerunRequested

    with pytest.raises(RerunRequested):
        sidebar.show_sidebar()

    assert ui.session_state["history_offset"] == 0
