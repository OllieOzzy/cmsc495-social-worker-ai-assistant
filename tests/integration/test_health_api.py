"""Test the health endpoint and its generated API documentation."""

import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.main import create_app


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Keep startup initialization isolated from the user's database."""
    monkeypatch.setenv("DAP_DB_PATH", str(tmp_path / "health.db"))
    return create_app()


def test_health_is_available_without_external_services(app):
    """Verify the assembled API reports that it is up."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_documents_health_response(app):
    """Verify OpenAPI lists a successful health response."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "200" in schema["paths"]["/health"]["get"]["responses"]
