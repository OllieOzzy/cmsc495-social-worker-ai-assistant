"""Exercise report editing through Streamlit, FastAPI, and a temporary database."""

from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from documentation_assistant.backend.main import create_app
from documentation_assistant.frontend import api_client, reports

APP_PATH = Path(reports.__file__).with_name("app.py")


def test_saved_dap_edits_survive_opening_another_report(monkeypatch, tmp_path):
    """Save all three DAP sections, switch reports, and reopen the stored version."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "frontend.db"))
    edited_sections = {
        "data": "The student completed two practice requests for help.",
        "assessment": "The second request was completed independently.",
        "plan": "Check in Friday after lunch.",
    }

    with TestClient(create_app()) as backend:
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

        def send_to_backend(method, url, **kwargs):
            """Route frontend HTTP requests through the actual FastAPI application."""
            return backend.request(
                method,
                httpx.URL(url).path,
                json=kwargs["json"],
                params=kwargs["params"],
            )

        def ollama_status(url, **kwargs):
            """Provide the optional service status without starting Ollama."""
            assert url == "http://127.0.0.1:11434/api/tags"
            return httpx.Response(
                200, json={"models": []}, request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(api_client.httpx, "request", send_to_backend)
        monkeypatch.setattr(api_client.httpx, "get", ollama_status)
        app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        assert not app.exception, app.exception

        picker = next(
            field for field in app.sidebar.selectbox if field.label == "Report"
        )
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
        next(
            button for button in app.button if button.label == "Save draft"
        ).click().run()
        assert not app.exception, app.exception
        assert not app.error
        assert any(message.value == "Draft saved." for message in app.success)

        stored = backend.get(f"/reports/{first['report_id']}").raise_for_status().json()
        assert stored["sections"] == edited_sections
        assert stored["revision"] == first["revision"] + 1
        assert stored["notes"] == first["notes"]

        picker = next(
            field for field in app.sidebar.selectbox if field.label == "Report"
        )
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

        picker = next(
            field for field in app.sidebar.selectbox if field.label == "Report"
        )
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
