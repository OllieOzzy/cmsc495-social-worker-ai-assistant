"""Share an authenticated backend transport for Streamlit integration tests."""

from unittest.mock import Mock

import httpx
import pytest

from documentation_assistant.backend.main import create_app
from documentation_assistant.frontend import api_client
from tests.auth_helpers import AuthenticatedTestClient as TestClient


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
                headers={
                    "Authorization": kwargs.get("headers", {}).get("Authorization", "")
                },
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
