"""Verify report actions and session state with isolated frontend dependencies."""

from copy import deepcopy
from unittest.mock import MagicMock, Mock

import pytest

from documentation_assistant import OLLAMA_REQUEST_TIMEOUT_SECONDS
from documentation_assistant.frontend import reports

# Exercise the download handler without Streamlit's fragment scheduling wrapper.
_download_report = reports.report_download.__wrapped__


class RerunRequested(Exception):
    """Stop the current render just as Streamlit does when requesting a rerun."""


@pytest.fixture
def report():
    """Provide a saved draft with a revision and editable metadata."""
    return {
        "report_id": "example",
        "revision": 3,
        "status": "draft",
        "notes": "Synthetic source notes.",
        "sections": {
            "data": "Observed progress.",
            "assessment": "Not documented.",
            "plan": "Check in Friday.",
        },
        "metadata": {"student_name": "Alex Example"},
        "approved_by": None,
        "approved_at": None,
    }


@pytest.fixture
def ui(monkeypatch):
    """Echo saved values and leave report actions unselected until a test opts in.

    RerunRequested stops the handler where Streamlit would restart rendering.
    Metadata widgets and PDF controls are isolated in their own test modules.
    """
    streamlit = MagicMock()
    streamlit.session_state = {}
    streamlit.rerun.side_effect = RerunRequested
    streamlit.columns.return_value = (MagicMock(), MagicMock())
    streamlit.text_area.side_effect = lambda label, **kwargs: kwargs.get("value", "")
    streamlit.text_input.return_value = "Taylor Example"
    streamlit.form_submit_button.return_value = False
    streamlit.checkbox.return_value = False
    monkeypatch.setattr(reports, "st", streamlit)
    monkeypatch.setattr(
        reports,
        "session_details",
        Mock(side_effect=lambda metadata, **kwargs: dict(metadata)),
    )
    monkeypatch.setattr(reports, "report_download", Mock())
    monkeypatch.setattr(reports, "color_expander", Mock())
    monkeypatch.setattr(reports, "is_admin", Mock(return_value=True))
    monkeypatch.setattr(reports, "owns_report", Mock(return_value=True))
    return streamlit


@pytest.fixture
def api_request(monkeypatch):
    """Prevent real FastAPI requests and expose report operations for assertions."""
    api = Mock()
    monkeypatch.setattr(reports, "request_api", api)
    return api


def select_action(ui, label):
    """Submit one form action and respect disabled controls."""
    ui.form_submit_button.side_effect = (
        lambda text, **kwargs: text == label and not kwargs.get("disabled", False)
    )


def test_show_saved_report_clears_pending_entry_state(ui, report):
    """Opening a saved report clears its pending recovery state."""
    ui.session_state.update(note_entry={"notes": "Edits"}, pending_report_id="example")

    with pytest.raises(RerunRequested):
        reports.show_saved_report(report)

    assert ui.session_state == {"report": report}


@pytest.mark.parametrize("succeeds", [False, True])
def test_open_report_preserves_pending_id_until_fetch_succeeds(
    ui, api_request, report, succeeds
):
    """A failed fetch leaves the saved ID available for retry."""
    ui.session_state["pending_report_id"] = "example"
    api_request.return_value = report if succeeds else None

    if succeeds:
        with pytest.raises(RerunRequested):
            reports.open_report("example")
        assert ui.session_state == {"report": report}
    else:
        reports.open_report("example")
        assert ui.session_state == {"pending_report_id": "example"}
        ui.rerun.assert_not_called()
    api_request.assert_called_once_with("GET", "/reports/example")


def test_reset_entry_clears_report_and_advances_form_version(ui, report):
    """Reset report widgets without clearing unrelated user preferences."""
    ui.session_state.update(
        report=report,
        note_entry={},
        pending_report_id="example",
        note_entry_version=2,
        time_format="12h",
    )

    reports.reset_report_entry()

    assert ui.session_state == {"note_entry_version": 3, "time_format": "12h"}


def test_unsubmitted_new_report_makes_no_request(ui, api_request):
    """Rendering a new report must not save or generate a draft."""
    reports.new_report()

    api_request.assert_not_called()


@pytest.mark.parametrize("notes", ["", " \n\t"])
def test_ai_generation_requires_nonblank_notes(ui, api_request, notes):
    """Reject empty AI input before making an API api_request."""
    ui.text_area.side_effect = None
    ui.text_area.return_value = notes
    select_action(ui, "AI-assisted draft")

    reports.new_report()

    api_request.assert_not_called()
    ui.error.assert_called_once_with(
        "Enter session notes to create an AI-assisted draft."
    )


def test_manual_creation_allows_empty_notes(ui, api_request, report):
    """A handwritten report can start with blank notes and blank DAP fields."""
    select_action(ui, "Written by hand")
    api_request.return_value = report

    with pytest.raises(RerunRequested):
        reports.new_report()

    api_request.assert_called_once_with(
        "POST", "/reports/manual", payload={"notes": "", "metadata": {}}
    )
    assert ui.session_state["report"] == report


def test_generation_keeps_saved_id_when_followup_fetch_fails(ui, api_request):
    """Recover a generated draft without issuing a second generation api_request."""
    ui.text_area.side_effect = None
    ui.text_area.return_value = "Synthetic notes."
    select_action(ui, "AI-assisted draft")
    api_request.side_effect = [{"report_id": "example"}, None]

    with pytest.raises(RerunRequested):
        reports.new_report()

    assert ui.session_state["pending_report_id"] == "example"
    assert "report" not in ui.session_state
    assert api_request.call_args_list[0].args == ("POST", "/reports/generate")
    assert (
        api_request.call_args_list[0].kwargs["timeout"] > OLLAMA_REQUEST_TIMEOUT_SECONDS
    )
    assert api_request.call_args_list[1].args == ("GET", "/reports/example")
    assert api_request.call_count == 2


@pytest.mark.parametrize("action", ["Written by hand", "AI-assisted draft"])
def test_failed_creation_keeps_user_on_entry_screen(ui, api_request, action):
    """A failed save or generation must not navigate to an incomplete report."""
    ui.text_area.side_effect = None
    ui.text_area.return_value = "Synthetic notes."
    select_action(ui, action)
    api_request.return_value = None

    reports.new_report()

    assert "report" not in ui.session_state
    assert "pending_report_id" not in ui.session_state
    ui.rerun.assert_not_called()


@pytest.mark.parametrize("action", ["Save notes", "AI-assisted draft"])
def test_existing_note_entry_reuses_report_and_revision(
    ui, api_request, report, action
):
    """Saving notes preserves DAP sections while regeneration uses the same report."""
    ui.session_state["note_entry"] = deepcopy(report)
    select_action(ui, action)
    updated = {**report, "revision": 4}
    api_request.return_value = updated

    with pytest.raises(RerunRequested):
        reports.new_report()

    payload = {"notes": report["notes"], "metadata": report["metadata"], "revision": 3}
    if action == "Save notes":
        payload["sections"] = report["sections"]
        api_request.assert_called_once_with(
            "PATCH", "/reports/example", payload=payload
        )
    else:
        api_request.assert_called_once_with(
            "POST",
            "/reports/example/regenerate",
            payload=payload,
            timeout=reports._GENERATION_API_TIMEOUT,
        )
    assert ui.session_state["report"] == updated
    assert "note_entry" not in ui.session_state


def test_failed_note_save_keeps_pending_edits(ui, api_request, report):
    """A failed update retains the entry data for another attempt."""
    ui.session_state["note_entry"] = deepcopy(report)
    select_action(ui, "Save notes")
    api_request.return_value = None

    reports.new_report()

    assert ui.session_state["note_entry"] == report
    ui.rerun.assert_not_called()


def test_discard_entry_resets_form_without_saving(ui, api_request):
    """Discarding notes advances the form version and avoids backend writes."""
    select_action(ui, "Discard changes")

    with pytest.raises(RerunRequested):
        reports.new_report()

    assert ui.session_state["note_entry_version"] == 1
    api_request.assert_not_called()


def test_back_to_notes_keeps_edited_sections_and_report_identity(
    ui, api_request, report
):
    """Carry pending edits back to notes without saving them yet."""
    ui.session_state["report"] = report
    select_action(ui, "Back to notes")
    ui.text_area.side_effect = lambda label, **kwargs: (
        "Edited observation." if label.startswith("D: Data") else kwargs["value"]
    )

    with pytest.raises(RerunRequested):
        reports.review_report(report)

    pending = ui.session_state["note_entry"]
    assert pending["report_id"] == "example"
    assert pending["revision"] == 3
    assert pending["sections"]["data"] == "Edited observation."
    assert report["sections"]["data"] == "Observed progress."
    assert "report" not in ui.session_state
    api_request.assert_not_called()


@pytest.mark.parametrize("succeeds", [False, True])
def test_save_review_uses_revision_and_keeps_saved_state_on_failure(
    ui, api_request, report, succeeds
):
    """Only replace the displayed report when saving succeeds."""
    ui.session_state["report"] = report
    select_action(ui, "Save draft")
    updated = {**report, "revision": 4}
    api_request.return_value = updated if succeeds else None

    if succeeds:
        with pytest.raises(RerunRequested):
            reports.review_report(report)
        assert ui.session_state["report"] == updated
        assert ui.session_state["report_notice"] == "Draft saved."
    else:
        reports.review_report(report)
        assert ui.session_state["report"] == report
        assert "report_notice" not in ui.session_state
        ui.rerun.assert_not_called()
    api_request.assert_called_once_with(
        "PATCH",
        "/reports/example",
        payload={
            "revision": 3,
            "sections": report["sections"],
            "metadata": report["metadata"],
        },
    )


@pytest.mark.parametrize("changed", ["sections", "metadata"])
def test_approval_requires_pending_edits_to_be_saved(
    ui, api_request, report, monkeypatch, changed
):
    """Prevent approving a saved revision while displaying different content."""
    select_action(ui, "Approve saved draft")
    if changed == "sections":
        ui.text_area.side_effect = lambda label, **kwargs: "Edited content."
    else:
        monkeypatch.setattr(
            reports, "session_details", Mock(return_value={"student_name": "Changed"})
        )

    reports.review_report(report)

    api_request.assert_not_called()
    ui.error.assert_called_once_with("Save your changes before approving this report.")


def test_approval_does_not_request_an_editable_reviewer_name(ui, api_request, report):
    """Reviewer identity comes from the session rather than an editable text field."""
    select_action(ui, "Approve saved draft")
    ui.text_input.return_value = "  "

    api_request.return_value = None
    reports.review_report(report)
    ui.text_input.assert_not_called()
    api_request.assert_called_once_with(
        "POST", "/reports/example/approve", payload={"revision": 3}
    )


def test_approval_submits_only_revision(ui, api_request, report):
    """Approve the saved revision without supplying a client-controlled identity."""
    select_action(ui, "Approve saved draft")
    ui.text_input.return_value = " Taylor Example "
    updated = {**report, "status": "approved", "revision": 4}
    api_request.return_value = updated

    with pytest.raises(RerunRequested):
        reports.review_report(report)

    api_request.assert_called_once_with(
        "POST",
        "/reports/example/approve",
        payload={"revision": 3},
    )
    assert ui.session_state["report"] == updated


@pytest.mark.parametrize("confirmed", [False, True])
def test_deletion_requires_confirmation_and_current_revision(
    ui, api_request, report, confirmed
):
    """Delete a confirmed draft and clear its local selection only on success."""
    ui.session_state["report"] = report
    select_action(ui, "Delete draft")
    ui.checkbox.return_value = confirmed
    api_request.return_value = True

    if confirmed:
        with pytest.raises(RerunRequested):
            reports.review_report(report)
        api_request.assert_called_once_with(
            "DELETE", "/reports/example", params={"revision": 3}
        )
        assert "report" not in ui.session_state
        assert ui.session_state["report_notice"] == "Draft deleted."
    else:
        reports.review_report(report)
        api_request.assert_not_called()
        ui.error.assert_called_once_with("Confirm that you want to delete this draft.")


@pytest.mark.parametrize("confirmed", [False, True])
def test_reopening_requires_confirmation(ui, api_request, report, confirmed):
    """Reopen an approved revision only after the user confirms approval removal."""
    report["status"] = "approved"
    select_action(ui, "Reopen as draft")
    ui.checkbox.return_value = confirmed
    api_request.return_value = {**report, "status": "draft", "revision": 4}

    if confirmed:
        with pytest.raises(RerunRequested):
            reports.review_report(report)
        api_request.assert_called_once_with(
            "POST", "/reports/example/reopen", payload={"revision": 3}
        )
        assert ui.session_state["report"]["status"] == "draft"
    else:
        reports.review_report(report)
        api_request.assert_not_called()
        ui.error.assert_called_once_with("Confirm that you want to reopen this report.")


def test_failed_deletion_preserves_report_selection(ui, api_request, report):
    """Keep the draft open when the backend rejects or cannot complete deletion."""
    ui.session_state["report"] = report
    select_action(ui, "Delete draft")
    ui.checkbox.return_value = True
    api_request.return_value = None

    reports.review_report(report)

    assert ui.session_state["report"] == report
    assert "report_notice" not in ui.session_state
    ui.rerun.assert_not_called()


def test_discard_review_keeps_saved_content(ui, api_request, report):
    """Discarding pending edits resets widgets while retaining the saved draft."""
    ui.session_state["report"] = report
    select_action(ui, "Discard changes")

    with pytest.raises(RerunRequested):
        reports.review_report(report)

    assert ui.session_state["report"] == report
    assert ui.session_state["edit_form_version"] == 1
    api_request.assert_not_called()


def test_approved_report_disables_edit_actions(ui, api_request, report):
    """Display approved DAP sections read-only and omit approval and delete actions."""
    report.update(
        status="approved",
        approved_by="Taylor Example",
        approved_at="2026-11-18T14:00:00+00:00",
    )

    reports.review_report(report)

    assert all(call.kwargs["disabled"] for call in ui.text_area.call_args_list)
    actions = {
        call.args[0]: call.kwargs for call in ui.form_submit_button.call_args_list
    }
    assert actions["Save draft"]["disabled"] is True
    assert actions["Back to notes"]["disabled"] is True
    assert "Delete draft" not in actions
    assert "Approve saved draft" not in actions
    api_request.assert_not_called()


def test_pdf_preparation_waits_for_button(ui, api_request):
    """Rendering the download controls must not fetch a PDF automatically."""
    ui.button.return_value = False

    _download_report("example")

    api_request.assert_not_called()
    ui.download_button.assert_not_called()


def test_failed_pdf_request_does_not_offer_download(ui, api_request):
    """A failed fetch must not expose a download containing an error response."""
    ui.button.return_value = True
    api_request.return_value = None

    _download_report("example")

    api_request.assert_called_once_with("GET", "/reports/example/download", raw=True)
    ui.download_button.assert_not_called()


def test_pdf_preparation_rejects_other_content_types(ui, api_request):
    """Reject an HTML or JSON response even when the fetch itself succeeds."""
    ui.button.return_value = True
    api_request.return_value = Mock(headers={"content-type": "text/html"})

    _download_report("example")

    ui.error.assert_called_once_with("The report server did not return a PDF.")
    ui.download_button.assert_not_called()


@pytest.mark.parametrize("filename", [None, "session-note.pdf"])
def test_pdf_download_uses_response_filename_or_report_fallback(
    ui, api_request, filename
):
    """Offer the returned PDF bytes with the backend filename when supplied."""
    ui.button.return_value = True
    headers = {"content-type": "application/pdf"}
    if filename:
        headers["content-disposition"] = f'attachment; filename="{filename}"'
    api_request.return_value = Mock(headers=headers, content=b"%PDF-1.4")

    _download_report("example")

    options = ui.download_button.call_args.kwargs
    assert options["data"] == b"%PDF-1.4"
    assert options["file_name"] == (filename or "dap-example.pdf")
    assert options["mime"] == "application/pdf"
