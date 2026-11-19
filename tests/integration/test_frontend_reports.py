"""Exercise report editing through Streamlit, FastAPI, and a temporary database."""

from pathlib import Path

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
            return backend.request(
                method,
                httpx.URL(url).path,
                json=kwargs["json"],
                params=kwargs["params"],
            )

        def ollama_status(url, **kwargs):
            """Provide optional AI status without starting Ollama."""
            assert url == "http://127.0.0.1:11434/api/tags"
            return httpx.Response(
                200, json={"models": []}, request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(api_client.httpx, "request", send_to_backend)
        monkeypatch.setattr(api_client.httpx, "get", ollama_status)
        yield backend


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
