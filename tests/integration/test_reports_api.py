import json

import httpx
import pytest
from fastapi.testclient import TestClient

from documentation_assistant.backend.main import app

NOTES = "Synthetic student practiced a breathing exercise."


@pytest.fixture
def mock_ollama(monkeypatch):
    original_client = httpx.AsyncClient

    def configure(handler):
        def make_client(**kwargs):
            return original_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", make_client)

    return configure


def test_generation_returns_an_unapproved_draft(mock_ollama):
    sections = {
        "data": NOTES,
        "assessment": "Not documented.",
        "plan": "Not documented.",
    }

    def reply(request):
        payload = json.loads(request.content)
        assert request.url == "http://127.0.0.1:11434/api/chat"
        assert payload["messages"][1] == {"role": "user", "content": NOTES}
        assert set(payload["format"]["required"]) == {"data", "assessment", "plan"}
        return httpx.Response(
            200, json={"done": True, "message": {"content": json.dumps(sections)}}
        )

    mock_ollama(reply)
    with TestClient(app) as client:
        response = client.post("/reports/generate", json={"notes": NOTES})
    assert response.status_code == 200
    assert response.json() == {"status": "draft", "sections": sections}


def test_blank_notes_never_reach_ollama(mock_ollama):
    def unexpected_call(request):
        pytest.fail("Blank notes should be rejected before calling Ollama")

    mock_ollama(unexpected_call)
    with TestClient(app) as client:
        assert client.post("/reports/generate", json={"notes": "  "}).status_code == 422


@pytest.mark.parametrize(
    "failure, status", [("offline", 503), ("timeout", 504), ("invalid", 502)]
)
def test_generation_returns_clear_upstream_errors(mock_ollama, failure, status):
    def reply(request):
        if failure == "offline":
            raise httpx.ConnectError("Connection refused", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        return httpx.Response(200, json={"done": True, "message": {"content": "{}"}})

    mock_ollama(reply)
    with TestClient(app) as client:
        response = client.post("/reports/generate", json={"notes": NOTES})
    assert response.status_code == status
    assert "Ollama" in response.json()["detail"]
