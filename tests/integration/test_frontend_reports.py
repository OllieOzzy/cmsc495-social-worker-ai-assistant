"""Exercise report editing through Streamlit, FastAPI, and a temporary database."""

from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.main import create_app
from documentation_assistant.frontend import api_client, reports

APP_PATH = Path(reports.__file__).with_name("app.py")


@pytest.fixture
def backend_for_ui(monkeypatch, tmp_path):
    """Connect Streamlit HTTP requests to FastAPI with an isolated SQLite database."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "frontend.db"))

    with TestClient(create_app()) as backend:

        def send_to_backend(method, url, **kwargs):
            """Route frontend requests through the actual API handlers."""
            response = backend.request(
                method,
                httpx.URL(url).path,
                json=kwargs["json"],
                params=kwargs["params"],
            )
            # Use the frontend's HTTP client type for status errors and decoding.
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=response.content,
                request=httpx.Request(method, url),
            )

        def ollama_status(url, **kwargs):
            """Provide optional AI status without starting Ollama."""
            assert url == "http://127.0.0.1:11434/api/tags"
            return httpx.Response(
                200, json={"models": []}, request=httpx.Request("GET", url)
            )

        client = Mock(request=send_to_backend, get=ollama_status)
        monkeypatch.setattr(api_client, "_get_http_client", Mock(return_value=client))
        yield backend


def test_history_navigation_and_filters_use_real_backend_pages(backend_for_ui):
    """Navigate a multi-page history, then apply and clear a filter from page two."""
    for index in range(27):
        response = backend_for_ui.post(
            "/reports/manual",
            json={"metadata": {"student_name": f"Student {index:02}"}},
        )
        assert response.status_code == 201

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    def button(label):
        return next(widget for widget in app.sidebar.button if widget.label == label)

    def history():
        return next(
            widget for widget in app.sidebar.selectbox if widget.label == "Report"
        )

    assert not app.exception, app.exception
    assert len(history().options) == 25
    assert "Student 26" in history().options[0]
    assert button("Previous").disabled
    assert not button("Next").disabled

    button("Next").click().run()
    assert not app.exception, app.exception
    assert len(history().options) == 2
    assert "Student 01" in history().options[0]
    assert button("Next").disabled
    assert not button("Previous").disabled

    next(
        widget for widget in app.sidebar.text_input if widget.label == "Student name"
    ).set_value("Student 26")
    button("Apply filters").click().run()
    assert not app.exception, app.exception
    assert len(history().options) == 1
    assert "Student 26" in history().options[0]
    assert button("Previous").disabled
    assert button("Next").disabled

    button("Clear filters").click().run()
    assert not app.exception, app.exception
    assert len(history().options) == 25
    button("Next").click().run()
    button("Previous").click().run()
    assert not app.exception, app.exception
    assert len(history().options) == 25
    assert "Student 26" in history().options[0]


def test_back_to_notes_saves_pending_edits_to_the_same_report(backend_for_ui):
    """Carry DAP and metadata edits through the notes screen before saving them."""
    backend = backend_for_ui
    initial = (
        backend.post(
            "/reports/manual",
            json={
                "notes": "Original synthetic notes.",
                "metadata": {"student_name": "Alex Example"},
            },
        )
        .raise_for_status()
        .json()
    )
    path = f"/reports/{initial['report_id']}"
    edited_sections = {
        "data": "The student practiced requesting help twice.",
        "assessment": "The second request was independent.",
        "plan": "Check in Friday after lunch.",
    }
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception

    for field, label in reports.DAP_FIELDS.items():
        next(widget for widget in app.text_area if widget.label == label).set_value(
            edited_sections[field]
        )
    next(widget for widget in app.text_input if widget.label == "School").set_value(
        "Example Middle School"
    )
    next(
        button for button in app.button if button.label == "Back to notes"
    ).click().run()

    assert not app.exception, app.exception
    assert "report" not in app.session_state
    pending = app.session_state["note_entry"]
    assert pending["report_id"] == initial["report_id"]
    assert pending["revision"] == initial["revision"]
    assert pending["sections"] == edited_sections
    assert (
        next(widget for widget in app.text_input if widget.label == "School").value
        == "Example Middle School"
    )
    assert (
        next(
            widget for widget in app.text_area if "Session Notes" in widget.label
        ).value
        == initial["notes"]
    )
    assert backend.get(path).raise_for_status().json() == initial

    edited_notes = "Revised synthetic notes after reviewing the draft."
    next(
        widget for widget in app.text_area if "Session Notes" in widget.label
    ).set_value(edited_notes)
    next(button for button in app.button if button.label == "Save notes").click().run()

    assert not app.exception, app.exception
    assert not app.error
    assert "note_entry" not in app.session_state
    assert app.session_state["report"]["report_id"] == initial["report_id"]
    stored = backend.get(path).raise_for_status().json()
    assert stored["revision"] == initial["revision"] + 1
    assert stored["notes"] == edited_notes
    assert stored["sections"] == edited_sections
    assert stored["metadata"]["school"] == "Example Middle School"
    assert stored["metadata"]["draft_source"] == "handwritten"
    for field, label in reports.DAP_FIELDS.items():
        assert (
            next(widget for widget in app.text_area if widget.label == label).value
            == edited_sections[field]
        )
    history = backend.get("/reports").raise_for_status().json()
    assert [item["report_id"] for item in history] == [initial["report_id"]]


def test_discard_changes_restores_saved_fields_without_writing(
    backend_for_ui, monkeypatch
):
    """Reset edited DAP and session details to the saved values without a save request."""
    backend = backend_for_ui
    initial = (
        backend.post(
            "/reports/manual",
            json={
                "notes": "Synthetic source notes.",
                "metadata": {"student_name": "Alex Example"},
            },
        )
        .raise_for_status()
        .json()
    )
    path = f"/reports/{initial['report_id']}"
    sections = {
        "data": "Saved observation.",
        "assessment": "Saved assessment.",
        "plan": "Saved follow-up plan.",
    }
    saved = (
        backend.patch(
            path, json={"revision": initial["revision"], "sections": sections}
        )
        .raise_for_status()
        .json()
    )
    client = api_client._get_http_client()
    request = Mock(wraps=client.request)
    monkeypatch.setattr(client, "request", request)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception

    for label in reports.DAP_FIELDS.values():
        next(widget for widget in app.text_area if widget.label == label).set_value(
            "Unsaved replacement."
        )
    next(
        widget for widget in app.text_input if widget.label == "Student name"
    ).set_value("Unsaved name")
    next(
        button for button in app.button if button.label == "Discard changes"
    ).click().run()

    assert not app.exception, app.exception
    assert not app.error
    assert any(message.value == "Unsaved changes discarded." for message in app.success)
    assert app.session_state["report"] == saved
    for field, label in reports.DAP_FIELDS.items():
        assert (
            next(widget for widget in app.text_area if widget.label == label).value
            == sections[field]
        )
    assert (
        next(
            widget for widget in app.text_input if widget.label == "Student name"
        ).value
        == "Alex Example"
    )
    assert backend.get(path).raise_for_status().json() == saved
    assert all(call.args[0] == "GET" for call in request.call_args_list)


def test_saved_dap_edits_survive_opening_another_report(backend_for_ui):
    """Save all three DAP sections, switch reports, and reopen the stored version."""
    edited_sections = {
        "data": "The student completed two practice requests for help.",
        "assessment": "The second request was completed independently.",
        "plan": "Check in Friday after lunch.",
    }

    backend = backend_for_ui
    first = (
        backend.post(
            "/reports/manual",
            json={
                "notes": "Synthetic notes for the first student.",
                "metadata": {"student_name": "Alex Example"},
            },
        )
        .raise_for_status()
        .json()
    )
    second = (
        backend.post(
            "/reports/manual",
            json={
                "notes": "Synthetic notes for the second student.",
                "metadata": {"student_name": "Sam Example"},
            },
        )
        .raise_for_status()
        .json()
    )

    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception

    picker = next(field for field in app.sidebar.selectbox if field.label == "Report")
    picker.select(first["report_id"])
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["report_id"] == first["report_id"]

    for field, label in reports.DAP_FIELDS.items():
        next(widget for widget in app.text_area if widget.label == label).set_value(
            edited_sections[field]
        )
    next(button for button in app.button if button.label == "Save draft").click().run()
    assert not app.exception, app.exception
    assert not app.error
    assert any(message.value == "Draft saved." for message in app.success)

    stored = backend.get(f"/reports/{first['report_id']}").raise_for_status().json()
    assert stored["sections"] == edited_sections
    assert stored["revision"] == first["revision"] + 1
    assert stored["notes"] == first["notes"]

    picker = next(field for field in app.sidebar.selectbox if field.label == "Report")
    picker.select(second["report_id"])
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["report_id"] == second["report_id"]
    for field, label in reports.DAP_FIELDS.items():
        assert (
            next(widget for widget in app.text_area if widget.label == label).value
            == second["sections"][field]
        )

    picker = next(field for field in app.sidebar.selectbox if field.label == "Report")
    picker.select(first["report_id"])
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["report_id"] == first["report_id"]
    assert app.session_state["report"]["revision"] == stored["revision"]
    for field, label in reports.DAP_FIELDS.items():
        assert (
            next(widget for widget in app.text_area if widget.label == label).value
            == edited_sections[field]
        )

    assert (
        backend.get(f"/reports/{second['report_id']}").raise_for_status().json()
        == second
    )


def test_approval_and_reopening_preserve_saved_content(backend_for_ui):
    """Block unsaved approval, lock the saved report, then reopen it for editing."""
    backend = backend_for_ui
    initial = (
        backend.post("/reports/manual", json={"notes": "Synthetic session notes."})
        .raise_for_status()
        .json()
    )
    path = f"/reports/{initial['report_id']}"
    sections = {
        "data": "The student practiced a request for help.",
        "assessment": "The second attempt was independent.",
        "plan": "Check in Friday.",
    }
    saved = (
        backend.patch(
            path, json={"revision": initial["revision"], "sections": sections}
        )
        .raise_for_status()
        .json()
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception

    edited_data = "The student completed two requests for help independently."
    next(
        widget for widget in app.text_area if widget.label == reports.DAP_FIELDS["data"]
    ).set_value(edited_data)
    next(
        widget for widget in app.text_input if widget.label == "Approver name"
    ).set_value("Taylor Example")
    next(
        button for button in app.button if button.label == "Approve saved draft"
    ).click().run()

    assert not app.exception, app.exception
    assert any(
        error.value == "Save your changes before approving this report."
        for error in app.error
    )
    assert backend.get(path).raise_for_status().json() == saved
    assert (
        next(
            widget
            for widget in app.text_area
            if widget.label == reports.DAP_FIELDS["data"]
        ).value
        == edited_data
    )

    next(button for button in app.button if button.label == "Save draft").click().run()
    assert not app.exception, app.exception
    saved = backend.get(path).raise_for_status().json()
    assert saved["sections"]["data"] == edited_data
    assert saved["revision"] == initial["revision"] + 2

    next(
        widget for widget in app.text_input if widget.label == "Approver name"
    ).set_value("Taylor Example")
    next(
        button for button in app.button if button.label == "Approve saved draft"
    ).click().run()

    assert not app.exception, app.exception
    assert not app.error
    approved = backend.get(path).raise_for_status().json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "Taylor Example"
    assert approved["approved_at"]
    assert approved["revision"] == saved["revision"] + 1
    for field, label in reports.DAP_FIELDS.items():
        widget = next(widget for widget in app.text_area if widget.label == label)
        assert widget.disabled
        assert widget.value == saved["sections"][field]
    assert next(
        button for button in app.button if button.label == "Save draft"
    ).disabled

    next(
        button for button in app.button if button.label == "Reopen as draft"
    ).click().run()
    assert not app.exception, app.exception
    assert any(
        error.value == "Confirm that you want to reopen this report."
        for error in app.error
    )
    assert backend.get(path).raise_for_status().json() == approved

    next(
        widget
        for widget in app.checkbox
        if widget.label == "I understand this clears the current approval"
    ).check()
    next(
        button for button in app.button if button.label == "Reopen as draft"
    ).click().run()

    assert not app.exception, app.exception
    assert not app.error
    reopened = backend.get(path).raise_for_status().json()
    assert reopened["report_id"] == initial["report_id"]
    assert reopened["status"] == "draft"
    assert reopened["approved_by"] is None
    assert reopened["approved_at"] is None
    assert reopened["revision"] == approved["revision"] + 1
    assert reopened["sections"] == saved["sections"]
    for field, label in reports.DAP_FIELDS.items():
        widget = next(widget for widget in app.text_area if widget.label == label)
        assert not widget.disabled
        assert widget.value == saved["sections"][field]
    assert not next(
        button for button in app.button if button.label == "Save draft"
    ).disabled


def test_stale_save_preserves_local_edits_and_current_database_version(backend_for_ui):
    """Reject an outdated save while retaining the first user's pending edits."""
    backend = backend_for_ui
    initial = (
        backend.post("/reports/manual", json={"notes": "Synthetic session notes."})
        .raise_for_status()
        .json()
    )
    path = f"/reports/{initial['report_id']}"
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["revision"] == initial["revision"]

    pending_sections = {
        "data": "The first user observed a practice request for help.",
        "assessment": "The first user recorded an independent attempt.",
        "plan": "The first user plans to check in Friday.",
    }
    for field, label in reports.DAP_FIELDS.items():
        next(widget for widget in app.text_area if widget.label == label).set_value(
            pending_sections[field]
        )
    next(
        widget for widget in app.text_input if widget.label == "Student name"
    ).set_value("Alex Example")

    # Another client saves the same report before the first user submits the form.
    latest = (
        backend.patch(
            path,
            json={
                "revision": initial["revision"],
                "sections": {
                    **initial["sections"],
                    "data": "The second user saved a different observation.",
                },
            },
        )
        .raise_for_status()
        .json()
    )
    assert latest["revision"] == initial["revision"] + 1

    next(button for button in app.button if button.label == "Save draft").click().run()

    assert not app.exception, app.exception
    assert any(
        error.value == "Report changed. Reload the current revision."
        for error in app.error
    )
    assert not any(message.value == "Draft saved." for message in app.success)
    assert app.session_state["report"]["revision"] == initial["revision"]
    assert (
        next(
            widget for widget in app.text_input if widget.label == "Student name"
        ).value
        == "Alex Example"
    )
    for field, label in reports.DAP_FIELDS.items():
        assert (
            next(widget for widget in app.text_area if widget.label == label).value
            == pending_sections[field]
        )
    assert backend.get(path).raise_for_status().json() == latest


def test_confirmed_draft_deletion_clears_review_and_refreshes_history(backend_for_ui):
    """Require confirmation, remove the selected draft, and retain the other report."""
    backend = backend_for_ui
    selected = (
        backend.post("/reports/manual", json={"notes": "Synthetic draft to delete."})
        .raise_for_status()
        .json()
    )
    retained = (
        backend.post("/reports/manual", json={"notes": "Synthetic draft to retain."})
        .raise_for_status()
        .json()
    )
    path = f"/reports/{selected['report_id']}"
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(widget for widget in app.sidebar.selectbox if widget.label == "Report").select(
        selected["report_id"]
    )
    next(
        button for button in app.sidebar.button if button.label == "Open report"
    ).click().run()
    assert not app.exception, app.exception
    assert app.session_state["report"]["report_id"] == selected["report_id"]

    next(
        button for button in app.button if button.label == "Delete draft"
    ).click().run()

    assert not app.exception, app.exception
    assert any(
        error.value == "Confirm that you want to delete this draft."
        for error in app.error
    )
    assert backend.get(path).raise_for_status().json() == selected
    assert app.session_state["report"]["report_id"] == selected["report_id"]

    next(
        widget
        for widget in app.checkbox
        if widget.label == "I understand this permanently deletes the draft"
    ).check()
    next(
        button for button in app.button if button.label == "Delete draft"
    ).click().run()

    assert not app.exception, app.exception
    assert not app.error
    assert backend.get(path).status_code == 404
    assert (
        backend.get(f"/reports/{retained['report_id']}").raise_for_status().json()
        == retained
    )
    assert "report" not in app.session_state
    assert "note_entry" not in app.session_state
    assert "pending_report_id" not in app.session_state
    assert any(message.value == "Draft deleted." for message in app.success)
    assert (
        next(
            widget for widget in app.text_area if "Session Notes" in widget.label
        ).value
        == ""
    )
    assert any(button.label == "Written by hand" for button in app.button)
    picker = next(
        widget for widget in app.sidebar.selectbox if widget.label == "Report"
    )
    assert picker.value == retained["report_id"]
    assert len(picker.options) == 1
    assert {
        item["report_id"] for item in backend.get("/reports").raise_for_status().json()
    } == {retained["report_id"]}


@pytest.mark.parametrize("notes", ["", " \n\t"])
def test_blank_notes_block_ai_generation_but_allow_handwritten_draft(
    backend_for_ui, monkeypatch, notes
):
    """Validate AI input while preserving the blank handwritten report workflow."""
    backend = backend_for_ui
    client = api_client._get_http_client()
    request = Mock(wraps=client.request)
    monkeypatch.setattr(client, "request", request)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception
    next(
        widget for widget in app.text_area if "Session Notes" in widget.label
    ).set_value(notes)
    next(
        button for button in app.button if button.label == "AI-assisted draft"
    ).click().run()

    assert not app.exception, app.exception
    assert any(
        error.value == "Enter session notes to create an AI-assisted draft."
        for error in app.error
    )
    assert all(call.args[0] != "POST" for call in request.call_args_list)
    assert "report" not in app.session_state
    assert "pending_report_id" not in app.session_state
    assert backend.get("/reports").raise_for_status().json() == []

    next(
        button for button in app.button if button.label == "Written by hand"
    ).click().run()

    assert not app.exception, app.exception
    assert not app.error
    report = app.session_state["report"]
    stored = backend.get(f"/reports/{report['report_id']}").raise_for_status().json()
    assert stored["status"] == "draft"
    assert not stored["notes"].strip()
    assert stored["metadata"]["draft_source"] == "handwritten"
    assert all(not section.strip() for section in stored["sections"].values())
    writes = [call for call in request.call_args_list if call.args[0] == "POST"]
    assert len(writes) == 1
    assert httpx.URL(writes[0].args[1]).path == "/reports/manual"
