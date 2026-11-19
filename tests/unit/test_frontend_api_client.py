"""Verify frontend API responses are handled without a running server."""

from unittest.mock import Mock

import httpx
import pytest

from documentation_assistant.frontend import api_client


@pytest.fixture
def api_mocks(monkeypatch):
    """Replace HTTP requests and Streamlit error messages for each test."""
    request = Mock()
    error = Mock()
    monkeypatch.setattr(api_client.httpx, "request", request)
    monkeypatch.setattr(api_client.st, "error", error)
    return request, error


@pytest.mark.parametrize("status", [409, 502, 503, 504])
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


@pytest.mark.parametrize("status", [409, 502, 503, 504])
def test_error_preserves_readable_detail(api_mocks, status):
    """Keep the backend's conflict and generation explanations visible."""
    request, error = api_mocks
    message = "Reload this report before saving your changes."
    request.return_value = httpx.Response(
        status,
        json={"detail": message},
        request=httpx.Request("PATCH", "http://test/reports/example"),
    )

    assert api_client.request_api("PATCH", "/reports/example") is None

    error.assert_called_once_with(message)


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


def test_connection_failure_shows_error(api_mocks):
    """Keep outages visible without raising an HTTP exception in Streamlit."""
    request, error = api_mocks
    request.side_effect = httpx.ConnectError("Connection refused")

    assert api_client.request_api("GET", "/reports") is None

    error.assert_called_once_with(
        "Could not reach the report server. Check that FastAPI is running."
    )
