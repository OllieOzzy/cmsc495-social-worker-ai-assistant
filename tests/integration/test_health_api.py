"""Test the health endpoint and its generated API documentation."""

from fastapi.testclient import TestClient

from documentation_assistant.backend.main import app


def test_health_is_available_without_external_services():
    """Verify the assembled API reports that it is up."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_documents_health_response():
    """Verify OpenAPI lists a successful health response."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "200" in schema["paths"]["/health"]["get"]["responses"]
