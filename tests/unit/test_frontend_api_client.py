"""Verify frontend API responses are handled without a running server."""

from unittest.mock import Mock

import httpx
import pytest

from documentation_assistant.frontend import api_client


@pytest.fixture
def api_mocks(monkeypatch):
    """Replace the cached client and error display without creating a UI session.

    Responses remain real HTTPX objects so status errors and JSON parsing
    behave as they do for network replies.
    """
    request = Mock()
    error = Mock()
    monkeypatch.setattr(
        api_client, "_get_http_client", Mock(return_value=Mock(request=request))
    )
    monkeypatch.setattr(api_client.st, "error", error)
    return request, error


@pytest.mark.parametrize("status", [409, 422, 502, 503, 504])
@pytest.mark.parametrize(
    "body",
    [
        "<html>Server unavailable</html>",
        "{}",
        "[]",
        "null",
        '{"detail": null}',
        '{"detail": []}',
        '{"detail": " "}',
    ],
)
def test_error_with_unusable_detail_shows_fallback(api_mocks, status, body):
    """Keep malformed server errors from crashing frontend recovery."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        status, text=body, request=httpx.Request("GET", "http://test/reports")
    )

    assert api_client.request_api("GET", "/reports") is None

    error.assert_called_once_with(
        f"The server could not complete the request ({status})."
    )


@pytest.mark.parametrize("status", [409, 422, 502, 503, 504])
def test_error_preserves_readable_detail(api_mocks, status):
    """Keep the backend's validation, conflict, and generation explanations visible."""
    request, error = api_mocks
    message = "Reload this report before saving your changes."
    request.return_value = httpx.Response(
        status,
        json={"detail": message},
        request=httpx.Request("PATCH", "http://test/reports/example"),
    )

    assert api_client.request_api("PATCH", "/reports/example") is None

    error.assert_called_once_with(message)


def test_validation_errors_identify_fields_without_exposing_input(api_mocks):
    """Show each usable validation message while ignoring malformed error entries."""
    request, error = api_mocks
    field_error = {
        "loc": ["body", "metadata", "end_time"],
        "msg": "Use a local time in HH:MM format",
        "input": "Private submitted value",
        "ctx": {"error": "Internal context"},
    }
    request.return_value = httpx.Response(
        422,
        json={
            "detail": [
                field_error,
                field_error,
                {
                    "loc": ["body", "notes"],
                    "msg": "String should have at most 4000 characters",
                },
                {"loc": ["body"], "msg": "Invalid request"},
                None,
                "broken",
                {},
                {"msg": []},
                {"msg": "  "},
            ]
        },
        request=httpx.Request("POST", "http://test/reports/generate"),
    )

    assert api_client.request_api("POST", "/reports/generate") is None

    error.assert_called_once_with(
        "End time: Use a local time in HH:MM format\n\n"
        "Notes: String should have at most 4000 characters\n\nInvalid request"
    )


@pytest.mark.parametrize("location", [None, {}, [], ["body", 0], ["query"], [None]])
def test_validation_message_survives_missing_or_unusable_locations(api_mocks, location):
    """Keep readable messages even when a field location cannot be displayed."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        422,
        json={"detail": [{"loc": location, "msg": "Correct this value."}]},
        request=httpx.Request("PATCH", "http://test/reports/example"),
    )

    assert api_client.request_api("PATCH", "/reports/example") is None
    error.assert_called_once_with("Correct this value.")


@pytest.mark.parametrize("detail", [[None, {}, {"msg": None}], 123, {"msg": "Invalid"}])
def test_validation_errors_with_no_readable_message_use_fallback(api_mocks, detail):
    """Malformed validation bodies must still produce a safe fallback."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        422,
        json={"detail": detail},
        request=httpx.Request("PATCH", "http://test/reports/example"),
    )

    assert api_client.request_api("PATCH", "/reports/example") is None
    error.assert_called_once_with("The server could not complete the request (422).")


def test_success_with_invalid_json_shows_error(api_mocks):
    """Report an invalid JSON reply instead of raising during decoding."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        200, text="invalid JSON", request=httpx.Request("GET", "http://test/reports")
    )

    assert api_client.request_api("GET", "/reports") is None

    error.assert_called_once_with(
        "The report server returned an invalid JSON response. Try again."
    )


@pytest.mark.parametrize("body", [{"report_id": "example"}, []])
def test_success_returns_json(api_mocks, body):
    """Return decoded reports and empty history responses."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        200, json=body, request=httpx.Request("GET", "http://test/reports")
    )

    assert api_client.request_api("GET", "/reports") == body

    error.assert_not_called()


def test_delete_without_content_returns_true(api_mocks):
    """Successful deletion needs no JSON response body."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        204, request=httpx.Request("DELETE", "http://test/reports/example")
    )

    assert api_client.request_api("DELETE", "/reports/example") is True

    error.assert_not_called()


def test_raw_pdf_returns_response_without_decoding(api_mocks):
    """Keep PDF downloads available through the API client."""
    request, error = api_mocks
    response = httpx.Response(
        200,
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
        request=httpx.Request("GET", "http://test/reports/example/download"),
    )
    request.return_value = response

    assert (
        api_client.request_api("GET", "/reports/example/download", raw=True) is response
    )

    error.assert_not_called()


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_failure_shows_error(api_mocks, failure):
    """Keep outages visible without raising an HTTP exception in Streamlit."""
    request, error = api_mocks
    request.side_effect = failure("The server did not respond")

    assert api_client.request_api("GET", "/reports") is None

    error.assert_called_once_with(
        "Could not reach the report server. Check that FastAPI is running."
    )


def test_request_forwards_payload_filters_and_timeout(api_mocks, monkeypatch):
    """Send report content and options to the configured backend address."""
    request, error = api_mocks
    monkeypatch.setattr(api_client, "API_URL", "http://example.test:9000")
    payload = {"revision": 2, "notes": "Synthetic session notes."}
    params = {"status": "draft"}
    request.return_value = httpx.Response(
        200,
        json={"revision": 3},
        request=httpx.Request("PATCH", "http://example.test:9000/reports/example"),
    )

    result = api_client.request_api(
        "PATCH", "/reports/example", payload=payload, params=params, timeout=255
    )

    assert result == {"revision": 3}
    request.assert_called_once_with(
        "PATCH",
        "http://example.test:9000/reports/example",
        json=payload,
        params=params,
        timeout=255,
    )
    error.assert_not_called()


@pytest.mark.parametrize(
    ("url", "trust_env"),
    [
        ("http://127.0.0.1:8000", False),
        ("http://127.0.0.2:8000/api", False),
        ("http://localhost:8000", False),
        ("http://LOCALHOST.:8000", False),
        ("http://[::1]:8000", False),
        ("https://reports.example.test", True),
        ("http://192.168.1.10:8000", True),
        ("http://backend:8000", True),
        ("http://localhost.example.test:8000", True),
        ("http://127.0.0.1@reports.example.test:8000", True),
    ],
)
def test_backend_proxy_policy_uses_the_actual_destination(
    api_mocks, monkeypatch, url, trust_env
):
    """Bypass proxies for loopback only, preserving remote and container configuration."""
    request, error = api_mocks
    monkeypatch.setattr(api_client, "API_URL", url)
    request.return_value = httpx.Response(
        200, json={"status": "ok"}, request=httpx.Request("GET", f"{url}/health")
    )

    assert api_client.request_api("GET", "/health") == {"status": "ok"}
    api_client._get_http_client.assert_called_once_with(trust_env=trust_env)
    error.assert_not_called()


@pytest.mark.parametrize("status", [400, 404, 422, 500])
def test_other_http_errors_show_status_message(api_mocks, status):
    """Explain unsuccessful requests even when the response is an HTML page."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        status,
        text="<html>Request failed</html>",
        request=httpx.Request("GET", "http://test/reports"),
    )

    assert api_client.request_api("GET", "/reports") is None

    error.assert_called_once_with(
        f"The server could not complete the request ({status})."
    )


def test_raw_download_failure_shows_error(api_mocks):
    """Handle a failed PDF download before returning a raw HTTP response."""
    request, error = api_mocks
    request.return_value = httpx.Response(
        404, request=httpx.Request("GET", "http://test/reports/example/download")
    )

    assert api_client.request_api("GET", "/reports/example/download", raw=True) is None

    error.assert_called_once_with("The server could not complete the request (404).")


@pytest.fixture
def ollama_get(monkeypatch):
    """Replace the local Ollama status request without starting a server."""
    get = Mock()
    monkeypatch.setattr(
        api_client, "_get_http_client", Mock(return_value=Mock(get=get))
    )
    return get


@pytest.mark.parametrize("models", [[], [{"name": "qwen3:8b"}]])
def test_ollama_status_accepts_empty_and_populated_model_lists(ollama_get, models):
    """A reachable Ollama server can have zero models installed."""
    ollama_get.return_value = httpx.Response(
        200,
        json={"models": models},
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    assert api_client.ollama_is_reachable() is True
    api_client._get_http_client.assert_called_once_with(trust_env=False)

    ollama_get.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=3)


@pytest.mark.parametrize(
    "body",
    ["invalid JSON", "null", "[]", "{}", '{"models": null}', '{"models": {}}'],
)
def test_ollama_status_rejects_unusable_model_lists(ollama_get, body):
    """An unexpected response must not mark AI Status as reachable."""
    ollama_get.return_value = httpx.Response(
        200,
        text=body,
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    assert api_client.ollama_is_reachable() is False


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_ollama_status_handles_connection_failures(ollama_get, failure):
    """Treat an unavailable or slow Ollama server as unreachable."""
    ollama_get.side_effect = failure("The local Ollama server did not respond")

    assert api_client.ollama_is_reachable() is False


def test_ollama_status_handles_http_errors(ollama_get):
    """An error response must not mark AI Status as reachable."""
    ollama_get.return_value = httpx.Response(
        503,
        json={"models": []},
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    assert api_client.ollama_is_reachable() is False
