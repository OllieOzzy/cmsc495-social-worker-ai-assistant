"""Exercise frontend recovery through Streamlit widgets with mocked HTTP replies."""

from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from documentation_assistant.frontend import api_client, reports

APP_PATH = Path(reports.__file__).with_name("app.py")


@pytest.fixture
def saved_report():
    """Provide a report that can be displayed in history and opened for review."""
    return {
        "report_id": "12345678-abcd-1234-abcd-123456789abc",
        "revision": 1,
        "status": "draft",
        "notes": "The student practiced asking for help.",
        "sections": {
            "data": "The student practiced asking for help.",
            "assessment": "The student completed the second attempt independently.",
            "plan": "Check in Friday.",
        },
        "metadata": {"student_name": "Alex Example", "draft_source": "ai_assisted"},
        "approved_by": None,
        "approved_at": None,
    }


@pytest.fixture
def ollama_status(monkeypatch):
    """Allow AI status checks without contacting a running Ollama instance."""
    get = Mock(
        return_value=httpx.Response(
            200,
            json={"models": []},
            request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
        )
    )
    monkeypatch.setattr(api_client.httpx, "get", get)
    return get


def test_retry_opens_saved_draft_without_generating_duplicate(
    monkeypatch, saved_report, ollama_status
):
    """Generate once, fail the follow-up fetch, then recover the saved report via Retry."""
    report_path = f"/reports/{saved_report['report_id']}"
    fetches = 0

    def respond(method, url, **kwargs):
        nonlocal fetches
        request = httpx.Request(method, url)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if method == "GET" and request.url.path == "/reports":
            return httpx.Response(200, json=[], request=request)
        if method == "POST" and request.url.path == "/reports/generate":
            assert kwargs["json"]["notes"] == saved_report["notes"]
            return httpx.Response(
                200, json={"report_id": saved_report["report_id"]}, request=request
            )
        if method == "GET" and request.url.path == report_path:
            fetches += 1
            if fetches == 1:
                raise httpx.ConnectError(
                    "Connection lost after saving", request=request
                )
            return httpx.Response(200, json=saved_report, request=request)
        raise AssertionError(f"Unexpected HTTP request: {method} {url}")

    request_api = Mock(side_effect=respond)
    monkeypatch.setattr(api_client.httpx, "request", request_api)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
    assert not app.exception, app.exception

    next(field for field in app.text_area if "Session Notes" in field.label).set_value(
        saved_report["notes"]
    )
    next(
        button for button in app.button if button.label == "AI-assisted draft"
    ).click().run()

    assert not app.exception, app.exception
    assert app.session_state["pending_report_id"] == saved_report["report_id"]
    assert "report" not in app.session_state
    assert any("Your draft was saved" in warning.value for warning in app.warning)
    assert all(button.label != "AI-assisted draft" for button in app.button)

    app.button(key="retry_opening_draft").click().run()

    assert not app.exception, app.exception
    assert app.session_state["report"] == saved_report
    assert "pending_report_id" not in app.session_state
    assert any(
        field.value == saved_report["sections"]["data"] for field in app.text_area
    )
    assert fetches == 2
    assert sum(call.args[0] == "POST" for call in request_api.call_args_list) == 1


def test_backend_reconnection_loads_history_after_status_check(
    monkeypatch, saved_report, ollama_status
):
    """Keep outage errors in the sidebar and reload history when the backend returns."""
    reachable = False

    def respond(method, url, **kwargs):
        request = httpx.Request(method, url)
        if request.url.path == "/health":
            if not reachable:
                raise httpx.ConnectError("Backend is stopped", request=request)
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if method == "GET" and request.url.path == "/reports":
            return httpx.Response(200, json=[saved_report], request=request)
        raise AssertionError(f"Unexpected HTTP request: {method} {url}")

    request_api = Mock(side_effect=respond)
    monkeypatch.setattr(api_client.httpx, "request", request_api)
    app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()

    assert not app.exception, app.exception
    assert app.session_state["history_waiting_for_backend"] is True
    assert len(app.sidebar.error) == 1
    assert "Could not reach the report server" in app.sidebar.error[0].value
    assert not app.main.error
    assert all(
        httpx.URL(call.args[1]).path != "/reports"
        for call in request_api.call_args_list
    )

    reachable = True
    app.button(key="check_backend").click().run()

    assert not app.exception, app.exception
    assert app.session_state["history_waiting_for_backend"] is False
    assert not app.sidebar.error
    report_picker = next(
        widget for widget in app.sidebar.selectbox if widget.label == "Report"
    )
    assert report_picker.value == saved_report["report_id"]
    assert any("Alex Example" in label for label in report_picker.options)
    assert any(button.label == "Open report" for button in app.sidebar.button)
    assert any(
        httpx.URL(call.args[1]).path == "/reports"
        for call in request_api.call_args_list
    )
