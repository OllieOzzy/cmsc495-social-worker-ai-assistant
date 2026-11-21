"""Exercise frontend recovery and HTTP client lifecycle through Streamlit widgets.

Most HTTP replies are mocked; no FastAPI process or Ollama server is needed.
The lifecycle cases use real HTTPX clients with an in-memory transport, and
the proxy regression case starts a temporary loopback-only HTTP server.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from documentation_assistant.frontend import api_client, reports
from tests.auth_helpers import sign_in_app

APP_PATH = Path(reports.__file__).with_name("app.py")
_USER = {
    "user_id": "test-owner",
    "username": "workflow-admin",
    "display_name": "Taylor Example",
    "role": "admin",
}


def authentication_response(request):
    """Supply login replies for recovery tests that isolate report transport failures."""
    if request.url.path == "/auth/login":
        return httpx.Response(
            200,
            json={
                "access_token": "t" * 43,
                "expires_at": "2099-01-01T00:00:00Z",
                "user": _USER,
            },
            request=request,
        )
    if request.url.path == "/auth/me":
        return httpx.Response(200, json=_USER, request=request)
    return None


@pytest.fixture
def saved_report():
    """Provide a report that can be displayed in history and opened for review."""
    return {
        "report_id": "12345678-abcd-1234-abcd-123456789abc",
        "owner_id": "test-owner",
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
    """Supply a mock session client whose backend requests each test configures."""
    get = Mock(
        return_value=httpx.Response(
            200,
            json={"models": []},
            request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
        )
    )
    client = Mock(get=get)
    monkeypatch.setattr(api_client, "_get_http_client", Mock(return_value=client))
    return client


@pytest.mark.parametrize(
    ("backend_url", "policies"),
    [("http://127.0.0.1:8000", [False]), ("http://example.test:8000", [True, False])],
)
def test_http_clients_are_reused_per_session_and_closed_on_release(
    monkeypatch, backend_url, policies
):
    """Real cached clients survive reruns without sharing state between sessions."""
    original_client = httpx.Client
    clients = []
    monkeypatch.setattr(api_client, "API_URL", backend_url)
    pool_count = len(policies)

    def respond(request):
        """Return healthy backend and Ollama replies without opening sockets."""
        payload = (
            {"models": []} if request.url.path == "/api/tags" else {"status": "ok"}
        )
        return httpx.Response(200, json=payload)

    def make_client(**kwargs):
        """Track real client instances and the proxy policy used for each pool."""
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append((client, kwargs))
        return client

    monkeypatch.setattr(httpx, "Client", make_client)
    script = """
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
from documentation_assistant.frontend.api_client import (
    _get_http_client, request_api, ollama_is_reachable,
)
# AppTest otherwise gives every app the same hardcoded session ID.
get_script_run_ctx().session_id = st.session_state["test_http_session_id"]
assert request_api("GET", "/health") == {"status": "ok"}
assert ollama_is_reachable()
if st.button("Release clients"):
    _get_http_client.clear()
"""
    first = AppTest.from_string(script)
    first.session_state["test_http_session_id"] = "http-first"
    first.run()
    assert not first.exception, first.exception
    first.run()
    assert not first.exception, first.exception
    assert len(clients) == pool_count
    assert [kwargs for _, kwargs in clients] == [
        {"trust_env": policy} for policy in policies
    ]

    second = AppTest.from_string(script)
    second.session_state["test_http_session_id"] = "http-second"
    second.run()
    assert not second.exception, second.exception
    assert len(clients) == 2 * pool_count
    assert all(not client.is_closed for client, _ in clients)

    first.button[0].click().run()
    assert not first.exception, first.exception
    assert all(client.is_closed for client, _ in clients[:pool_count])
    assert all(not client.is_closed for client, _ in clients[pool_count:])

    first.run()
    assert not first.exception, first.exception
    assert len(clients) == 3 * pool_count
    assert all(not client.is_closed for client, _ in clients[2 * pool_count :])
    # Explicit release also keeps the test's mocked clients from outliving its patch.
    first.button[0].click().run()
    second.button[0].click().run()
    assert all(client.is_closed for client, _ in clients)


def test_local_backend_is_reachable_with_environment_proxy_configured(monkeypatch):
    """Reach a real local server even with an unusable proxy and no NO_PROXY exception."""

    class HealthHandler(BaseHTTPRequestHandler):
        """Provide a minimal local health endpoint without launching FastAPI."""

        def do_GET(self):
            """Return a complete response so HTTPX does not wait for more data."""
            content = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            """Keep expected local requests out of pytest output."""

    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "")

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(api_client, "API_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        app = AppTest.from_string("""
from documentation_assistant.frontend.api_client import _get_http_client, request_api
try:
    assert request_api("GET", "/health", timeout=2) == {"status": "ok"}
finally:
    _get_http_client.clear()
""").run(timeout=10)
        assert not app.exception, app.exception
        assert not app.error
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_retry_opens_saved_draft_without_generating_duplicate(
    monkeypatch, saved_report, ollama_status
):
    """Generate once, fail the follow-up fetch, then recover the saved report via Retry."""
    report_path = f"/reports/{saved_report['report_id']}"
    fetches = 0

    def respond(method, url, **kwargs):
        """Fail only the first saved-report fetch to reproduce a lost follow-up reply."""
        nonlocal fetches
        request = httpx.Request(method, url)
        if auth_reply := authentication_response(request):
            return auth_reply
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
    ollama_status.request = request_api
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=10))
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
    assert (
        sum(
            httpx.URL(call.args[1]).path == "/reports/generate"
            for call in request_api.call_args_list
        )
        == 1
    )


def test_backend_reconnection_loads_history_after_status_check(
    monkeypatch, saved_report, ollama_status
):
    """Keep outage errors in the sidebar and reload history when the backend returns."""
    reachable = True

    def respond(method, url, **kwargs):
        """Expose a switchable health check and the existing saved report."""
        request = httpx.Request(method, url)
        if request.url.path == "/auth/me" and not reachable:
            raise httpx.ConnectError("Backend is stopped", request=request)
        if auth_reply := authentication_response(request):
            return auth_reply
        if request.url.path == "/health":
            if not reachable:
                raise httpx.ConnectError("Backend is stopped", request=request)
            return httpx.Response(200, json={"status": "ok"}, request=request)
        if method == "GET" and request.url.path == "/reports":
            return httpx.Response(200, json=[saved_report], request=request)
        raise AssertionError(f"Unexpected HTTP request: {method} {url}")

    request_api = Mock(side_effect=respond)
    ollama_status.request = request_api
    app = sign_in_app(AppTest.from_file(str(APP_PATH), default_timeout=10))
    request_api.reset_mock()
    reachable = False
    app.run()

    assert not app.exception, app.exception
    assert "Could not reach the report server" in app.main.error[0].value
    assert not app.text_area
    assert all(
        httpx.URL(call.args[1]).path != "/reports"
        for call in request_api.call_args_list
    )

    reachable = True
    app.button(key="retry_session").click().run()

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
